"""Normalize explicitly published reset/dataset transitions without querying environments."""
import copy

from ..common import fail,same_scope,unique,validate


def split_autoreset_transition(record):
    required={'mode','before_scope','after_scope','observation','terminated','truncated','reset_only'}
    if not required<=record.keys() or set(record)-required-{'final_observation','executed_items'}:
        fail('invalid_request','Transition export fields missing or unknown')
    for key in ('before_scope','after_scope'):validate(record[key],'scope')
    for key in ('terminated','truncated','reset_only'):
        if type(record[key]) is not bool:fail('invalid_request','Transition flags must be booleans')
    mode=record['mode']
    if mode not in ('SAME_STEP','NEXT_STEP','DISABLED'):fail('unsupported_version','Explicit known autoreset mode is required')
    terminal=record['terminated'] or record['truncated']
    changed=not same_scope(record['before_scope'],record['after_scope'])
    if any(record['before_scope'].get(k)!=record['after_scope'].get(k) for k in ('run_id','task_id','perspective_id')):
        fail('identity_mismatch','Reset cannot silently change task, run or observation perspective')
    count=record.get('executed_items')
    if count is not None and (type(count) is not int or count<0):fail('invalid_request','Execution count must be nonnegative integer')
    observations=[]
    if mode=='SAME_STEP' and terminal:
        if not changed or 'final_observation' not in record or record['reset_only']:
            fail('identity_mismatch','SAME_STEP terminal/reset observations require distinct epochs and final observation')
        observations.append(dict(scope=copy.deepcopy(record['before_scope']),role='terminal',value=copy.deepcopy(record['final_observation'])))
        observations.append(dict(scope=copy.deepcopy(record['after_scope']),role='reset',value=copy.deepcopy(record['observation'])))
    elif mode=='NEXT_STEP' and record['reset_only']:
        if not changed or count not in (None,0):fail('identity_mismatch','Reset-only response cannot execute actions')
        count=0
        observations.append(dict(scope=copy.deepcopy(record['after_scope']),role='reset',value=copy.deepcopy(record['observation'])))
    else:
        if changed or record['reset_only']:fail('identity_mismatch','Ordinary transition unexpectedly changes epoch')
        observations.append(dict(scope=copy.deepcopy(record['before_scope']),role='terminal' if terminal else 'observation',value=copy.deepcopy(record['observation'])))
    return dict(observations=observations,executed_items=count,terminated=record['terminated'],truncated=record['truncated'])


def normalize_rlds_step(step,*,invalid_episode=False):
    for key in ('is_first','is_last','is_terminal'):
        if key not in step or type(step[key]) is not bool:fail('invalid_request','RLDS step flags must be explicit booleans')
    out=copy.deepcopy(step)
    if out['is_last']:
        for key in ('action','reward','discount'):out.pop(key,None)
    out['eligible_response_evidence']=not invalid_episode and not out['is_last']
    return out


def validate_vector_scopes(exports):
    slots=set()
    for export in exports:
        scope=export['scope'];validate(scope,'scope')
        key=tuple(scope.get(k) for k in ('run_id','task_id','epoch_id','perspective_id'))
        if key in slots:fail('identity_mismatch','Vector slots must not share a context state identity')
        slots.add(key)
