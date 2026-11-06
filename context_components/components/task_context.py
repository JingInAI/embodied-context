import copy
from decimal import Decimal

from ..common import equal, fail, same_scope, unique
from ..memory import restore


def condition(expr,facts):
    if set(expr)=={'all'}:
        vals=[condition(e,facts) for e in expr['all']]
        return False if False in vals else None if None in vals else True
    if set(expr)=={'any'}:
        vals=[condition(e,facts) for e in expr['any']]
        return True if True in vals else None if None in vals else False
    if set(expr)=={'not'}:
        v=condition(expr['not'],facts);return None if v is None else not v
    if set(expr)=={'fact_id','equals'}:
        values=facts.get(expr['fact_id'],[])
        if not values or any(not equal(v,values[0]) for v in values):return None
        return equal(values[0],expr['equals'])
    if set(expr) == {'fact_id', 'operator', 'value'}:
        values = facts.get(expr['fact_id'], [])
        if not values or any(not equal(v, values[0]) for v in values):
            return None
        value = values[0]
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            return None
        threshold = expr['value']
        return {'lt': lambda: value < threshold, 'le': lambda: value <= threshold,
                'gt': lambda: value > threshold, 'ge': lambda: value >= threshold}[expr['operator']]()
    fail('invalid_request', 'Unsupported condition')


def condition_ids(expr):
    """Collect only explicitly named predicates; never interpret free text."""
    if 'fact_id' in expr:
        return {expr['fact_id']}
    if 'not' in expr:
        return condition_ids(expr['not'])
    return set().union(*(condition_ids(child) for child in expr.get('all', expr.get('any', []))))


def decision_support(inv, rules):
    """Evaluate supplied advice against current evidence, without retaining rules."""
    unique(rules)
    results = []
    for rule in rules:
        needed = condition_ids(rule['when'])
        facts, refs, invalidated = {}, [], set()
        for upstream in inv.upstream:
            if upstream['component'] != 'observation_context':
                continue
            for bucket in ('entities', 'relations', 'events'):
                for index, claim in enumerate(upstream['content'].get(bucket, [])):
                    if claim['id'] not in needed:
                        continue
                    origin = claim.get('scope', upstream['scope'])
                    age = inv.scope['turn_index'] - origin['turn_index']
                    if not same_scope(origin, inv.scope) or age > rule.get('max_age_turns', 0):
                        continue
                    if claim.get('retracted'):
                        invalidated.add(claim['id'])
                    elif claim['epistemic'] in ('observed', 'derived') and claim['evidence_refs']:
                        facts.setdefault(claim['id'], []).append(claim['claim'])
                    else:
                        # An uncertain alternative is not discarded to manufacture certainty.
                        invalidated.add(claim['id'])
                    refs.append(inv.bind_upstream(upstream, f'/content/{bucket}/{index}'))
        for name in invalidated:
            facts.pop(name, None)
        value = condition(rule['when'], facts)
        required = rule.get('required_bindings', {})
        actual = inv.request.get('bindings', {})
        mismatch = any(k in actual and not equal(v, actual[k]) for k, v in required.items())
        missing = any(k not in actual for k in required)
        if mismatch:
            value = False
        elif missing and value is not False:
            value = None
        limits = ['Applicability of caller-supplied advice only; not authorization, a new plan, or task success.',
                  'Only supported predicates within the declared turn age are used; unmodeled conditions remain unchecked.']
        if missing:
            limits.append('One or more required configuration bindings are missing.')
        if mismatch:
            limits.append('Required configuration bindings differ.')
        result = dict(id=rule['id'], status='applicable' if value is True else
                      'not_applicable' if value is False else 'unresolved', condition_result=value,
                      evaluated_condition=copy.deepcopy(rule['when']), limitations=limits,
                      max_age_turns=rule.get('max_age_turns', 0), required_bindings=copy.deepcopy(required),
                      evidence_refs=list(dict.fromkeys(rule['evidence_refs'] + refs)))
        if value is True:
            result['recommendation'] = rule['recommendation']
            if 'example_reference_id' in rule:
                result['example_reference_id'] = rule['example_reference_id']
        elif value is None and 'next_check' in rule:
            result['next_check'] = rule['next_check']
        results.append(result)
    return results


