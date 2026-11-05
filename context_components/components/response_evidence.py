"""Local evidence statistics on explicit executed records; never searches actions."""
import math

from ..common import equal, elapsed, fail, same_scope, unique
from ..memory import merge,restore,state


def solve(matrix, rhs):
    n=len(rhs);a=[list(row)+[rhs[i]] for i,row in enumerate(matrix)]
    largest=max((abs(v) for row in matrix for v in row),default=0)
    for col in range(n):
        pivot=max(range(col,n),key=lambda i:abs(a[i][col]))
        if abs(a[pivot][col])<=1e-12*max(largest,1):fail('insufficient_joint_support','Design matrix is singular or poorly conditioned')
        a[col],a[pivot]=a[pivot],a[col];div=a[col][col];a[col]=[v/div for v in a[col]]
        for i in range(n):
            if i!=col:
                factor=a[i][col];a[i]=[v-factor*w for v,w in zip(a[i],a[col])]
    return [row[-1] for row in a]


def contains_origin(points):
    """Conservative convex-hull certificate via closest convex combination.

    Failure to converge is insufficient support, never permission to extrapolate.
    Coordinates are already scaled by explicit query distance scales.
    """
    current=[sum(p[i] for p in points)/len(points) for i in range(len(points[0]))]
    for _ in range(4096):
        if sum(x*x for x in current)<=1e-18:return True
        vertex=min(points,key=lambda p:sum(x*y for x,y in zip(current,p)))
        direction=[v-c for v,c in zip(vertex,current)]
        denominator=sum(x*x for x in direction)
        if denominator==0:return False
        step=max(0,min(1,-sum(c*d for c,d in zip(current,direction))/denominator))
        if step<=1e-15:return False
        current=[c+step*d for c,d in zip(current,direction)]
    return False


