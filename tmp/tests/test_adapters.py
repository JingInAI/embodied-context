import copy
import importlib
import json
from pathlib import Path
import unittest

from context_components import compose,ContextError
from context_components.adapters.core import adapt,profiles,ExportPolicy
from context_components.common import dumps,validate
from context_components.render import render_context

ROOT=Path(__file__).resolve().parents[1]
SCOPE=dict(run_id='synthetic-adapter',task_id='published-task',epoch_id='one',turn_index=0)


def make_export(definition,mode=None,task_id=None):
    name=definition['adapter'];mode=mode or definition['modes'][0];ids=definition['catalog']['task_ids']
    explicit_task=task_id is not None
    task_id=task_id or ids[0]
    if not explicit_task and definition['catalog'].get('task_modes') and mode not in ('pretrain_scene','target_scene'):
        task_id=next(t for t,m in definition['catalog']['task_modes'].items() if m==mode)
    if name=='isaac_lab_arena' and not explicit_task:
        task_id={'fixed_arm':'factory:cube_goal_pose','humanoid':'factory:galileo_pick_and_place','mobile_manipulation':'factory:galileo_g1_locomanip_pick_and_place','sequential_task':'yaml:robolab/tasks/banana_then_rubiks_cube.yaml'}[mode]
    if name=='libero':
        suite={'spatial':'libero_spatial','object':'libero_object','goal':'libero_goal'}.get(mode,mode)
        task_id=next((x for x in ids if x.startswith(suite+':')),task_id)
    if name=='robocerebra':task_id=next(x for x in ids if x.startswith(mode+'/'))
    p=dict(benchmark_revision=definition['benchmark_revision'],export_schema_version='published-native.v1',wrapper_revision='synthetic-exporter-v1',resolved_configuration_id='synthetic-config-v1',mode=mode,task_id=task_id)
    native=dict(instruction='Use the published observation to answer the current task.',observation={})
    refs=[dict(id='frame',media_type='image/png',uri='fixture://published/frame.png',source_kind='synthetic')]
    if name in ('libero','libero_plus','libero_pro','robocerebra'):
        native['observation']=dict(agentview_image=dict(reference_id='frame'),robot0_eef_pos=[0,0,1])
    if name=='libero_plus':
        suite,variant=task_id.split(':');p.update(suite=suite,variant_id=int(variant))
    if name=='libero_pro':
        p['perturbations']=dict(use_environment=False,use_swap=False,use_object=False,use_language=False,use_task=False)
        if mode=='combined_perturbations':p['perturbations'].update(use_swap=True,use_language=True)
        else:p['perturbations'][{'object':'use_object','position':'use_swap','semantic':'use_language','task':'use_task','environment':'use_environment'}[mode]]=True
    if name=='metaworld':native['observation']=[0]*39;p['goal_visibility']='hidden'
    if name=='robotwin2':native=dict(instruction=native['instruction'],observation={'head_camera':{'rgb':{'reference_id':'frame'}}},joint_action={'left_arm':[0,0],'right_arm':[0,0,0]});p['control_interface']=mode
    if name=='robocasa365':p['control_interface']='gym_dict';native['observation']={'robot0_agentview_image':{'reference_id':'frame'},'robot0_eef_pos':[0,0,1]}
    if name=='robodojo':native['observation']=dict(images={'front':{'reference_id':'frame'}},joint_state=[0,0,0])
    if name=='robocerebra':native['desc']=native.pop('instruction');p.update(instruction_scope='current_segment',segment_id='s1',instruction_revision='i1')
    if name=='robomme':p.update(control_interface='joint_angle',dataset_split='test');native.update(obs={'front_rgb_list':[{'reference_id':'frame','id':'t0'},{'reference_id':'frame','id':'t1'}],'joint_state_list':[[0,0],[1,0]]},info={'available_multi_choices':[{'label':'A','action':'published','need_parameter':False}]})
    if name=='isaac_lab_arena':p.update(source_kind='graph_spec' if task_id.startswith('yaml:') else 'registered_factory',source_identity=task_id,overrides_identity='none');native['observation']=dict(images={'front':{'reference_id':'frame'}},proprioception={'arm':[0,1]})
    if name=='vlabench':
        if mode=='VLM_reasoning':native.update(input_image={'reference_id':'frame'},input_mask={'reference_id':'frame'});p['evaluation_dimension']='Spatial'
        else:native['observation']={'rgb':{'reference_id':'frame'}};p['evaluation_track']='track_1_in_distribution'
    # Deliberately included private data must never appear in mapped contexts.
    native['private_evaluator']={'answer':'SECRET_EVALUATOR_ANSWER','score':1,'future_instruction':'PRIVATE_FUTURE'}
    policy=ExportPolicy(tuple('/'+key for key in native if key!='private_evaluator'))
    return dict(schema_version='context.export.v1',scope=copy.deepcopy(SCOPE),profile=p,native=native,references=refs),policy


