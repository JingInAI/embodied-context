import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from context_components import build_context,compose,ContextError,Services,InformationTool
from context_components.common import cas,dumps,loads
from context_components.render import render_context
from context_components.adapters.core import adapt,profiles,ExportPolicy
from test_adapters import make_export
from test_components import request,ref,fixture,SCOPE


ROOT=Path(__file__).resolve().parents[2]


class IntegrationTest(unittest.TestCase):
    def test_terminal_reset_and_dataset_boundaries(self):
        from context_components.adapters.transitions import split_autoreset_transition,normalize_rlds_step,validate_vector_scopes
        record=dict(mode='SAME_STEP',before_scope=SCOPE,after_scope={**SCOPE,'epoch_id':'new'},observation={'reset':True},final_observation={'terminal':True},terminated=True,truncated=False,reset_only=False,executed_items=1)
        result=split_autoreset_transition(record)
        self.assertEqual([o['scope']['epoch_id'] for o in result['observations']],['world','new'])
        record.update(mode='NEXT_STEP',reset_only=True,executed_items=0);record.pop('final_observation')
        self.assertEqual(split_autoreset_transition(record)['executed_items'],0)
        record['executed_items']=1
        with self.assertRaises(ContextError):split_autoreset_transition(record)
        step=normalize_rlds_step(dict(is_first=False,is_last=True,is_terminal=True,action=[9],reward=1,discount=0))
        self.assertNotIn('action',step);self.assertFalse(step['eligible_response_evidence'])
        with self.assertRaises(ContextError):validate_vector_scopes([dict(scope=SCOPE),dict(scope=SCOPE)])

    def test_cli_stdin_files_relocation_and_preservation(self):
        req=request(dict(task=dict(text='A question',kind='reasoning')))
        with tempfile.TemporaryDirectory() as tmp:
            env={**os.environ,'PYTHONPATH':str(ROOT)+os.pathsep+os.environ.get('PYTHONPATH','')}
            command=[sys.executable,'-B','-m','context_components','task_context']
            run=subprocess.run(command,input=dumps(req),text=True,cwd=tmp,env=env,capture_output=True)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertEqual(loads(run.stdout)['component'],'task_context')
            output=Path(tmp)/'new.json'
            run=subprocess.run(command+['--output',str(output)],input=dumps(req),text=True,cwd=tmp,env=env,capture_output=True)
            self.assertEqual(run.returncode,0)
            original=output.read_bytes()
            repeated=subprocess.run(command+['--output',str(output)],input=dumps(req),text=True,cwd=tmp,env=env,capture_output=True)
            self.assertEqual(repeated.returncode,2);self.assertEqual(output.read_bytes(),original)
            duplicate=subprocess.run(command,input='{"a":1,"a":2}',text=True,cwd=tmp,env=env,capture_output=True)
            self.assertEqual(duplicate.returncode,2);self.assertEqual(loads(duplicate.stdout)['schema_version'],'context.error.v1')

    def test_retraction_reopens_downstream_goal(self):
        event=dict(id='done',source_namespace='sensor',revision=0,claim=True,epistemic='observed',evidence_refs=['r'])
        first=build_context('observation_context',request(dict(events=[event]),references=[ref('r')]))
        task=dict(task=dict(text='Verify task',kind='execution'),goals=[dict(id='g',description='Goal')],procedure=dict(completion={'g':dict(fact_id='done',equals=True)}))
        before=build_context('task_context',request(task,upstream=[dict(context=first)]))
        self.assertEqual(before['content']['goals'][0]['status'],'supported')
        next_req=request(dict(events=[{**event,'revision':1,'retracted':True}]),references=[ref('r')],history=cas(None,first['state_update']))
        next_req['scope']['turn_index']=1
        second=build_context('observation_context',next_req)
        task_req=request(task,upstream=[dict(context=second)],history=cas(None,before['state_update']))
        task_req['scope']['turn_index']=1
        after=build_context('task_context',task_req)
        self.assertEqual(after['content']['goals'][0]['status'],'unknown')
        packet=render_context(after,dict(receiver_id='r',session_id='s'))
        self.assertIn('unknown',packet['blocks'][0]['text'])

    def test_geometry_tool_extension_and_shared_budget(self):
        case=copy.deepcopy(next(c for c in fixture('review5-examples.json')['spatial_cases'] if c['id']=='J18'))
        payload=case['payload'];payload['processors']={payload['queries'][0]['id']:'geometry'}
        refs=[ref('calibration'),ref('depth'),ref('fisheye_schema',{'type':'object','required':['focal']})]
        tool=dict(id='geometry',purpose='Explicit camera model processor',input_schema={'type':'object'},output_schema={'type':'object'},effects=['process_data'],limits={})
        calls=[]
        def process(args,refs,limits):
            calls.append(args)
            return dict(query_id=args['query']['id'],status='ready',value=dict(kind='point',point=[1,0,1],frame_id='camera',unit='m'),evidence_refs=['calibration','depth'],method=dict(id='test_processor',version='1'))
        services=Services(tools={'geometry':InformationTool(process,{'process_data'})},max_calls=1)
        req=request(payload,references=refs,tools=[tool])
        result=build_context('spatial_context',req,services=services)
        self.assertEqual(result['content']['results'][0]['epistemic'],'estimated')
        result=build_context('spatial_context',req,services=services)
        self.assertEqual(result['status'],'unavailable');self.assertEqual(len(calls),1)

    def test_response_hull_expiry_and_history(self):
        clock=dict(clock_id='physical',clock_epoch='1',unit='s',value=0)
        records=[dict(id=str(i),inputs={'x':i},responses={'y':2*i},conditions={},scope=SCOPE,bindings={},evidence_refs=['r'],executed=True,time=clock) for i in range(4)]
        payload=dict(variables=[dict(id='x',unit='m',role='input'),dict(id='y',unit='m',role='response')],records=records,conditions={},query=dict(kind='estimate',inputs={'x':4},radius=10,distance_scale={'x':1}))
        outside=build_context('response_evidence',request(payload,references=[ref('r')]))
        self.assertEqual(outside['status'],'unavailable')
        payload['query']['inputs']['x']=1.5
        good=build_context('response_evidence',request(payload,references=[ref('r')]))
        self.assertEqual(good['status'],'ready')
        payload['records']=[];payload['query'].update(max_age_seconds=1,now={**clock,'value':5})
        req=request(payload,history=cas(None,good['state_update']));req['scope']['turn_index']=1
        expired=build_context('response_evidence',req)
        self.assertEqual(expired['status'],'unavailable')

    def test_all_benchmarks_history_and_scope_rejection(self):
        for definition in profiles():
            export,policy=make_export(definition)
            event=dict(id='clue',claim='published clue',epistemic='observed',evidence_refs=['event'],source_namespace='export',revision=0)
            export['references'].append(ref('event'))
            export['supplements']={'observation_context':{'events':[event]}}
            policy=ExportPolicy(policy.public_paths+('/supplements/observation_context',))
            first=adapt(definition['adapter'],export,policy=policy)
            obs=next(n['request'] for n in first['compose']['nodes'] if n['component']=='observation_context')
            result=build_context('observation_context',obs)
            history=cas(None,result['state_update'])
            export['scope']['turn_index']=1;export['history']={'observation_context':history}
            second=adapt(definition['adapter'],export,policy=policy)
            obs=next(n['request'] for n in second['compose']['nodes'] if n['component']=='observation_context')
            result=build_context('observation_context',obs)
            self.assertEqual(result['content']['coverage']['unique_active_events'],1)
            obs['scope']['epoch_id']='reset'
            with self.assertRaises(ContextError):build_context('observation_context',obs)

    def test_plain_text_and_exact_resource_contracts(self):
        req=request(dict(delivery=dict(kind='text'),contract=dict(rules=[dict(id='exact',kind='exact_text',candidate_reference_id='candidate',expected_reference_id='expected')]),candidate='unchanged'),references=[dict(id='candidate',uri='candidate',media_type='text/plain'),dict(id='expected',uri='expected',media_type='text/plain')])
        from context_components.common import Resolved
        content={'candidate':b'A\n','expected':b'A'}
        result=build_context('output_contract',req,resolver=lambda r:Resolved(content[r['uri']],'version-1'))
        self.assertEqual(result['content']['checks'][0]['status'],'failed')
        self.assertEqual(req['input']['candidate'],'unchanged')


if __name__=='__main__':unittest.main()
