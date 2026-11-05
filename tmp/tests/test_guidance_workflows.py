"""Decision guidance follows actual results while retaining canonical evidence."""
import unittest

from context_components import build_context, Resolved
from context_components.common import cas, dumps
from context_components.presentation import instructions
from context_components.render import render_context
from test_render_presentation import build, request, reference, resource_payload, text, OPTS


def guide(result):
    return '\n'.join(instructions(result))


class GuidanceWorkflowTests(unittest.TestCase):
    def test_task_kind_changes_workflow_without_guessing_from_task_name(self):
        for kind in ('execution', 'reasoning', 'hybrid'):
            payload = dict(task=dict(text='Complete the published task.', kind=kind))
            result = build('task_context', payload)
            explanation = guide(result)
            self.assertIn('provisional plan', explanation)
            self.assertIn('completion checks', explanation)
            self.assertIn('expected outcome', explanation)
            self.assertIn('failed attempt', explanation)
            self.assertIn('all explicit requirements', explanation)
            self.assertEqual('question does not imply' in explanation, kind in ('reasoning', 'hybrid'))
            self.assertEqual('work that changes the environment' in explanation, kind != 'reasoning')
            self.assertEqual('required answer and the required environmental outcome' in explanation, kind == 'hybrid')
            self.assertNotIn('state_update accompanies', explanation)
            # Never infer capabilities or robot workflow from benchmark names or prose.
            payload['task']['text'] = 'LIBERO robot manipulation, RoboMME video, real robot, unknown benchmark.'
            self.assertEqual(guide(build('task_context', payload)), explanation)

    def test_task_retraction_changes_evidence_guidance_without_rewriting_goals(self):
        event = dict(id='access', claim=True, epistemic='observed', evidence_refs=['source'],
                     source_namespace='fixture', revision=0)
        observation = build('observation_context', dict(events=[event]), references=[reference()])
        payload = dict(task=dict(text='Complete the requested work.', kind='hybrid'), goals=[
            dict(id='access', description='Access is confirmed'),
            dict(id='finish', description='Complete the next operation', depends_on=['access'], status='attempted')],
            procedure=dict(completion={'access': dict(fact_id='access', equals=True)}))
        before = build('task_context', payload, upstream=[dict(context=observation)])
        self.assertIn('A supported goal', guide(before))
        self.assertIn('For attempted goals', guide(before))
        self.assertNotIn('For blocked goals', guide(before))
        self.assertIn('state_update accompanies', guide(before))
        req = request(dict(events=[dict(event, revision=1, retracted=True)]),
                      references=[reference()], history=cas(None, observation['state_update']))
        req['scope']['turn_index'] = 1
        retracted = build_context('observation_context', req)
        req = request(payload, upstream=[dict(context=retracted)], history=cas(None, before['state_update']))
        req['scope']['turn_index'] = 1
        after = build_context('task_context', req)
        self.assertEqual([g['status'] for g in after['content']['goals']], ['unknown', 'blocked'])
        frozen = dumps(after)
        for style in ('json', 'text_json', 'text'):
            render_context(after, dict(OPTS, content_format=style), sources={retracted['context_id']: retracted})
        self.assertEqual(dumps(after), frozen)
        self.assertIn('For blocked goals', guide(after))
        self.assertIn('unknown goal conditions', guide(after))
        self.assertNotIn('A supported goal', guide(after))
        self.assertNotIn('For attempted goals', guide(after))

    def test_task_branches_require_explicit_conditions(self):
        payload = dict(task=dict(text='Review the record.', kind='reasoning'),
                       goals=[dict(id='g', description='Review supported claims')])
        plain = build('task_context', payload)
        self.assertNotIn('terminate a loop', guide(plain))
        payload['goals'][0].update(when=dict(fact_id='available', equals=True),
                                   repeat_until=dict(fact_id='checked', equals=True))
        conditional = build('task_context', payload)
        self.assertIn('unknown condition is not permission', guide(conditional))
        self.assertIn('terminate a loop', guide(conditional))

    def test_observation_hypotheses_and_order_do_not_become_facts(self):
        empty = build('observation_context', dict(features=[]))
        self.assertNotIn('hypothesis as a possible', guide(empty))
        payload = dict(features=[dict(id='guess', claim='Object may have moved', epistemic='hypothesis', evidence_refs=[])])
        hypothetical = build('observation_context', payload)
        self.assertIn('hypothesis as a possible explanation to test', guide(hypothetical))
        self.assertNotIn('Reconstruct event order', guide(hypothetical))
        event = dict(id='event', claim=True, epistemic='observed', evidence_refs=['source'],
                     source_namespace='fixture', revision=1)
        events = build('observation_context', dict(events=[event]), references=[reference()])
        self.assertIn('not array position', guide(events))
        self.assertIn('Repeated delivery', guide(events))
        self.assertIn('text-only receiver', guide(events))

    def test_spatial_workflow_uses_named_frames_and_individual_query_status(self):
        result = build('spatial_context', dict(frames=[dict(id='arbitrary-frame', length_unit='mm', handedness='left')],
                       queries=[dict(id='same', kind='transform', source_frame='arbitrary-frame',
                                     target_frame='arbitrary-frame', point=[1, 2, 3]),
                                dict(id='missing', kind='transform', source_frame='arbitrary-frame',
                                     target_frame='missing', point=[1, 2, 3])]))
        prose = text(result)
        self.assertIn('named physical reference point', prose)
        self.assertIn('moving reference frames change', prose)
        self.assertIn('zero coordinates', prose)
        self.assertNotIn('A projected pixel', prose)
        self.assertEqual(result['content']['results'][0]['value']['unit'], 'mm')
        self.assertEqual(result['content']['results'][1]['status'], 'unavailable')

    def test_custom_operation_kinds_do_not_require_a_fixed_robot_protocol(self):
        def operation(kind):
            return dict(id='custom', kind=kind, description='Caller-defined operation', parameters={})
        for kind in ('query', 'answer'):
            result = build('interaction_contract', dict(operations=[operation(kind)]))
            self.assertIn('without adding actuator parameters', guide(result))
            self.assertNotIn('what holds or resets', guide(result))
        control = build('interaction_contract', dict(operations=[operation('custom_joint_mode')],
                        control_groups=[dict(entities=['left', 'right'])], execution_semantics={'timing': 'caller-defined'}))
        self.assertIn('If a declared operation controls', guide(control))
        self.assertIn('multiple entities', guide(control))
        self.assertIn('If only a prefix is executed', guide(control))
        for assumption in ('20 Hz', 'seven', 'LIBERO', 'world +z', 'g = -1'):
            self.assertNotIn(assumption, guide(control))

    def test_feedback_interruption_changes_retry_guidance_only_when_reported(self):
        payload = dict(executions=[dict(id='work', status='interrupted', submitted=dict(items=9), executed=dict(items=3))])
        failed = build('execution_feedback', payload)
        self.assertIn('partial effects to avoid duplicate work', guide(failed))
        self.assertIn('unreported failure cause unknown', guide(failed))
        self.assertEqual(failed['content']['segments'][0]['executed_items'], 3)
        payload['executions'][0]['status'] = 'complete'
        completed = build('execution_feedback', payload)
        self.assertNotIn('partial effects to avoid duplicate work', guide(completed))
        self.assertIn('execution status alone', guide(completed))
        empty = build('execution_feedback', dict(executions=[]))
        self.assertNotIn('Match each segment', guide(empty))
        self.assertIn('not a measurement of zero', guide(empty))

    def test_response_candidates_with_missing_support_are_not_ranked_as_zero(self):
        from test_render_presentation import SCOPE
        rows = [dict(id=str(i), inputs={'x':i}, responses={'y':2*i+1}, conditions={}, scope=SCOPE,
                     bindings={}, evidence_refs=['source'], executed=True) for i in range(5)]
        payload = dict(variables=[dict(id='x', unit='rad', role='input'), dict(id='y', unit='m', role='response')],
                       records=rows, conditions={}, query=dict(kind='compare_candidates', radius=2,
                       distance_scale={'x':1}, candidates=[dict(id='near', inputs={'x':2}), dict(id='far', inputs={'x':100})]))
        result = build('response_evidence', payload, references=[reference()])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['content']['candidate_comparison'][1]['estimates'], [])
        self.assertIn('Missing estimates are not zero', guide(result))
        self.assertIn('small or zero residual does not prove certainty', guide(result))
        self.assertIn('Do not feed predictions back as measured records', guide(result))

    def test_resource_shortfalls_expiry_and_noninterruptible_work_are_conditional(self):
        payload = resource_payload(0)
        payload['execution_window']['interruptible'] = False
        result = build('resource_context', payload)
        self.assertIn('reduce optional work', guide(result))
        self.assertIn('non-interruptible window', guide(result))
        self.assertNotIn('An expired deadline', guide(result))
        healthy = build('resource_context', resource_payload(100))
        self.assertNotIn('reduce optional work', guide(healthy))
        self.assertNotIn('non-interruptible window', guide(healthy))
        clock = dict(clock_id='host', clock_epoch='boot', unit='s', value=10)
        expired = build('resource_context', dict(resources=[dict(id='time', unit='s', deadline=clock)],
                                                now=dict(clock, value=11)))
        self.assertIn('An expired deadline', guide(expired))
        self.assertIn('already reflected in the balance', guide(expired))

    def test_evidence_rendering_does_not_read_again_or_invent_access(self):
        accesses = []
        def reader(ref):
            accesses.append(ref['id'])
            return Resolved(b'published note', 'v1')
        req = request(dict(queries=[dict(reference_id='note', kind='readability')]),
                      references=[dict(id='note', media_type='text/plain', uri='published:note')])
        result = build_context('evidence_context', req, resolver=reader)
        count = len(accesses)
        self.assertGreater(count, 0)
        for style in ('text', 'text_json'):
            self.assertIn('not source authenticity', text(result, style))
        self.assertEqual(len(accesses), count)
        unavailable = build_context('evidence_context', req)
        self.assertEqual(unavailable['content']['entries'][0]['status'], 'unavailable')
        self.assertIn('instead of substituting an unrelated file', guide(unavailable))
        self.assertNotIn('A verified read establishes', guide(unavailable))

    def test_tool_history_does_not_grant_current_capability_or_silent_retry(self):
        call = dict(call_id='previous', tool_id='processor', version='1', status='timeout', input_refs=[])
        historical = build('tool_context', dict(calls=[call]))
        self.assertIn('retry policy', guide(historical))
        self.assertIn('No tool capabilities are listed', guide(historical))
        self.assertNotIn('choose a listed tool that can answer it', guide(historical))
        capability = dict(id='processor', purpose='Process supplied data', input_schema={'type':'object'},
                          output_schema={'type':'object'}, effects=['process_data'], limits={})
        current = build('tool_context', dict(calls=[dict(call, status='succeeded')]), tools=[capability])
        self.assertIn('choose a listed tool that can answer it', guide(current))
        self.assertIn('inputs, version, and scope still apply', guide(current))
        self.assertNotIn('retry unchanged calls indefinitely', guide(current))
        self.assertIn('does not authorize robot actions or backend communication', guide(current))

    def test_output_repairs_require_revalidation_and_preserve_exact_values(self):
        payload = dict(delivery=dict(kind='json'), contract=dict(schema={'type':'integer'},
                       rules=[dict(id='keep', kind='parsed_value_equal', value=7)]), candidate=8)
        failed = build('output_contract', payload)
        self.assertIn('validate the complete revised candidate again', guide(failed))
        self.assertIn('protected content', guide(failed))
        payload['candidate'] = 7
        passed = build('output_contract', payload)
        self.assertTrue(all(c['status'] == 'passed' for c in passed['content']['checks']))
        self.assertNotIn('candidate has reported failures', guide(passed))
        self.assertIn('Changes to either require a new check', guide(passed))
        self.assertIn('Structural compliance alone', guide(passed))
        self.assertEqual(failed['content']['requirements'], passed['content']['requirements'])


if __name__ == '__main__':
    unittest.main()
