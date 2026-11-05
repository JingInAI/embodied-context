"""Task type propagation, explicit JSON variants, and cross-turn isolation."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import unittest

from context_components import build_context, compose, ContextError, InformationTool, Resolved, Services
from context_components.common import cas, dumps, loads, validate
from context_components.render import render_context
from context_components.task_modes import KINDS
from test_render_presentation import examples, request, reference, OPTS, ROOT, SCOPE, CLOCK


def mode_request(payload, kind):
    req=request(copy.deepcopy(payload))
    req['input'].setdefault('task', {})['kind']=kind
    return req


def tool_spec(tid):
    return dict(id=tid,purpose='Process published data',input_schema={'type':'object'},
                output_schema={'type':'object'},effects=['process_data'],limits={})


def variant_case(component):
    base=examples()[component]
    req=request(copy.deepcopy(base),request={'task_variants':{}})
    if component=='evidence_context':
        req['references']=[reference(k, {'value':k}) for k in KINDS]
    if component=='tool_context':
        req['tools']=[tool_spec(k) for k in KINDS]
    if component=='response_evidence':
        req['references']=[reference()]
    for index,kind in enumerate(KINDS,1):
        patch={}
        if component=='task_context':patch={'goals':[dict(id=kind,description='Caller-defined '+kind+' goal')]}
        elif component=='observation_context':patch={'features':[dict(id=kind,claim=kind,epistemic='hypothesis',evidence_refs=[])]}
        elif component=='spatial_context':patch={'queries':[dict(id=kind,kind='transform',source_frame='map',target_frame='map',point=[index,2,3])]}
        elif component=='interaction_contract':patch={'operations':[dict(id=kind,kind='query' if kind=='reasoning' else 'custom_control',description='Declared operation',parameters={})]}
        elif component=='execution_feedback':patch={'executions':[dict(id=kind,status='complete',executed=dict(items=index))]}
        elif component=='response_evidence':
            patch={'records':[dict(id=str(i),inputs={'input':i},responses={},conditions={},scope=SCOPE,
                                    bindings={},executed=True,evidence_refs=['source']) for i in range(index)]}
        elif component=='resource_context':patch={'resources':[dict(id='time',unit='s',remaining=index,as_of=CLOCK)]}
        elif component=='evidence_context':patch={'queries':[dict(reference_id=kind,kind='readability')]}
        elif component=='output_contract':
            patch={'delivery':{'kind':'json'},'contract':{'schema':{'const':kind}},'candidate':kind}
        variant={'focus':[kind]} if component=='tool_context' else {'input':patch}
        req['request']['task_variants'][kind]=variant
    return req


class TaskModeTests(unittest.TestCase):
    def assertError(self,code,fn):
        with self.assertRaises(ContextError) as caught:fn()
        self.assertEqual(caught.exception.issue['code'],code)

    def test_all_ten_components_select_real_json_and_english_for_three_kinds(self):
        for component in examples():
            contents=[]
            for kind in KINDS:
                with self.subTest(component=component,kind=kind):
                    req=variant_case(component)
                    req['input'].setdefault('task',{})['kind']=kind
                    frozen=dumps(req)
                    result=build_context(component,req)
                    self.assertEqual(dumps(req),frozen)
                    self.assertEqual(result['task'],{'kind':kind})
                    self.assertEqual(result['guidance'][0]['id'],'task_kind_usage')
                    self.assertTrue(result['guidance'][0]['text'].isascii())
                    contents.append(dumps(result['content']))
                    canonical=dumps(result)
                    for style in ('json','text_json','text'):
                        packet=render_context(result,dict(OPTS,content_format=style))
                        validate(packet,'delivery')
                        text=packet['blocks'][0]['text']
                        if style=='json':self.assertEqual(loads(text)['task']['kind'],kind)
                        else:self.assertIn('Task kind: '+kind,text)
                        if style=='text_json':
                            self.assertEqual(loads(text.split('Context data (JSON):\n')[1])['content'],result['content'])
                        self.assertEqual(dumps(result),canonical)
            self.assertEqual(len(set(contents)),3,component)

    def test_kind_only_preserves_domain_data_and_legacy_generic_mode(self):
        payload=examples()['execution_feedback']
        generic=build_context('execution_feedback',request(payload))
        self.assertNotIn('task',generic)
        self.assertNotIn('guidance',generic)
        for kind in KINDS:
            typed=build_context('execution_feedback',mode_request(payload,kind))
            self.assertEqual(typed['content'],generic['content'])
            self.assertEqual(typed['state_update']['state']['value'],generic['state_update']['state']['value'])
        reasoning=build_context('execution_feedback',mode_request(payload,'reasoning'))
        prose=render_context(reasoning,OPTS)['blocks'][0]['text']
        self.assertIn('Analyze reported failures',prose)
        self.assertNotIn('before retrying',prose)
        self.assertEqual(reasoning['content']['segments'][0]['executed_items'],30)

    def test_variants_replace_fields_without_merging_hybrid_or_nested_objects(self):
        req=mode_request(dict(delivery={'kind':'json'},contract={'schema':{'type':'object'}},candidate={}), 'hybrid')
        req['request']={'task_variants':{
            'execution':{'input':{'contract':{'schema':{'type':'integer'}},'candidate':1}},
            'reasoning':{'input':{'contract':{'schema':{'type':'string'}},'candidate':'answer'}},
        }}
        unchanged=build_context('output_contract',req)
        self.assertEqual(unchanged['content']['requirements'][1]['schema'],{'type':'object'})
        req['input']['task']['kind']='reasoning'
        changed=build_context('output_contract',req)
        self.assertEqual(changed['content']['requirements'][1]['schema'],{'type':'string'})
        self.assertEqual(changed['content']['checks'][0]['status'],'passed')

    def test_missing_invalid_and_conflicting_kind_rejected(self):
        req=request(dict(resources=[]),request={'task_variants':{'reasoning':{'input':{'resources':[]}}}})
        self.assertError('invalid_request',lambda:build_context('resource_context',req))
        for kind in ('auto','',None,True,{}):
            self.assertError('invalid_request',lambda:build_context('resource_context',mode_request({'resources':[]},kind)))
        req=mode_request(dict(resources=[]),'reasoning')
        req['request']={'task_variants':{'execution':{'input':{'task':{'kind':'execution'}}}}}
        self.assertError('invalid_request',lambda:build_context('resource_context',req))
        req['request']={'task_variants':{'execution':{'input':{'unexpected':True}}}}
        self.assertError('invalid_request',lambda:build_context('resource_context',req))

    def test_compose_inherits_type_even_when_task_node_is_after_observation(self):
        plan=dict(schema_version='context.compose.v1',scope=SCOPE,nodes=[
            dict(id='observation',component='observation_context',request=request({'features':[]})),
            dict(id='task',component='task_context',request=mode_request({'task':{'text':'Explain the event.'}},'reasoning'),upstream_nodes=['observation']),
            dict(id='tools',component='tool_context',request=request({})),
        ])
        frozen=dumps(plan);result=compose(plan)
        self.assertEqual(dumps(plan),frozen)
        self.assertEqual(result['task']['kind'],'reasoning')
        self.assertTrue(all(n['result']['task']['kind']=='reasoning' for n in result['nodes']))
        plan['task']={'kind':'execution'}
        self.assertError('task_kind_mismatch',lambda:compose(plan))

    def test_explicit_compose_type_supplies_missing_task_kind(self):
        plan=dict(schema_version='context.compose.v1',scope=SCOPE,task={'kind':'hybrid'},nodes=[
            dict(id='task',component='task_context',request=request({'task':{'text':'Act and explain.'}})),
            dict(id='budget',component='resource_context',request=request({'resources':[]})),
        ])
        result=compose(plan)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['nodes'][0]['result']['content']['requirements'][0]['kind'],'hybrid')

    def test_upstream_inline_referenced_and_legacy_task_types_are_inherited(self):
        source=build_context('task_context',mode_request({'task':{'text':'Explain.'}},'reasoning'))
        legacy=copy.deepcopy(source);legacy.pop('task');legacy.pop('guidance')
        req=request({'resources':[]},upstream=[dict(context=legacy)])
        self.assertEqual(build_context('resource_context',req)['task']['kind'],'reasoning')
        req=request({'resources':[]},references=[dict(id='up',media_type='application/json',uri='published:up')],
                    upstream=[dict(reference_id='up',context_id=source['context_id'],component='task_context')])
        resolver=lambda _:Resolved(dumps(source).encode(),'v1')
        self.assertEqual(build_context('resource_context',req,resolver=resolver)['task']['kind'],'reasoning')
        req['input']['task']={'kind':'execution'}
        self.assertError('task_kind_mismatch',lambda:build_context('resource_context',req,resolver=resolver))

    def test_typed_history_preserves_type_and_rejects_silent_mode_switch(self):
        payload=dict(executions=[dict(id='record',status='complete',executed={'items':3})])
        first=build_context('execution_feedback',mode_request(payload,'execution'))
        state=cas(None,first['state_update'])
        req=request({'executions':[]},history=state);req['scope']['turn_index']=1
        second=build_context('execution_feedback',req)
        self.assertEqual(second['task']['kind'],'execution')
        self.assertEqual(second['content']['segments'][0]['executed_items'],3)
        req['input']['task']={'kind':'reasoning'}
        self.assertError('task_kind_mismatch',lambda:build_context('execution_feedback',req))
        old=copy.deepcopy(state);old.pop('task')
        req['history']=old
        self.assertEqual(build_context('execution_feedback',req)['task']['kind'],'reasoning')

    def test_compose_conflicts_and_bad_inactive_variant_precede_tool_execution(self):
        calls=[]
        provider=InformationTool(lambda *args:calls.append(args) or {'features':[],'events':[]},{'process_data'})
        obs=request(dict(observations=[dict(id='frame',modality='image',reference_id='image')],extractors=['extract']),
                    references=[dict(id='image',media_type='image/png',inline='synthetic')],tools=[tool_spec('extract')])
        plan=dict(schema_version='context.compose.v1',scope=SCOPE,task={'kind':'execution'},nodes=[
            dict(id='obs',component='observation_context',request=obs),
            dict(id='later',component='resource_context',request=mode_request({'resources':[]},'reasoning'))])
        services=Services(tools={'extract':provider})
        self.assertError('task_kind_mismatch',lambda:compose(plan,services=services))
        self.assertEqual(calls,[])
        plan['nodes'][1]['request']['input']['task']['kind']='execution'
        plan['nodes'][1]['request']['request']={'task_variants':{'reasoning':{'input':{'resources':'invalid'}}}}
        self.assertError('invalid_request',lambda:compose(plan,services=services))
        self.assertEqual(calls,[])
        # A referenced declaration is also checked before the earlier tool node.
        upstream=build_context('resource_context',mode_request({'resources':[]},'reasoning'))
        plan['nodes'][1]['request']=request({'resources':[]},references=[dict(id='up',media_type='application/json',uri='up')],
             upstream=[dict(reference_id='up',context_id=upstream['context_id'],component='resource_context')])
        services.resolver=lambda _:Resolved(dumps(upstream).encode(),'v1')
        self.assertError('task_kind_mismatch',lambda:compose(plan,services=services))
        self.assertEqual(calls,[])

    def test_referenced_type_propagates_to_independent_nodes_and_resolves_once(self):
        upstream=build_context('resource_context',mode_request({'resources':[]},'reasoning'))
        reads=[]
        def resolver(ref):
            reads.append(ref['id']);return Resolved(dumps(upstream).encode(),'v1')
        plan=dict(schema_version='context.compose.v1',scope=SCOPE,nodes=[
            dict(id='first',component='tool_context',request=request({})),
            dict(id='second',component='resource_context',request=request({'resources':[]},
                 references=[dict(id='up',media_type='application/json',uri='up')],
                 upstream=[dict(reference_id='up',context_id=upstream['context_id'],component='resource_context')]))])
        result=compose(plan,services=Services(resolver=resolver))
        self.assertEqual(reads,['up'])
        self.assertTrue(all(n['result']['task']['kind']=='reasoning' for n in result['nodes']))

    def test_unreadable_external_upstream_does_not_break_independent_nodes(self):
        plan=dict(schema_version='context.compose.v1',scope=SCOPE,task={'kind':'reasoning'},nodes=[
            dict(id='good',component='resource_context',request=request({'resources':[]})),
            dict(id='bad',component='tool_context',request=request({},references=[dict(id='up',media_type='application/json',uri='up')],
                 upstream=[dict(reference_id='up',context_id='missing',component='resource_context')]))])
        result=compose(plan)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['nodes'][0]['result']['task']['kind'],'reasoning')
        self.assertEqual(result['nodes'][1]['error']['issues'][0]['code'],'reference_unavailable')

    def test_invalid_scope_or_history_cannot_assign_type_to_other_nodes(self):
        foreign=build_context('resource_context',mode_request({'resources':[]},'reasoning'))
        foreign['scope']['task_id']='another-task'
        plan=dict(schema_version='context.compose.v1',scope=SCOPE,nodes=[
            dict(id='generic',component='resource_context',request=request({'resources':[]})),
            dict(id='bad',component='tool_context',request=request({},upstream=[dict(context=foreign)]))])
        result=compose(plan)
        self.assertEqual(result['status'],'partial')
        self.assertNotIn('task',result)
        self.assertNotIn('task',result['nodes'][0]['result'])
        self.assertEqual(result['nodes'][1]['error']['issues'][0]['code'],'identity_mismatch')
        recorded=build_context('execution_feedback',mode_request({'executions':[
            dict(id='work',status='complete',executed={'items':1})]},'reasoning'))
        state=cas(None,recorded['state_update']);state['scope']['task_id']='another-task'
        plan['nodes'][1]=dict(id='bad',component='execution_feedback',request=request({'executions':[]},history=state))
        result=compose(plan)
        self.assertNotIn('task',result['nodes'][0]['result'])
        self.assertEqual(result['nodes'][1]['error']['issues'][0]['code'],'identity_mismatch')

    def test_variant_selected_references_must_exist(self):
        req=mode_request(dict(features=[]),'reasoning')
        req['request']={'task_variants':{'reasoning':{'input':{'features':[
            dict(id='missing',claim=True,epistemic='observed',evidence_refs=['missing'])]}}}}
        self.assertError('dangling_reference',lambda:build_context('observation_context',req))

    def test_cli_three_formats_keep_kind_and_selected_canonical_json(self):
        req=variant_case('output_contract');req['input']['task']={'kind':'reasoning'}
        env={**os.environ,'PYTHONPATH':str(ROOT)}
        for style in ('json','text_json','text'):
            run=subprocess.run([sys.executable,'-B','-m','context_components','output_contract',
                               '--format','bundle','--content-format',style],input=dumps(req),
                               text=True,capture_output=True,env=env)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            packet=loads(run.stdout);validate(packet,'delivery')
            block=packet['blocks'][0]['text']
            self.assertIn('reasoning',block)
            self.assertNotIn('hybrid',block)


if __name__=='__main__':unittest.main()
