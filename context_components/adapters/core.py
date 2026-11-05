"""Native exported-data adapters; never imports benchmark packages or contacts a backend."""
import copy
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

from ..common import COMPONENTS, at, equal, fail, loads, pointer, unique, validate
from ..task_modes import combine, declared_task


PROFILES=Path(__file__).parent/'profiles.json'


@dataclass(frozen=True)
class ExportPolicy:
    """Trusted host configuration. Request JSON cannot expand this publication allowlist."""
    public_paths: tuple
    catalog: dict | None = None

    def permits(self,path):
        return any(path==p or path.startswith(p+'/') for p in self.public_paths)


@lru_cache(maxsize=1)
def profiles():return loads(PROFILES.read_bytes())['benchmarks']


@lru_cache(maxsize=16)
def task_ids(benchmark):
    return frozenset(next(x for x in profiles() if x['adapter']==benchmark)['catalog']['task_ids'])


def adapt(benchmark,export,*,policy,components=None):
    profiles_by_name={x['adapter']:x for x in profiles()}
    if benchmark not in profiles_by_name:fail('unsupported_version','Unknown benchmark adapter')
    if not isinstance(policy,ExportPolicy):fail('invalid_request','Host must inject an ExportPolicy')
    allowed={'schema_version','scope','profile','native','references','supplements','request','history'}
    if set(export)-allowed or not {'schema_version','scope','profile','native'}<=export.keys():fail('invalid_request','Invalid export envelope')
    if export['schema_version']!='context.export.v1':fail('unsupported_version','Unsupported export envelope')
    validate(export['scope'],'scope')
    definition=profiles_by_name[benchmark];profile=export['profile']
    required={'benchmark_revision','export_schema_version','wrapper_revision','resolved_configuration_id','mode','task_id'}
    optional={'suite','variant_id','control_interface','task_kind','instruction_scope','segment_id','enabled_modalities','goal_visibility','source_kind','source_identity','overrides_identity','callback_revision','dataset_split','perturbations','instruction_revision','evaluation_track','evaluation_dimension','autoreset_mode','instance_id'}
    if not required<=profile.keys() or set(profile)-required-optional:fail('invalid_request','Profile identity fields missing or unknown')
    if profile['benchmark_revision']!=definition['benchmark_revision'] or profile['export_schema_version']!='published-native.v1':
        fail('unsupported_version','Benchmark or native export version is not frozen by this adapter')
    for key in ('wrapper_revision','resolved_configuration_id'):
        if not isinstance(profile[key],str) or not profile[key]:fail('invalid_request','Profile binding must be nonempty: '+key)
    if profile['mode'] not in definition['modes']:fail('unsupported_version','Unknown benchmark mode')
    catalog=policy.catalog or definition.get('catalog',{})
    entries=catalog.get('task_ids',[])
    member=any(equal(profile['task_id'],entry) for entry in entries) if policy.catalog else isinstance(profile['task_id'],str) and profile['task_id'] in task_ids(benchmark)
    if not entries or not member:
        fail('identity_mismatch','Task identity not in frozen catalog; supply the reviewed host catalog when required')
    if policy.catalog:
        if catalog.get('benchmark_revision')!=profile['benchmark_revision'] or not catalog.get('catalog_id') or catalog.get('complete') is not True:
            fail('identity_mismatch','External catalog needs matching revision, immutable identity and explicit completeness')
    task_modes=catalog.get('task_modes',{})
    if profile['task_id'] in task_modes and profile['mode'] not in ('pretrain_scene','target_scene') and task_modes[profile['task_id']]!=profile['mode']:
        fail('identity_mismatch','Task catalog family and selected mode disagree')
    if benchmark=='libero_plus':
        if not {'suite','variant_id'}<=profile.keys():fail('invalid_request','Plus requires suite and suite-local variant ID')
        if profile['task_id']!=str(profile['suite'])+':'+str(profile['variant_id']):fail('identity_mismatch','Plus variant must match suite-local catalog identity')
        if type(profile['variant_id']) is not int:fail('invalid_request','Plus variant ID must retain its native integer type')
    if benchmark=='libero':
        suite=profile['task_id'].split(':',1)[0]
        mode={'libero_spatial':'spatial','libero_object':'object','libero_goal':'goal'}.get(suite,suite)
        if mode!=profile['mode']:fail('identity_mismatch','LIBERO mode does not match task suite')
    if benchmark=='libero_pro':
        perturbations=profile.get('perturbations')
        if not isinstance(perturbations,dict) or set(perturbations)!={'use_environment','use_swap','use_object','use_language','use_task'} or any(type(v) is not bool for v in perturbations.values()):
            fail('invalid_request','Pro requires the five effective perturbation switches')
        switches={'object':'use_object','position':'use_swap','semantic':'use_language','task':'use_task','environment':'use_environment'}
        if profile['mode']=='combined_perturbations':
            if sum(perturbations.values())<2:fail('identity_mismatch','Combined Pro mode needs at least two active perturbations')
        elif not perturbations[switches[profile['mode']]]:fail('identity_mismatch','Pro mode does not match effective perturbations')
    if benchmark=='robomme':
        if profile.get('control_interface') not in ('joint_angle','ee_pose','waypoint','multi_choice'):fail('unsupported_version','RoboMME requires its action interface identity')
        if profile.get('dataset_split') not in ('train','val','test'):fail('invalid_request','RoboMME requires dataset split')
    if benchmark=='robotwin2' and profile.get('control_interface',profile['mode']) not in ('qpos','ee'):
        fail('unsupported_version','RoboTwin control representation must be qpos or ee')
    if benchmark=='robocasa365' and profile.get('control_interface') not in ('native_flat','gym_dict','lerobot_flat'):
        fail('invalid_request','RoboCasa native/Gym/LeRobot ordering must be explicit')
    if benchmark=='isaac_lab_arena':
        if profile.get('source_kind') not in ('registered_factory','graph_spec') or not profile.get('source_identity') or not profile.get('overrides_identity'):
            fail('invalid_request','Arena requires one source kind, source identity and resolved overrides identity')
        if not policy.catalog and profile['task_id'].startswith('yaml:')!=(profile['source_kind']=='graph_spec'):
            fail('identity_mismatch','Arena task identity and source kind differ')
    if benchmark=='robocerebra' and profile['task_id'].split('/')[0]!=profile['mode']:
        fail('identity_mismatch','RoboCerebra task directory and mode differ')
    if benchmark=='vlabench':
        if profile['mode']=='VLA_policy' and profile.get('evaluation_track') not in (
            'track_1_in_distribution','track_2_cross_categroy','track_3_common_sense','track_4_semantic_instruction','track_5_cross_task','track_6_unseen_texture'):
            fail('invalid_request','VLABench policy track must be explicit')
        if profile['mode']=='VLM_reasoning' and profile.get('evaluation_dimension') not in ('M&T','CommonSense','Semantic','Spatial','PhysicalLaw','PhysicsLaw','Complex'):
            fail('invalid_request','VLABench reasoning dimension must be explicit')
    if benchmark=='metaworld' and profile.get('goal_visibility') not in ('public','hidden'):
        fail('invalid_request','Meta-World goal visibility must be explicit')
    native=export['native'];refs=unique(export.get('references',[]))
    for ref in refs.values():validate(ref,'reference')
    selected=list(['task_context','observation_context'] if components is None else components)
    if len(set(selected))!=len(selected) or set(selected)-set(COMPONENTS):fail('invalid_request','Selected components are duplicated or unknown')
    def read(path,required=False):
        if not policy.permits(path):
            if any(p.startswith(path+'/') for p in policy.public_paths):
                try:value=at(native,path)
                except Exception:return None
                if isinstance(value,dict):
                    return {key:child for key in value if (child:=read(path+pointer([key]))) is not None}
                if isinstance(value,list):return [read(path+pointer([i])) for i in range(len(value))]
            if required:fail('forbidden_reference','Required field is not published: '+path)
            return None
        try:return copy.deepcopy(at(native,path))
        except Exception:
            if required:fail('invalid_request','Published native field is missing: '+path)
            return None
    def make_ref(path,value):
        rid='native:'+path
        ref=dict(id=rid,media_type='application/json',inline=value,scope=export['scope'],source_kind=benchmark)
        if rid in refs and not equal(refs[rid],ref):fail('identity_mismatch','Native reference conflicts')
        refs[rid]=ref;return rid
    observations=[];features=[]
    def media(path,modality,role='observation'):
        value=read(path)
        if value is None:return
        if not isinstance(value,dict) or not {'reference_id'}<=value.keys():fail('invalid_request','Media export must bind a declared resource at '+path)
        if set(value)-{'reference_id','id','captured_at','available_at','quality','role','frame_id','snapshot_id'}:fail('invalid_request','Unknown media descriptor metadata')
        if value['reference_id'] not in refs:fail('dangling_reference','Media reference is not declared')
        enabled=profile.get('enabled_modalities')
        if enabled is not None and modality not in enabled:fail('identity_mismatch','Received media conflicts with effective enabled modalities')
        observations.append(dict(id=value.get('id',path),modality=modality,role=value.get('role',role),**{k:v for k,v in value.items() if k!='id' and k!='role'}))
    def feature(path):
        value=read(path)
        if value is None:return
        rid=make_ref(path,value)
        features.append(dict(id=path,claim=dict(field=path,value=value),epistemic='observed',evidence_refs=[rid]))
    if 'observation_context' in selected:
        if benchmark in ('libero','libero_plus','libero_pro','robocerebra'):
            for name in ('agentview_image','robot0_eye_in_hand_image'):media('/observation/'+name,'image')
            for name in ('robot0_eef_pos','robot0_eef_quat','robot0_gripper_qpos'):feature('/observation/'+name)
        elif benchmark=='metaworld':
            value=read('/observation',True)
            if not isinstance(value,list) or len(value)!=39:fail('invalid_request','Frozen Meta-World v3 observation has 39 values')
            if profile['goal_visibility']=='hidden' and any(v!=0 for v in value[-3:]):fail('forbidden_reference','Hidden-goal profile contains unmasked goal coordinates')
            feature('/observation')
        elif benchmark=='robotwin2':
            cams=read('/observation') or {}
            if not isinstance(cams,dict):fail('invalid_request','RoboTwin camera observation must be a dictionary')
            for camera in cams:
                for field,modality in [('rgb','image'),('depth','depth'),('mesh_segmentation','mask'),('actor_segmentation','mask')]:media(pointer(['observation',camera,field]),modality)
            media('/pointcloud','point_cloud')
            # joint_action is a measured state, never an execution receipt.
            feature('/joint_action');feature('/endpose')
        elif benchmark=='robocasa365':
            obs=read('/observation') or {}
            if not isinstance(obs,dict):fail('invalid_request','RoboCasa observation must be a dictionary')
            for key in obs:
                if key.endswith('_image'):media(pointer(['observation',key]),'image')
                elif key.startswith('robot') and key.endswith(('_pos','_quat','_qpos','_qvel')):feature(pointer(['observation',key]))
        elif benchmark=='robomme':
            obs=read('/obs') or {}
            for key in ('front_rgb_list','wrist_rgb_list','front_depth_list','wrist_depth_list'):
                values=read('/obs/'+key)
                if values is None:continue
                if not isinstance(values,list):fail('invalid_request','RoboMME media values must remain lists')
                for index in range(len(values)):media(pointer(['obs',key,index]),'depth' if 'depth' in key else 'image')
            for key in ('eef_state_list','joint_state_list','gripper_state_list'):feature('/obs/'+key)
            feature('/info/available_multi_choices')
        elif benchmark=='vlabench':
            if profile['mode']=='VLM_reasoning':
                media('/input_image','image');media('/input_mask','mask')
                examples=read('/examples') or []
                for index,example in enumerate(examples):
                    if example.get('task_id')==profile['task_id'] or not example.get('source_identity'):
                        fail('forbidden_reference','Few-shot example must bind another published task')
                    feature(pointer(['examples',index]))
            else:
                for key in ('rgb','depth','point_cloud'):media('/observation/'+key,{'rgb':'image','depth':'depth','point_cloud':'point_cloud'}[key])
                feature('/observation/robot_state')
        elif benchmark=='robodojo':
            # Exporter publishes view names from the effective camera configuration.
            images=read('/observation/images') or {}
            for camera in images:media(pointer(['observation','images',camera]),'image')
            feature('/observation/joint_state');feature('/observation/eef_state')
        elif benchmark=='isaac_lab_arena':
            obs=read('/observation') or {}
            for camera in obs.get('images',{}):media(pointer(['observation','images',camera]),'image')
            feature('/observation/proprioception')
    supplements=export.get('supplements',{})
    if not isinstance(supplements,dict) or set(supplements)-set(COMPONENTS):fail('invalid_request','Unknown supplementary component input')
    task_kind=combine([profile.get('task_kind','reasoning' if benchmark=='vlabench' and profile['mode']=='VLM_reasoning' else 'execution')])
    payloads={}
    if 'task_context' in selected:
        instruction_path='/desc' if benchmark=='robocerebra' else '/instruction'
        text=read(instruction_path,True)
        if not isinstance(text,str) or not text:fail('invalid_request','Published instruction must be nonempty text')
        task=dict(text=text,kind=task_kind)
        for key in ('instruction_scope','segment_id'):
            if key in profile:task[key]=profile[key]
        payloads['task_context']=dict(task=task)
    if 'observation_context' in selected:payloads['observation_context']=dict(observations=observations,features=features)
    for component,extra in supplements.items():
        if component not in selected:continue
        if not policy.permits('/supplements/'+component):fail('forbidden_reference','Supplementary input was not published by host policy')
        if component in payloads:
            if set(extra)&payloads[component].keys():fail('identity_mismatch','Supplement cannot replace native mapped fields')
            payloads[component].update(copy.deepcopy(extra))
        else:payloads[component]=copy.deepcopy(extra)
    bindings=dict(benchmark=profile['benchmark_revision'],wrapper=profile['wrapper_revision'],configuration=profile['resolved_configuration_id'],task_revision=profile['task_id'])
    if 'instruction_revision' in profile:bindings['instruction_revision']=profile['instruction_revision']
    if profile.get('evaluation_dimension'):bindings['evaluation_dimension']=profile['evaluation_dimension']
    if profile.get('control_interface'):bindings['control']=profile['control_interface']+':'+profile['resolved_configuration_id']
    nodes=[];issues=[]
    for component in selected:
        if component not in payloads:
            if component in ('evidence_context','tool_context'):payloads[component]={}
            else:
                issues.append(dict(code='missing_component_input',path='/supplements/'+component,message='Requested component requires explicit published domain data'));continue
        combine([task_kind,declared_task(payloads[component].get('task'))])
        payloads[component].setdefault('task',{})['kind']=task_kind
        request=dict(schema_version='context.v1',scope=copy.deepcopy(export['scope']),input=payloads[component],bindings=bindings)
        if refs:request['references']=list(refs.values())
        if export.get('request'):request['request']=copy.deepcopy(export['request'])
        if component in export.get('history',{}):request['history']=copy.deepcopy(export['history'][component])
        validate(request,'input');validate(request['input'],component=component)
        nodes.append(dict(id=component,component=component,request=request))
    if not nodes:fail('invalid_request','No selected component has a valid input')
    return dict(schema_version='context.adaptation.v1',benchmark=benchmark,profile=copy.deepcopy(profile),
                catalog_id=catalog.get('catalog_id'),issues=issues,
                compose=dict(schema_version='context.compose.v1',scope=copy.deepcopy(export['scope']),task=dict(kind=task_kind),nodes=nodes))


def decode_depth_sample(value,profile):
    """Convert a decoded scalar; media bytes stay outside JSON and are never expanded here."""
    import math
    if profile=='ros_openni_uint16':
        if isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=65535:fail('invalid_request','Expected uint16 sample')
        return dict(status='invalid') if value==0 else dict(status='valid',value=value/1000,unit='m',kind='optical_z')
    if profile=='ros_rep118_32fc1':
        if isinstance(value,bool) or not isinstance(value,(int,float)):fail('invalid_request','Expected decoded floating sample')
        if math.isnan(value):return dict(status='invalid')
        if math.isinf(value):return dict(status='above_max_range' if value>0 else 'below_min_range')
        return dict(status='valid',value=value,unit='m',kind='optical_z') if value>0 else dict(status='invalid')
    if profile=='robomme_hdf5_int16_mm':
        if isinstance(value,bool) or not isinstance(value,int) or not -32768<=value<=32767:fail('invalid_request','Expected int16 sample')
        if value<=0:return dict(status='unknown',reason='No positive finite depth; source validity rule required')
        return dict(status='valid',value=value/1000,unit='m',kind='optical_z')
    fail('unsupported_version','Unknown depth encoding profile')