def run(inv):
    inp=inv.input;task=inp['task'];old=restore(inv)
    # Reuse only an identical published task; configuration mismatch already clears history.
    if old and old.get('task')!=task:old={}
    goals=copy.deepcopy(inp.get('goals',old.get('goals',[])));by_id=unique(goals)
    visited,visiting=set(),set()
    def visit(gid):
        if gid not in by_id:fail('invalid_request','Unknown goal dependency')
        if gid in visiting:fail('invalid_request','Goal dependency cycle; express loop separately')
        if gid in visited:return
        visiting.add(gid)
        for dep in by_id[gid].get('depends_on',[]):visit(dep)
        visiting.remove(gid);visited.add(gid)
    for gid in by_id:visit(gid)
    requirements=[dict(id='task',text=task['text'],kind=task['kind'])]+copy.deepcopy(inp.get('constraints',[]))
    facts={};fact_refs={}
    for c in inv.upstream:
        if c['component']!='observation_context':continue
        for bucket in ('entities','relations','events'):
            for i,item in enumerate(c['content'].get(bucket,[])):
                if not item.get('retracted') and item.get('epistemic') in ('observed','derived'):
                    facts.setdefault(item['id'],[]).append(item['claim'])
                    fact_refs.setdefault(item['id'],[]).append(inv.bind_upstream(c,f'/content/{bucket}/{i}'))
    procedure=inp.get('procedure',old.get('procedure',{}))
    if set(procedure)-{'completion','loops'}:fail('invalid_request','Procedure supports completion/loops maps only')
    for key in ('completion','loops'):
        if not isinstance(procedure.get(key,{}),dict) or set(procedure.get(key,{}))-by_id.keys():fail('invalid_request','Procedure references unknown goals')
    agent_state=inp.get('agent_state',{})
    if set(agent_state)-{'goal_status','version'}:fail('invalid_request','agent_state supports version and goal_status')
    questions=[]
    for goal in goals:
        # Supplied supported status is a claim, never a completion certificate.
        status=agent_state.get('goal_status',{}).get(goal['id'],goal.get('status','pending'))
        if status=='supported':status='unknown'
        if 'when' in goal:
            result=condition(goal['when'],facts)
            status='blocked' if result is False else 'unknown' if result is None else status
        completion=procedure.get('completion',{}).get(goal['id'])
        if completion:
            result=condition(completion,facts)
            status='supported' if result is True else 'unknown' if result is None else 'pending'
            if result is True:
                def refs(expr):
                    if 'fact_id' in expr:return fact_refs.get(expr['fact_id'],[])
                    if 'not' in expr:return refs(expr['not'])
                    return [r for child in expr.get('all',expr.get('any',[])) for r in refs(child)]
                goal['evidence_refs']=list(dict.fromkeys(refs(completion)))
        if 'repeat_until' in goal:condition(goal['repeat_until'],facts)
        if goal['id'] in procedure.get('loops',{}):condition(procedure['loops'][goal['id']],facts)
        goal['status']=status
        if status=='unknown':goal['evidence_refs']=[]
    for goal in goals:
        if any(by_id[dep]['status']!='supported' for dep in goal.get('depends_on',[])) and goal['status']!='supported':goal['status']='blocked'
        if goal['status']=='unknown':questions.append('Evidence needed for goal '+goal['id'])
    focus=inv.request.get('request',{}).get('focus',[])
    active=next((g['id'] for g in goals if g['status'] in ('active','pending','attempted')),None)
    content=dict(requirements=requirements,active_focus=focus[0] if focus else active or task['text'],open_questions=questions)
    if goals:content['goals']=goals
    if 'decision_rules' in inp:
        content['decision_support'] = decision_support(inv, inp['decision_rules'])
    state=None
    if goals:
        used={r for g in goals for r in g.get('evidence_refs',[])}
        state=dict(task=task,goals=goals,procedure=procedure,references=[inv.refs[r] for r in sorted(used) if r in inv.refs])
    return inv.finish(content,state=state)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('task_context', request, **kwargs)