class AdaptersTest(unittest.TestCase):
    def assertError(self,code,fn):
        with self.assertRaises(ContextError) as ctx:fn()
        self.assertEqual(ctx.exception.issue['code'],code)

    def test_all_eleven_modes_transform_and_render(self):
        self.assertEqual(len(profiles()),11)
        for definition in profiles():
            for mode in definition['modes']:
                with self.subTest(adapter=definition['adapter'],mode=mode):
                    export,policy=make_export(definition,mode)
                    before=copy.deepcopy(export)
                    adapter=importlib.import_module('context_components.adapters.'+definition['adapter'])
                    mapped=adapter.adapt(export,policy=policy)
                    self.assertEqual(export,before)
                    self.assertFalse(mapped['issues'])
                    output=compose(mapped['compose'])
                    validate(output,'composed_output')
                    for modalities in [['text'],['text','image','video']]:
                        packet=render_context(output,dict(receiver_id='agent',session_id='s',audience={'modalities':modalities}))
                        validate(packet,'delivery');encoded=dumps(packet)
                        self.assertNotIn('SECRET_EVALUATOR_ANSWER',encoded);self.assertNotIn('PRIVATE_FUTURE',encoded)
                    # Optional observations are absent, not fabricated; task context still works.
                    minimal=copy.deepcopy(export)
                    minimal['native']={k:v for k,v in minimal['native'].items() if k in ('instruction','desc')}
                    task=adapt(definition['adapter'],minimal,policy=policy,components=['task_context'])
                    self.assertEqual(len(task['compose']['nodes']),1)

    def test_every_catalog_identity_is_mapped(self):
        totals={}
        for definition in profiles():
            name=definition['adapter'];total=0
            for tid in definition['catalog']['task_ids']:
                mode=definition['modes'][0]
                if name=='libero':
                    suite=tid.split(':',1)[0];mode={'libero_spatial':'spatial','libero_object':'object','libero_goal':'goal'}.get(suite,suite)
                if name=='robocerebra':mode=tid.split('/')[0]
                if definition['catalog'].get('task_modes'):mode=definition['catalog']['task_modes'][tid]
                export,policy=make_export(definition,mode,tid)
                export['profile']['task_id']=tid
                if name=='isaac_lab_arena':export['profile']['source_kind']='graph_spec' if tid.startswith('yaml:') else 'registered_factory'
                mapped=adapt(name,export,policy=policy,components=['task_context'])
                self.assertEqual(mapped['profile']['task_id'],tid);total+=1
            totals[name]=total
        self.assertEqual(totals, json.loads((ROOT/'catalog-evidence.json').read_text())['counts'])

    def test_all_adapters_reject_version_mode_task_and_publication_conflicts(self):
        for definition in profiles():
            name=definition['adapter'];export,policy=make_export(definition)
            for key,value,code in [('benchmark_revision','unknown','unsupported_version'),('mode','unknown','unsupported_version'),('task_id','unknown','identity_mismatch')]:
                with self.subTest(adapter=name,field=key):
                    bad=copy.deepcopy(export);bad['profile'][key]=value
                    self.assertError(code,lambda:adapt(name,bad,policy=policy))
            self.assertError('forbidden_reference',lambda:adapt(name,export,policy=ExportPolicy(()),components=['task_context']))
            requested=adapt(name,export,policy=policy,components=['task_context','spatial_context'])
            self.assertEqual(requested['issues'][0]['code'],'missing_component_input')

    def test_metaworld_hidden_goal_and_robotwin_disabled_modality(self):
        definition=next(x for x in profiles() if x['adapter']=='metaworld');export,policy=make_export(definition)
        export['native']['observation'][-1]=5
        self.assertError('forbidden_reference',lambda:adapt('metaworld',export,policy=policy))
        definition=next(x for x in profiles() if x['adapter']=='robotwin2');export,policy=make_export(definition)
        export['native']['observation']['head_camera']['depth']={'reference_id':'frame'};export['profile']['enabled_modalities']=['image']
        self.assertError('identity_mismatch',lambda:adapt('robotwin2',export,policy=policy))

    def test_robomme_list_roles_and_all_interfaces(self):
        definition=next(x for x in profiles() if x['adapter']=='robomme')
        for interface in ['joint_angle','ee_pose','waypoint','multi_choice']:
            export,policy=make_export(definition);export['profile']['control_interface']=interface
            export['native']['obs']['front_rgb_list'][0]['role']='demonstration'
            mapped=adapt('robomme',export,policy=policy)
            obs=next(n for n in mapped['compose']['nodes'] if n['component']=='observation_context')['request']['input']['observations']
            self.assertEqual(len(obs),2);self.assertEqual(obs[0]['role'],'demonstration')

    def test_vlabench_all_tracks_dimensions_and_example_boundary(self):
        definition=next(x for x in profiles() if x['adapter']=='vlabench')
        for track in ['track_1_in_distribution','track_2_cross_categroy','track_3_common_sense','track_4_semantic_instruction','track_5_cross_task','track_6_unseen_texture']:
            export,policy=make_export(definition);export['profile']['evaluation_track']=track
            self.assertFalse(adapt('vlabench',export,policy=policy)['issues'])
        for dimension in ['M&T','CommonSense','Semantic','Spatial','PhysicalLaw','PhysicsLaw','Complex']:
            export,policy=make_export(definition,'VLM_reasoning');export['profile']['evaluation_dimension']=dimension
            self.assertFalse(adapt('vlabench',export,policy=policy)['issues'])
        export['native']['examples']=[dict(task_id=export['profile']['task_id'],source_identity='sample')]
        policy=ExportPolicy(policy.public_paths+('/examples',))
        self.assertError('forbidden_reference',lambda:adapt('vlabench',export,policy=policy))

    def test_casa_interface_identity_and_cerebra_segments(self):
        definition=next(x for x in profiles() if x['adapter']=='robocasa365')
        for interface in ['native_flat','gym_dict','lerobot_flat']:
            export,policy=make_export(definition);export['profile']['control_interface']=interface
            self.assertFalse(adapt('robocasa365',export,policy=policy)['issues'])
        definition=next(x for x in profiles() if x['adapter']=='robocerebra');export,policy=make_export(definition)
        export['native']['complete_task_file']='PRIVATE_FUTURE';mapped=adapt('robocerebra',export,policy=policy)
        self.assertNotIn('PRIVATE_FUTURE',dumps(mapped['compose']))
        self.assertEqual(mapped['compose']['nodes'][0]['request']['input']['task']['instruction_scope'],'current_segment')


if __name__=='__main__':unittest.main()
