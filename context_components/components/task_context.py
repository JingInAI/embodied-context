import copy

from ..common import equal, fail, unique
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
    fail('invalid_request','Condition must be all/any/not or fact_id+equals')


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
    state=None
    if goals:
        used={r for g in goals for r in g.get('evidence_refs',[])}
        state=dict(task=task,goals=goals,procedure=procedure,references=[inv.refs[r] for r in sorted(used) if r in inv.refs])
    return inv.finish(content,state=state)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('task_context', request, **kwargs)