def run(inv):
    inp=inv.input;variables=unique(inp['variables']);q=inp['query']
    if q.get('kind') not in ('support','estimate','compare_candidates'):fail('unsupported_operator','Unknown response query')
    old=restore(inv)
    incoming=[dict(id=r['id'],source_namespace=r.get('source_namespace','published-response'),revision=r.get('revision',0),
                   record=r,evidence_refs=r.get('evidence_refs',[]),**{k:r[k] for k in ('scope','origin_epoch','retracted') if k in r}) for r in inp['records']]
    memory,complete=merge(inv,old.get('records',[]),incoming,old.get('complete_set',True))
    update=state(inv,memory,complete_set=complete) if memory or old else None
    rows=[];excluded=[]
    for stored in memory:
        r=stored['record']
        if not {'id','inputs','responses','conditions','scope','bindings','evidence_refs','executed'}<=r.keys():
            fail('invalid_request','Response record lacks bound executed input/response data')
        if not r['executed'] or r.get('retracted'):
            excluded.append(dict(id=r['id'],reason='not_valid_execution'));continue
        if not same_scope(r['scope'],inv.scope) or not equal(r['conditions'],inp['conditions']) or not equal(r['bindings'],inv.request.get('bindings',{})):
            excluded.append(dict(id=r['id'],reason='conditions_or_identity_mismatch'));continue
        if any(rid not in inv.refs for rid in r['evidence_refs']):fail('dangling_reference','Response evidence is undeclared')
        rows.append(r)
    unique(rows)
    content=dict(support=dict(valid_samples=len(rows),excluded=excluded),estimates=[],limitations=[])
    if q['kind']=='support':return inv.finish(content,state=update)
    input_ids=[v['id'] for v in inp['variables'] if v.get('role')=='input']
    response_ids=[v['id'] for v in inp['variables'] if v.get('role')=='response']
    if not input_ids or not response_ids:fail('invalid_request','Estimation variables need input/response roles')
    if not {'radius','distance_scale'}<=q.keys():fail('invalid_request','Local estimation requires explicit radius and per-variable distance scales')
    radius=float(q['radius'])
    if radius<=0 or not math.isfinite(radius):fail('invalid_request','Radius must be positive finite')
    scales=q['distance_scale']
    if set(scales)!=set(input_ids) or any(float(v)<=0 for v in scales.values()):fail('invalid_request','Positive scale required for every input dimension')
    targets=q.get('candidates',[]) if q['kind']=='compare_candidates' else [dict(id='query',inputs=q.get('inputs',{}))]
    unique(targets)
    estimates=[]
    for target in targets:
        if set(target['inputs'])!=set(input_ids):fail('invalid_request','Query inputs must match declared variables')
        selected=[]
        for r in rows:
            if set(r['inputs'])!=set(input_ids) or set(r['responses'])!=set(response_ids):continue
            distance=math.sqrt(sum(((float(r['inputs'][k])-float(target['inputs'][k]))/float(scales[k]))**2 for k in input_ids))
            if distance>radius:continue
            weight=1.
            if 'max_age_seconds' in q:
                if 'now' not in q or 'time' not in r:continue
                age=float(elapsed(r['time'],q['now']))
                if age<0 or age>float(q['max_age_seconds']):continue
            if 'half_life_seconds' in q:
                if float(q['half_life_seconds'])<=0 or 'now' not in q or 'time' not in r:fail('invalid_request','Time decay requires positive half-life and comparable times')
                age=float(elapsed(r['time'],q['now']))
                if age<0:continue
                weight=2**(-age/float(q['half_life_seconds']))
            selected.append((r,weight))
        if len(selected)<len(input_ids)+2:
            content['limitations'].append(target['id']+': insufficient local samples');continue
        design=[[1.]+[(float(r['inputs'][k])-float(target['inputs'][k]))/float(scales[k]) for k in input_ids] for r,w in selected]
        weights=[w for r,w in selected];n=len(input_ids)+1
        effective=sum(weights)**2/sum(w*w for w in weights) if any(weights) else 0
        if effective<n+1 or not contains_origin([row[1:] for row in design]):
            content['limitations'].append(target['id']+': insufficient effective sample size or convex joint support');continue
        gram=[[sum(w*x[i]*x[j] for x,w in zip(design,weights)) for j in range(n)] for i in range(n)]
        try:
            for key in response_ids:
                ys=[float(r['responses'][key]) for r,w in selected]
                rhs=[sum(w*x[i]*y for x,w,y in zip(design,weights,ys)) for i in range(n)]
                beta=solve(gram,rhs)
                residual=sum(w*(y-sum(a*b for a,b in zip(x,beta)))**2 for x,w,y in zip(design,weights,ys))/sum(weights)
                if key in q.get('max_residual_rms',{}) and math.sqrt(residual)>float(q['max_residual_rms'][key]):
                    content['limitations'].append(target['id']+': response dispersion exceeds supplied limit for '+key);continue
                estimates.append(dict(candidate_id=target['id'],variable=key,value=beta[0],unit=variables[key]['unit'],
                    sample_count=len(selected),effective_sample_size=effective,weighted_residual_rms=math.sqrt(residual),
                    evidence_refs=list(dict.fromkeys(rid for r,w in selected for rid in r['evidence_refs'])),
                    method=dict(id='local_weighted_linear',version='1'),assumptions=['Local empirical association, not a causal or extrapolation guarantee']))
        except Exception as exc:
            content['limitations'].append(target['id']+': '+str(exc))
    content['estimates']=estimates
    if content['limitations']:
        inv.issue('insufficient_joint_support','One or more local estimates unavailable')
    if q['kind']=='compare_candidates':content['candidate_comparison']=[dict(candidate_id=t['id'],estimates=[e for e in estimates if e['candidate_id']==t['id']]) for t in targets]
    return inv.finish(content,status='partial' if estimates and inv.issues else 'unavailable' if inv.issues else 'ready',state=update)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('response_evidence', request, **kwargs)
