import copy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from context_components import build_context,compose,ContextError,Services,InformationTool,Resolved,FileResolver
from context_components.common import loads,dumps,equal,cas,validate
from context_components.render import render_context,apply_delta,ReceiverState
from context_components.adapters.core import decode_depth_sample

ROOT=Path(__file__).resolve().parents[1]
SCOPE=dict(run_id='test',task_id='task',epoch_id='world',turn_index=0)


def request(payload,**extras):return dict(schema_version='context.v1',scope=copy.deepcopy(SCOPE),input=payload,**extras)
def ref(rid,value=None):return dict(id=rid,media_type='application/json',inline={} if value is None else value)
def fixture(name):return loads((ROOT/'examples'/name).read_bytes())


class ComponentsTest(unittest.TestCase):
    def assertError(self,code,fn):
        with self.assertRaises(ContextError) as caught:fn()
        self.assertEqual(caught.exception.issue['code'],code)

    def test_original_design_requests_execute(self):
        for ex in fixture('protocol-examples.json')['examples']:
            with self.subTest(ex=ex['id']):
                result=build_context(ex['component'],ex['input'])
                validate(result,'output');validate(result['content'],component=ex['component'],direction='output')
                self.assertEqual(result['status'],ex['expected_output']['status'])
        for ex in fixture('payload-examples.json')['positive']:
            with self.subTest(ex=ex['id']):
                result=build_context(ex['component'],request(ex['input']))
                validate(result,'output')

    def test_strict_json_precision_and_identity(self):
        for raw in ['{"a":1,"a":2}','[NaN]','[Infinity]']:
            self.assertError('invalid_request',lambda:loads(raw))
        value=loads('{"n":9007199254740993,"x":0.1000000000000000001}')
        self.assertEqual(value['x'],Decimal('0.1000000000000000001'))
        self.assertTrue(equal(value,loads(dumps(value))))
        self.assertFalse(equal(True,1));self.assertFalse(equal('1',1))
        self.assertEqual(loads('1e1000'),Decimal('1e1000'))

    def test_published_utf8_text_observation(self):
        text = '抽屉已关闭。\nKeep this observation verbatim.'
        resource = dict(id='note', media_type='text/plain', uri='published:note')
        req = request(dict(observations=[dict(id='note', modality='text', reference_id='note')]),
                      references=[resource])
        result = build_context('observation_context', req,
                               resolver=lambda _: Resolved(text.encode('utf-8'), 'v1'))
        self.assertEqual(result['content']['entities'][0]['claim'], text)
        self.assertIn('digest', result['references'][0])
        self.assertError('invalid_request', lambda: build_context('observation_context', req,
                         resolver=lambda _: Resolved(b'\xff', 'v1')))

    def test_tool_call_resources_survive_delivery(self):
        req = request(dict(calls=[dict(call_id='c', tool_id='processor', status='succeeded',
                      version='1', input_refs=['input'], output_refs=['output'])]),
                      references=[ref('input', {'x': 1}), ref('output', {'y': 2}), ref('unused')])
        result = build_context('tool_context', req)
        self.assertEqual({r['id'] for r in result.get('references', [])}, {'input', 'output'})
        packet = render_context(result, dict(receiver_id='agent', session_id='s'))
        self.assertEqual({r['source']['reference_id'] for r in packet['resources']}, {'input', 'output'})

    def test_boolean_output_schemas_and_rule_references(self):
        for schema, expected in [(True, 'passed'), (False, 'failed')]:
            result = build_context('output_contract', request(dict(delivery=dict(kind='json'),
                                   contract=dict(schema=schema), candidate={'x': 1})))
            self.assertEqual(result['content']['checks'][0]['status'], expected)
        req = request(dict(delivery=dict(kind='text'), contract=dict(rules=[dict(id='exact',
                      kind='exact_text', candidate_reference_id='candidate', expected_reference_id='expected')]),
                      candidate='A'), references=[dict(id=r, media_type='text/plain', uri=r)
                                                 for r in ('candidate', 'expected')])
        result = build_context('output_contract', req, resolver=lambda _: Resolved(b'A', 'v1'))
        self.assertEqual({r['id'] for r in result.get('references', [])}, {'candidate', 'expected'})
        literal = {'reference_id': 'ordinary-answer-field', 'input_refs': ['answer-data']}
        result = build_context('output_contract', request(dict(delivery=dict(kind='json'),
                               contract=dict(rules=[dict(id='literal', kind='parsed_value_equal', value=literal)]),
                               candidate=literal)))
        self.assertEqual(result['content']['checks'][0]['status'], 'passed')
        self.assertNotIn('references', result)

    def test_spatial_design_arithmetic_and_failure_modes(self):
        for case in fixture('review5-examples.json')['spatial_cases']:
            if 'payload' not in case:continue
            with self.subTest(case=case['id']):
                payload=case['payload'];rids=set()
                def walk(v):
                    if isinstance(v,dict):
                        rids.update(v.get('evidence_refs',[]))
                        rids.update(value for key,value in v.items() if key.endswith('reference_id') and isinstance(value,str))
                        for x in v.values():walk(x)
                    elif isinstance(v,list):
                        for x in v:walk(x)
                walk(payload)
                req=request(payload,references=[ref(r) for r in rids])
                if case['expected'].get('schema_valid') is False:
                    self.assertError('invalid_request',lambda:build_context('spatial_context',req));continue
                result=build_context('spatial_context',req)['content']['results'][0]
                expected=case['expected']
                if 'issue' in expected:
                    self.assertEqual(result['status'],'unavailable');self.assertEqual(result['issues'][0]['code'],expected['issue'])
                else:
                    for field in ('point','direction','origin'):
                        if field in expected:
                            for a,b in zip(result['value'][field],expected[field]):self.assertAlmostEqual(float(a),float(b),places=10)
                    if 'distance' in expected:self.assertAlmostEqual(result['value']['distance'],float(expected['distance']))

    def test_spatial_projection_and_partial_results(self):
        req=copy.deepcopy(fixture('protocol-examples.json')['examples'][1]['input'])
        req['input']['queries'].append(dict(id='bad',kind='project',camera_id='missing',point=[1,2,3],frame_id='camera'))
        result=build_context('spatial_context',req)
        self.assertEqual(result['status'],'partial');self.assertEqual(result['content']['results'][0]['value']['pixel'],[352,304])
        self.assertEqual(result['content']['results'][0]['value']['occlusion'],'unknown')

    def test_transform_reverse_units_and_conflicting_paths(self):
        base=copy.deepcopy(next(c['payload'] for c in fixture('review5-examples.json')['spatial_cases'] if c['id']=='J04'))
        base['queries']=[dict(id='inverse',kind='transform',point=[2,2,0],source_frame='world',target_frame='body')]
        result=build_context('spatial_context',request(base,references=[ref('pose')]))
        self.assertEqual(result['content']['results'][0]['value']['point'],[1,0,0])
        second=copy.deepcopy(base['transforms'][0]);second['id']='conflict';second['translation']=[2,2,0];base['transforms'].append(second)
        result=build_context('spatial_context',request(base,references=[ref('pose')]))
        self.assertEqual(result['content']['results'][0]['issues'][0]['code'],'ambiguous_transform')

    def test_bounded_memory_duplicate_revision_retraction(self):
        event=dict(id='e',source_namespace='sensor',revision=0,claim='press',epistemic='observed',evidence_refs=['e'])
        first=build_context('observation_context',request(dict(events=[event,event]),references=[ref('e')]))
        self.assertEqual(first['content']['coverage']['unique_active_events'],1)
        history=cas(None,first['state_update'])
        again=request(dict(events=[event]),references=[ref('e')],history=history);again['scope']['turn_index']=1
        second=build_context('observation_context',again)
        self.assertEqual(second['content']['coverage']['unique_active_events'],1)
        event2={**event,'revision':1,'retracted':True}
        again['input']['events']=[event2];again['history']=cas(history,second['state_update']);again['scope']['turn_index']=2
        last=build_context('observation_context',again)
        self.assertEqual(last['content']['coverage']['unique_active_events'],0)
        self.assertTrue(last['content']['events'][0]['retracted'])
        many=[{**event,'id':str(i)} for i in range(4)]
        bounded=build_context('observation_context',request(dict(events=many),references=[ref('e')]),services=Services(max_records=2))
        self.assertEqual(bounded['content']['count_status'],'incomplete')
        self.assertEqual(len(bounded['state_update']['state']['value']['records']),2)

    def test_conflicting_event_revision_and_source_run(self):
        event=dict(id='same',source_namespace='sensor',revision=0,claim='press',epistemic='observed',evidence_refs=['e'])
        req=request(dict(events=[event,{**event,'claim':'release'}]),references=[ref('e')])
        self.assertError('conflicting_revision',lambda:build_context('observation_context',req))
        req['input']['events']=[{**event,'scope':{**SCOPE,'run_id':'a'}},{**event,'scope':{**SCOPE,'run_id':'b'}}]
        self.assertEqual(build_context('observation_context',req)['content']['coverage']['unique_active_events'],2)

    def test_state_cas_conflict_and_idempotency(self):
        ex=fixture('protocol-examples.json')['examples'][3]
        result=build_context(ex['component'],ex['input']);update=result['state_update']
        saved=cas(None,update);self.assertEqual(cas(saved,update),saved)
        other=copy.deepcopy(update);other['state']['state_id']='other'
        self.assertError('state_conflict',lambda:cas(saved,other))
        changed=copy.deepcopy(update);changed['state']['value']['unknown']=True
        self.assertError('state_conflict',lambda:cas(saved,changed))

    def test_task_dependency_evidence_and_unknown(self):
        feature=dict(id='closed',claim=True,epistemic='observed',evidence_refs=['f'])
        upstream=build_context('observation_context',request(dict(features=[feature]),references=[ref('f')]))
        task=dict(task=dict(text='Check closed cabinet',kind='execution'),goals=[dict(id='close',description='Cabinet closed'),dict(id='next',description='Next',depends_on=['close'])],procedure=dict(completion={'close':dict(fact_id='closed',equals=True)}))
        result=build_context('task_context',request(task,upstream=[dict(context=upstream)]))
        self.assertEqual(result['content']['goals'][0]['status'],'supported')
        absent=build_context('task_context',request(task))
        self.assertEqual(absent['content']['goals'][0]['status'],'unknown')
        self.assertEqual(absent['content']['goals'][1]['status'],'blocked')

    def test_execution_never_substitutes_accepted_count(self):
        result=build_context('execution_feedback',request(dict(executions=[dict(id='e',status='accepted',accepted=dict(items=5))])))
        self.assertNotIn('executed_items',result['content']['segments'][0])
        self.assertTrue(result['content']['unknowns'])
        req=request(dict(executions=[dict(id='e',status='complete',submitted=dict(items=2),executed=dict(items=3))]))
        self.assertError('invalid_request',lambda:build_context('execution_feedback',req))

    def test_resource_clock_and_units(self):
        clock=dict(clock_id='steady',clock_epoch='1',unit='s',value=10)
        req=request(dict(resources=[dict(id='time',unit='s',deadline={**clock,'value':20})],now=clock,
                         cost_model=dict(version='1',per_item=dict(time=dict(value=3,unit='s'))),workload=dict(items=4)))
        result=build_context('resource_context',req)
        self.assertEqual(result['content']['supported_work']['joint_items'],3)
        self.assertEqual(result['content']['shortfalls'],[dict(resource_id='time',items=1)])
        req['input']['now']['clock_epoch']='reset'
        self.assertEqual(build_context('resource_context',req)['status'],'partial')

    def test_output_candidate_preserved_and_unknown_rule(self):
        candidate={};req=request(dict(delivery=dict(kind='json'),contract=dict(schema={'type':'object','properties':{'x':{'default':1}},'required':['x']}),candidate=candidate))
        original=copy.deepcopy(req);result=build_context('output_contract',req)
        self.assertEqual(req,original);self.assertEqual(result['content']['checks'][0]['status'],'failed')
        req['input']['contract']['schema']={'type':'string','format':'email'};req['input']['candidate']='bad'
        self.assertEqual(build_context('output_contract',req)['content']['checks'][0]['status'],'not_evaluated')
        req['input']['contract']['schema']={'type':'object'};req['input']['candidate']={'reference_id':'candidate-data-not-a-resource'}
        self.assertEqual(build_context('output_contract',req)['content']['checks'][0]['status'],'passed')

    def test_local_response_estimation_and_no_extrapolation(self):
        rows=[dict(id=str(i),inputs={'x':i},responses={'y':2*i+1},conditions={},scope=SCOPE,bindings={},evidence_refs=['r'],executed=True) for i in range(5)]
        payload=dict(variables=[dict(id='x',role='input',unit='rad'),dict(id='y',role='response',unit='rad')],records=rows,conditions={},query=dict(kind='estimate',inputs={'x':2},radius=2,distance_scale={'x':1}))
        result=build_context('response_evidence',request(payload,references=[ref('r')]))
        self.assertAlmostEqual(result['content']['estimates'][0]['value'],5)
        payload['query']['inputs']['x']=100
        self.assertEqual(build_context('response_evidence',request(payload,references=[ref('r')]))['status'],'unavailable')

    def test_tools_explicit_injection_and_late_result(self):
        tool=dict(id='vision',purpose='Interpret published frame',input_schema={'type':'object'},output_schema={'type':'object'},effects=['process_data'],limits={})
        obs=dict(id='frame',modality='image',reference_id='r')
        claim=dict(id='object',claim='red',epistemic='estimated',method=dict(id='fake',version='1'),evidence_refs=['r'])
        req=request(dict(observations=[obs],extractors=['vision']),references=[ref('r')],tools=[tool])
        provider=InformationTool(lambda a,r,l:dict(features=[claim]),{'process_data'})
        result=build_context('observation_context',req,services=Services(tools={'vision':provider}))
        self.assertEqual(result['content']['entities'][0]['epistemic'],'estimated')
        ticks=iter([0,31]);late=Services(tools={'vision':provider},clock=lambda:next(ticks))
        result=build_context('observation_context',req,services=late)
        self.assertEqual(result['status'],'unavailable');self.assertNotIn('state_update',result)
        self.assertError('invalid_request',lambda:InformationTool(lambda *a:None,{'backend_read'}))

    def test_resolver_hash_links_fifo_and_no_implicit_reads(self):
        import os
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'value.json').write_text('{"x":1}')
            resolver=FileResolver(root,{'value':'value.json'})
            self.assertEqual(loads(resolver({'uri':'value'}).data),{'x':1})
            os.symlink(root/'value.json',root/'link')
            self.assertError('reference_unavailable',lambda:FileResolver(root,{'x':'link'})({'uri':'x'}))
            os.mkfifo(root/'fifo')
            self.assertError('forbidden_reference',lambda:FileResolver(root,{'x':'fifo'})({'uri':'x'}))
            self.assertError('forbidden_reference',lambda:resolver({'uri':'other'}))
            req=request(dict(queries=[dict(kind='readability',reference_id='r')]),references=[dict(id='r',uri='value',media_type='application/json',digest='sha256:'+'0'*64)])
            self.assertError('reference_changed',lambda:build_context('evidence_context',req,resolver=resolver))

    def test_composition_scope_cycle_and_independent_failure(self):
        node=dict(id='task',component='task_context',request=request(dict(task=dict(text='Q',kind='reasoning'))))
        graph=dict(schema_version='context.compose.v1',scope=SCOPE,nodes=[node])
        self.assertEqual(compose(graph)['status'],'ready')
        bad=copy.deepcopy(graph);bad['nodes'][0]['upstream_nodes']=['task']
        self.assertError('invalid_request',lambda:compose(bad))
        bad=copy.deepcopy(graph);bad['nodes'][0]['request']['scope']['perspective_id']='other'
        self.assertError('identity_mismatch',lambda:compose(bad))
        invalid=dict(id='bad',component='resource_context',request=request(dict(resources=[],execution_window=dict(max_items=1,minimum_items=2,interruptible=False))))
        graph['nodes'].append(invalid)
        result=compose(graph);self.assertEqual(result['status'],'partial');self.assertIn('result',result['nodes'][0]);self.assertIn('error',result['nodes'][1])

    def test_delivery_full_delta_retention_and_budget(self):
        result=build_context('task_context',request(dict(task=dict(text='Question',kind='reasoning'))))
        opts=dict(receiver_id='r',session_id='s')
        full=render_context(result,opts)
        later=copy.deepcopy(result);later['scope']['turn_index']=1;later['context_id']='new'
        later['content']['open_questions']=['Evidence revoked']
        retained=dict(receiver_id='r',session_id='s',base_delivery_id=full['delivery_id'],base_packet=full)
        self.assertEqual(render_context(later,{**opts,'mode':'delta','retained':retained})['mode'],'full')
        delta=render_context(later,{**opts,'mode':'delta','retained':retained,'reconstructs_context':True})
        rebuilt=apply_delta(full,delta)
        self.assertIn('Evidence revoked',rebuilt['blocks'][0]['text'])
        bad=copy.deepcopy(delta);bad['operations'].append(dict(op='remove',id='missing'))
        self.assertError('invalid_delta',lambda:apply_delta(full,bad))
        self.assertError('context_budget_insufficient',lambda:render_context(result,{**opts,'budget':{'max_bytes':1}}))
        host=ReceiverState();host.submitted(1);host.submitted(2)
        self.assertError('stale_delivery',lambda:host.accept(1,full))
        host.accept(2,full);self.assertEqual(host.accept(2,full),full)

    def test_depth_source_profiles(self):
        self.assertEqual(decode_depth_sample(0,'ros_openni_uint16'),{'status':'invalid'})
        self.assertEqual(decode_depth_sample(1200,'ros_openni_uint16')['value'],1.2)
        for value,status in [(math.nan,'invalid'),(math.inf,'above_max_range'),(-math.inf,'below_min_range')]:
            self.assertEqual(decode_depth_sample(value,'ros_rep118_32fc1')['status'],status)
        self.assertEqual(decode_depth_sample(0,'robomme_hdf5_int16_mm')['status'],'unknown')


if __name__=='__main__':unittest.main()
