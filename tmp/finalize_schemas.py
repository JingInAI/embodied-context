"""Fill domain subcontracts that draft-5 deliberately left for implementation P1."""
import json
from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/'context_components/schemas'
STRING={'type':'string','minLength':1}
NUMBER={'type':'number'}
POSITIVE={'type':'number','exclusiveMinimum':0}
COMMON='urn:context-design:common:v1#/$defs/'


def obj(props,required=None):return dict(type='object',properties=props,required=list(props) if required is None else required,additionalProperties=False)
def array(item):return dict(type='array',items=item)
def ref(name):return {'$ref':'#/$defs/'+name}


def extend_v11(defs):
    """Add opt-in v1-1 fields; legacy inputs and state shapes remain valid."""
    evidence = array(STRING)
    evidence['minItems'] = 1
    defs['condition']['oneOf'].append(obj({
        'fact_id': STRING, 'operator': {'enum': ['lt', 'le', 'gt', 'ge']}, 'value': NUMBER}))
    rule = obj({'id': STRING, 'when': ref('condition'), 'recommendation': STRING,
                'evidence_refs': evidence, 'max_age_turns': {'type': 'integer', 'minimum': 0},
                'required_bindings': {'$ref': COMMON+'bindings'}, 'next_check': STRING,
                'example_reference_id': STRING}, ['id', 'when', 'recommendation', 'evidence_refs'])
    defs['task_context_input']['properties']['decision_rules'] = array(rule)
    defs['task_context_output']['properties']['decision_support'] = array(obj({
        'id': STRING, 'status': {'enum': ['applicable', 'not_applicable', 'unresolved']},
        'condition_result': {'type': ['boolean', 'null']}, 'evaluated_condition': ref('condition'),
        'evidence_refs': evidence, 'recommendation': STRING, 'next_check': STRING,
        'example_reference_id': STRING, 'limitations': array(STRING),
        'max_age_turns': {'type': 'integer', 'minimum': 0},
        'required_bindings': {'$ref': COMMON+'bindings'}},
        ['id', 'status', 'condition_result', 'evaluated_condition', 'evidence_refs', 'limitations']))
    advice = defs['task_context_output']['properties']['decision_support']['items']
    advice['oneOf'] = [
        {'properties': {'status': {'const': 'applicable'}, 'condition_result': {'const': True}},
         'required': ['recommendation'], 'not': {'required': ['next_check']}},
        {'properties': {'status': {'const': 'not_applicable'}, 'condition_result': {'const': False}},
         'not': {'anyOf': [{'required': [key]} for key in ('recommendation', 'example_reference_id', 'next_check')]}},
        {'properties': {'status': {'const': 'unresolved'}, 'condition_result': {'type': 'null'}},
         'not': {'anyOf': [{'required': [key]} for key in ('recommendation', 'example_reference_id')]}}]
    query = defs['response_evidence_input']['properties']['query']
    query['properties']['kind']['enum'].append('describe')
    query['properties']['ratios'] = array(obj({'id': STRING, 'input': STRING,
                                              'response': STRING, 'min_abs_input': POSITIVE}))
    query['allOf'].append({'if': {'properties': {'kind': {'const': 'describe'}}},
                           'then': {'not': {'anyOf': [{'required': [k]} for k in
                              ('inputs', 'radius', 'distance_scale', 'candidates',
                               'half_life_seconds', 'max_residual_rms')]}}})
    query['allOf'].append({'if': {'required': ['ratios']},
                           'then': {'properties': {'kind': {'const': 'describe'}}}})
    statistic = obj({'variable': STRING, 'role': {'enum': ['input', 'response']},
                     'unit': STRING, 'sample_count': {'type': 'integer', 'minimum': 1},
                     'minimum': NUMBER, 'maximum': NUMBER, 'mean': NUMBER,
                     'evidence_refs': array(STRING)})
    ratio = obj({'id': STRING, 'record_id': STRING, 'input': STRING, 'response': STRING,
                 'numerator_unit': STRING, 'denominator_unit': STRING,
                 'status': {'enum': ['ready', 'unavailable']}, 'value': NUMBER,
                 'reason': STRING, 'evidence_refs': array(STRING)},
                ['id', 'record_id', 'input', 'response', 'numerator_unit',
                 'denominator_unit', 'status', 'evidence_refs'])
    ratio['oneOf'] = [
        {'properties': {'status': {'const': 'ready'}}, 'required': ['value'],
         'not': {'required': ['reason']}},
        {'properties': {'status': {'const': 'unavailable'}}, 'required': ['reason'],
         'not': {'required': ['value']}}]
    defs['response_evidence_output']['properties']['descriptive'] = obj({
        'statistics': array(statistic), 'ratios': array(ratio),
        'method': obj({'id': STRING, 'version': STRING}), 'conditions': {'type': 'object'},
        'coverage_complete': {'type': 'boolean'}, 'missing_values': array(obj({
            'record_id': STRING, 'variable': STRING})), 'limitations': array(STRING)})
    outcome = obj({'category': {'enum': ['task_evaluation', 'execution_failure',
                                        'infrastructure_failure', 'interruption', 'unknown']},
                   'evaluation_status': {'enum': ['complete', 'partial', 'not_run', 'unknown']},
                   'task_success': {'type': 'boolean'}, 'reason': STRING, 'evidence_refs': evidence},
                  ['category', 'evaluation_status', 'evidence_refs'])
    outcome['allOf'] = [{'if': {'required': ['task_success']}, 'then': {'properties': {
        'category': {'const': 'task_evaluation'}, 'evaluation_status': {'const': 'complete'}}}}]
    defs['execution_feedback_input']['properties']['executions']['items']['properties']['outcome'] = outcome
    result_outcome = obj({'execution_id': STRING, **outcome['properties']},
                         ['execution_id', *outcome['required']])
    result_outcome['allOf'] = outcome['allOf']
    defs['execution_feedback_output']['properties']['outcomes'] = array(result_outcome)


