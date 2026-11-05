"""Explicit geometric queries. No perception, collision planning or action generation."""
import math

from ..common import ContextError, elapsed, fail, unique

SCALE = {'m': 1., 'cm': .01, 'mm': .001}
IDENTITY = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]


def unit(name):
    if name not in SCALE: fail('unsupported_unit', 'Unsupported length unit: ' + name)
    return SCALE[name]


def vector(values): return [float(v) for v in values]
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def norm(v): return math.sqrt(dot(v, v))
def add(a, b): return [x + y for x, y in zip(a, b)]
def scale(a, s): return [x * s for x in a]
def transpose(r): return [list(row) for row in zip(*r)]
def mv(r, v): return [dot(row, v) for row in r]
def mm(a, b): return [[dot(row, col) for col in zip(*b)] for row in a]


def rotation(value):
    if value['representation'] == 'matrix3':
        r = [vector(row) for row in value['rows']]
    else:
        q = vector(value['values'])
        if abs(dot(q, q) - 1) > 1e-9: fail('invalid_rotation', 'Quaternion must have unit norm')
        x, y, z, w = q if value['order'] == 'xyzw' else q[1:] + q[:1]
        r = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
             [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
             [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    gram = mm(transpose(r), r)
    det = r[0][0]*(r[1][1]*r[2][2]-r[1][2]*r[2][1])-r[0][1]*(r[1][0]*r[2][2]-r[1][2]*r[2][0])+r[0][2]*(r[1][0]*r[2][1]-r[1][1]*r[2][0])
    if abs(det - 1) > 1e-9 or any(abs(gram[i][j]-IDENTITY[i][j]) > 1e-9 for i in range(3) for j in range(3)):
        fail('invalid_rotation', 'Expected orthonormal proper rotation')
    return r


class Geometry:
    def __init__(self, inv):
        self.inv = inv
        self.frames = unique(inv.input['frames'])
        self.cameras = unique(inv.input.get('cameras', []))
        self.transforms = unique(inv.input.get('transforms', []))
        self.shapes = unique(inv.input.get('geometry', []))
        if len(self.frames) > 256 or len(self.transforms) > 1024:
            fail('invalid_request', 'Frame graph exceeds bounded geometry limit')

    def frame(self, name):
        if name not in self.frames: fail('missing_frame', 'Undeclared frame: ' + name)
        return self.frames[name]

    def path(self, source, target, time):
        self.frame(source); self.frame(target)
        if self.frame(source)['handedness'] != self.frame(target)['handedness']:
            fail('unsupported_handedness', 'Handedness conversion is not a rigid transform')
        known = {source: (IDENTITY, [0., 0., 0.], [])}
        pending, temporal_missing = [source], False
        while pending:
            node = pending.pop(0)
            current_r, current_t, current_refs = known[node]
            for edge in self.transforms.values():
                if node not in (edge['source_frame'], edge['target_frame']): continue
                a, b = edge['source_frame'], edge['target_frame']
                if self.frame(a)['handedness'] != self.frame(b)['handedness']:
                    fail('unsupported_handedness', 'Rigid edge joins different handedness')
                temporal = edge['temporal']
                if temporal['kind'] == 'sample':
                    if time is None:
                        temporal_missing = True; continue
                    try: matches = elapsed(temporal['time'], time) == 0
                    except ContextError: matches = False
                    if not matches: temporal_missing = True; continue
                r = rotation(edge['rotation'])
                t = scale(vector(edge['translation']), unit(edge['length_unit']))
                next_node = b
                if node == b:
                    next_node = a; r = transpose(r); t = scale(mv(r, t), -1)
                candidate = (mm(r, current_r), add(mv(r, current_t), t), current_refs + edge['evidence_refs'])
                if next_node in known:
                    old_r, old_t, _ = known[next_node]
                    if any(abs(candidate[0][i][j]-old_r[i][j]) > 1e-9 for i in range(3) for j in range(3)) or any(abs(x-y)>1e-9 for x,y in zip(candidate[1], old_t)):
                        fail('ambiguous_transform', 'Frame paths disagree (rotation 1e-9; translation 1e-9 m)')
                else:
                    known[next_node] = candidate; pending.append(next_node)
        if target not in known:
            fail('transform_time_unavailable' if temporal_missing else 'missing_transform', 'No consistent transform path at query time')
        return known[target]

    def point(self, point, source, target, time):
        r, t, refs = self.path(source, target, time)
        p = add(mv(r, scale(vector(point), unit(self.frame(source)['length_unit']))), t)
        return scale(p, 1 / unit(self.frame(target)['length_unit'])), refs

    def camera(self, name):
        if name not in self.cameras: fail('missing_calibration', 'Camera calibration is not provided')
        camera = self.cameras[name]
        if camera['model'] != 'pinhole': fail('unsupported_camera_model', 'Camera requires an explicit compatible processor')
        frame = self.frame(camera['frame_id'])
        if any(frame.get(k) != v for k,v in dict(handedness='right', x_axis='right', y_axis='down', forward_axis='+z').items()):
            fail('unsupported_camera_axes', 'Pinhole requires explicit optical +z frame')
        return camera

    def query(self, q):
        kind, refs, time = q['kind'], [], q.get('time')
        if kind == 'transform':
            point, refs = self.point(q['point'], q['source_frame'], q['target_frame'], time)
            value = dict(kind='point', point=point, frame_id=q['target_frame'], unit=self.frame(q['target_frame'])['length_unit'])
        elif kind == 'distance':
            frame = self.frame(q['frame_id']); unit(frame['length_unit'])
            value = dict(kind='distance', distance=norm(add(vector(q['point_a']),scale(vector(q['point_b']),-1))), frame_id=q['frame_id'], unit=frame['length_unit'])
        elif kind == 'clearance':
            value, refs = self.clearance(q)
        else:
            camera = self.camera(q['camera_id']); refs += camera['evidence_refs']
            frame_id = camera['frame_id']; length_unit = self.frame(frame_id)['length_unit']
            k = {name: float(v) for name,v in camera['intrinsics'].items()}
            if kind == 'project':
                p, more = self.point(q['point'], q['frame_id'], frame_id, time); refs += more
                if p[2] <= 0: fail('point_behind_camera' if p[2] < 0 else 'at_camera_plane', 'Point cannot be projected to a forward finite pixel')
                u,v = k['fx']*p[0]/p[2]+k['cx'], k['fy']*p[1]/p[2]+k['cy']
                value = dict(kind='pixel', pixel=[u,v], camera_id=camera['id'], unit='px',
                             validity='in_image' if 0<=u<camera['image_size'][0] and 0<=v<camera['image_size'][1] else 'out_of_image', occlusion='unknown')
            else:
                u,v = vector(q['pixel']); direction = [(u-k['cx'])/k['fx'], (v-k['cy'])/k['fy'], 1.]
                normalized = scale(direction, 1/norm(direction))
                if 'depth' in q:
                    d = q['depth']; refs += d['evidence_refs']
                    direction = direction if d['kind']=='optical_z' else normalized
                    point = scale(direction, float(d['value'])*unit(d['unit'])/unit(length_unit))
                    value = dict(kind='point',point=point,frame_id=frame_id,unit=length_unit)
                elif 'plane' in q:
                    plane = q['plane']; n = vector(plane['normal']); refs += plane['evidence_refs']
                    if abs(norm(n)-1)>1e-9: fail('invalid_geometry','Plane normal must be unit length')
                    r,t,more = self.path(frame_id,plane['frame_id'],time); refs+=more
                    d=mv(r,normalized); denominator=dot(n,d)
                    if abs(denominator)<=1e-12: fail('numerically_unstable','Ray is parallel or nearly parallel to plane')
                    amount=(float(plane['offset'])*unit(plane['unit'])-dot(n,t))/denominator
                    if amount<0: fail('no_forward_intersection','Plane intersection is behind the ray')
                    frame_id=plane['frame_id']; length_unit=self.frame(frame_id)['length_unit']
                    value=dict(kind='point',point=scale(add(t,scale(d,amount)),1/unit(length_unit)),frame_id=frame_id,unit=length_unit)
                else:
                    value=dict(kind='ray',origin=[0,0,0],direction=normalized,frame_id=frame_id,unit=length_unit)
        refs = list(dict.fromkeys(refs))
        # Bind the actual query coordinates as evidence, not only calibration.
        query_ref = 'query:' + q['id']
        if query_ref in self.inv.refs: fail('identity_mismatch','Reserved query evidence ID conflicts')
        self.inv.refs[query_ref] = dict(id=query_ref,media_type='application/json',inline=q)
        refs.append(query_ref)
        return dict(query_id=q['id'], status='ready', value=value, epistemic='derived', evidence_refs=refs,
                    method=dict(id='analytic_' + kind,version='1'))

    def clearance(self,q):
        try: a,b=[self.shapes[k] for k in q['geometry_ids']]
        except KeyError: fail('missing_geometry','Query geometry not provided')
        if a['kind'] not in ('point','sphere') or b['kind'] not in ('sphere','plane','aabb'):
            fail('unsupported_geometry_pair','Expected point/sphere against sphere/plane/aabb')
        if a['frame_id'] != q['frame_id'] or b['frame_id'] != q['frame_id']:
            fail('geometry_frame_mismatch','Normalize geometry into query frame explicitly')
        target_unit=self.frame(q['frame_id'])['length_unit']
        p=scale(vector(a.get('center',a.get('point'))),unit(a['unit']))
        radius=float(a.get('radius',0))*unit(a['unit'])
        if b['kind']=='sphere':
            distance=norm(add(p,scale(vector(b['center']),-unit(b['unit']))))-float(b['radius'])*unit(b['unit'])
        elif b['kind']=='plane':
            n=vector(b['normal'])
            if abs(norm(n)-1)>1e-9: fail('invalid_geometry','Plane normal must be unit length')
            distance=dot(n,p)-float(b['offset'])*unit(b['unit'])
        else:
            lo,hi=scale(vector(b['min']),unit(b['unit'])),scale(vector(b['max']),unit(b['unit']))
            if any(x>y for x,y in zip(lo,hi)): fail('invalid_geometry','AABB minimum exceeds maximum')
            center=scale(add(lo,hi),.5); half=scale(add(hi,scale(lo,-1)),.5)
            delta=[abs(v-c)-h for v,c,h in zip(p,center,half)]
            distance=norm([max(d,0) for d in delta])+min(max(delta),0)
        distance=(distance-radius)/unit(target_unit)
        return dict(kind='clearance',distance=distance,relation='inside' if distance<0 else 'outside' if distance>0 else 'on',geometry_ids=q['geometry_ids'],frame_id=q['frame_id'],unit=target_unit),a['evidence_refs']+b['evidence_refs']


def run(inv):
    geometry=Geometry(inv); unique(inv.input['queries'])
    processors=inv.input.get('processors',{})
    if set(processors)-{q['id'] for q in inv.input['queries']}:fail('invalid_request','Processor mapping contains an unknown query ID')
    results=[]
    for i,q in enumerate(inv.input['queries']):
        try:
            if q['id'] in processors:
                arguments={k:v for k,v in inv.input.items() if k not in ('queries','processors')}
                arguments['query']=q
                for camera in inv.input.get('cameras',[]):
                    if 'parameters_schema_reference_id' in camera:
                        from ..common import validator
                        schema=inv.read(camera['parameters_schema_reference_id'])
                        if not validator(schema).is_valid(camera['parameters']):fail('invalid_request','Provider camera parameters violate their declared schema')
                result=inv.call(processors[q['id']],arguments,list(inv.refs))
                if not isinstance(result,dict) or result.get('query_id')!=q['id']:fail('tool_output_invalid','Spatial processor must return the requested query outcome')
                if result.get('status')=='ready':
                    if not result.get('evidence_refs') or 'method' not in result:fail('tool_output_invalid','External geometry requires method and evidence')
                    expected_kind={'project':'pixel','unproject':'point' if 'depth' in q or 'plane' in q else 'ray','transform':'point','distance':'distance','clearance':'clearance'}[q['kind']]
                    if result.get('value',{}).get('kind')!=expected_kind:fail('tool_output_invalid','Spatial result kind differs from requested operation')
                    result['epistemic']='estimated'
                else:
                    inv.issues.extend(result.get('issues',[]))
                results.append(result)
            else:
                results.append(geometry.query(q))
        except (OverflowError,ZeroDivisionError):
            issue=dict(code='numerically_unstable',path=f'/input/queries/{i}',message='Calculation exceeds finite numeric range')
            results.append(dict(query_id=q['id'],status='unavailable',issues=[issue]));inv.issues.append(issue)
        except ContextError as exc:
            if exc.issue['code'] in ('identity_mismatch','dangling_reference'): raise
            issue={**exc.issue,'path':f'/input/queries/{i}'}
            results.append(dict(query_id=q['id'],status='unavailable',issues=[issue]));inv.issues.append(issue)
    count=sum(r['status']=='ready' for r in results)
    return inv.finish(dict(results=results),status='ready' if count==len(results) else 'partial' if count else 'unavailable')


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('spatial_context', request, **kwargs)