def main():
    p=PATH/'component-payload.schema.json';schema=json.loads(p.read_text());defs=schema['$defs']
    condition={'oneOf':[
        obj({'fact_id':STRING,'equals':{}}),
        obj({'all':array(ref('condition'))}),obj({'any':array(ref('condition'))}),obj({'not':ref('condition')})]}
    defs['condition']=condition
    for key in ('when','repeat_until'):defs['goal']['properties'][key]=ref('condition')
    task=defs['task_context_input']['properties']
    task['procedure']=obj({'completion':{'type':'object','additionalProperties':ref('condition')},'loops':{'type':'object','additionalProperties':ref('condition')}},[])
    task['agent_state']=obj({'version':STRING,'goal_status':{'type':'object','additionalProperties':{'enum':['pending','active','attempted','supported','blocked','unknown']}}},['version','goal_status'])
    response=defs['response_evidence_input']['properties']
    response['variables']=array(obj({'id':STRING,'unit':STRING,'role':{'enum':['input','response']}},['id','unit']));response['variables']['minItems']=1
    record=obj({'id':STRING,'inputs':{'type':'object','additionalProperties':NUMBER},'responses':{'type':'object','additionalProperties':NUMBER},
        'conditions':{'type':'object'},'scope':{'$ref':COMMON+'scope'},'bindings':{'$ref':COMMON+'bindings'},'evidence_refs':array(STRING),
        'executed':{'type':'boolean'},'retracted':{'type':'boolean'},'time':{'$ref':COMMON+'time_point'},
        'source_namespace':STRING,'origin_epoch':STRING,'revision':{'type':'integer','minimum':0}},
        ['id','inputs','responses','conditions','scope','bindings','evidence_refs','executed'])
    response['records']=array(record)
    response['query']=obj({'kind':{'enum':['support','estimate','compare_candidates']},'inputs':{'type':'object','additionalProperties':NUMBER},
        'radius':POSITIVE,'distance_scale':{'type':'object','additionalProperties':POSITIVE},'half_life_seconds':POSITIVE,'now':{'$ref':COMMON+'time_point'},
        'max_age_seconds':{'type':'number','minimum':0},'max_residual_rms':{'type':'object','additionalProperties':{'type':'number','minimum':0}},
        'candidates':array(obj({'id':STRING,'inputs':{'type':'object','additionalProperties':NUMBER}}))},['kind'])
    response['query']['allOf']=[
        {'if':{'properties':{'kind':{'const':'estimate'}}},'then':{'required':['inputs','radius','distance_scale']}},
        {'if':{'properties':{'kind':{'const':'compare_candidates'}}},'then':{'required':['candidates','radius','distance_scale']}}]
    resources=defs['resource_context_input']['properties']
    resources['workload']=obj({'items':{'type':'integer','minimum':0}})
    resources['cost_model']=obj({'version':STRING,'per_item':{'type':'object','additionalProperties':obj({'value':POSITIVE,'unit':STRING})}})
    resources['execution_window']=obj({'max_items':{'type':'integer','minimum':0},'minimum_items':{'type':'integer','minimum':0},'interruptible':{'type':'boolean'}},['max_items','interruptible'])
    defs['evidence_context_input']['properties']['queries']=array(obj({'kind':{'enum':['readability','index']},'reference_id':STRING}))
    defs['tool_context_input']['properties']['calls']=array(obj({'call_id':STRING,'tool_id':STRING,'status':{'enum':['succeeded','failed','cancelled','timeout']},
        'version':STRING,'input_refs':array(STRING),'output_refs':array(STRING),'issues':array({'$ref':COMMON+'issue'})},['call_id','tool_id','status','version','input_refs']))
    execution=defs['execution_feedback_input']['properties']['executions']['items']['properties']
    for phase in ('submitted','accepted','executed'):execution[phase]=obj({'items':{'type':'integer','minimum':0},'evidence_refs':array(STRING)},['items'])
    extend_v11(defs)
    p.write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n')
    state_defs={
        'records':array({'type':'object'}),'references':array({'$ref':COMMON+'reference'}),'complete_set':{'type':'boolean'},
        'event_keys':array({'type':'array','items':STRING,'minItems':4,'maxItems':4})}
    states={}
    for owner in ['observation_context','execution_feedback','response_evidence']:
        keys=['records','references','complete_set']+(['event_keys'] if owner=='observation_context' else [])
        states[owner]=obj({key:state_defs[key] for key in keys})
        if owner=='observation_context':
            states[owner]['properties']['records']=array({'allOf':[{'$ref':'urn:context-design:payload:v1#/$defs/claim'},{'required':['source_namespace','revision','scope','origin_epoch']}]})
        else:
            value_key='execution' if owner=='execution_feedback' else 'record'
            value_schema=defs['execution_feedback_input']['properties']['executions']['items'] if owner=='execution_feedback' else record
            wrapper=obj({'id':STRING,'source_namespace':STRING,'revision':{'type':'integer','minimum':0},'scope':{'$ref':COMMON+'scope'},'origin_epoch':STRING,
                'retracted':{'type':'boolean'},'evidence_refs':array(STRING),value_key:value_schema},['id','source_namespace','revision','scope','origin_epoch','evidence_refs',value_key])
            states[owner]['properties']['records']=array(wrapper)
    states['task_context']=obj({'task':task['task'],'goals':array({'$ref':'urn:context-design:payload:v1#/$defs/goal'}),'procedure':task['procedure'],'references':state_defs['references']})
    state={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':'urn:context-components:state-values:v1','$defs':{**states,'condition':condition}}
    (PATH/'state-values.schema.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
