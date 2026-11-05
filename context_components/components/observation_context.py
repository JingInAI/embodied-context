import copy

from ..common import ContextError, fail, unique, validate, same_scope
from ..memory import merge,restore,state,event_key


def run(inv):
    old=restore(inv)
    features=copy.deepcopy(inv.input.get('features',[]))
    events=copy.deepcopy(inv.input.get('events',[]))
    unknown=[]
    observations=inv.input.get('observations',[]);unique(observations)
    tools=inv.input.get('extractors',[])
    for obs in observations:
        if obs['reference_id'] not in inv.refs:fail('dangling_reference','Observation reference is missing')
        origin=inv.refs[obs['reference_id']].get('scope')
        if obs.get('role','observation')=='observation' and origin and not same_scope(origin,inv.scope):
            fail('identity_mismatch','Live observation resource belongs to another world or perspective')
        if obs.get('quality') in ('padded','invalid'):continue
        if tools:
            for tool in tools:
                try:
                    result=inv.call(tool,dict(observation=obs,focus=inv.request.get('request',{}).get('focus',[])),[obs['reference_id']])
                    if not isinstance(result,dict) or set(result)-{'features','events'}:
                        fail('tool_output_invalid','Extractor must return features/events')
                    validate(result,component='observation_context')
                    for claim in result.get('features',[])+result.get('events',[]):
                        if claim['epistemic']!='estimated':fail('tool_output_invalid','Perception tool claims must be estimated')
                    if obs.get('role','observation')!='observation':
                        for claim in result.get('features',[])+result.get('events',[]):
                            claim=copy.deepcopy(claim)
                            claim['claim']=dict(role=obs['role'],description=claim['claim'])
                            features.append(claim)
                    else:
                        features.extend(result.get('features',[]));events.extend(result.get('events',[]))
                except ContextError as exc:
                    if exc.issue['code'] in ('forbidden_reference','reference_changed','identity_mismatch'):raise
                    inv.issues.append(exc.issue);unknown.append(obs['id']+': '+exc.issue['code'])
        elif obs['modality']=='text':
            text=inv.read(obs['reference_id'])
            if isinstance(text,str):
                features.append(dict(id=obs['id'],claim=text,epistemic='observed',evidence_refs=[obs['reference_id']]))
            else:unknown.append(obs['id']+': text reference does not contain text')
        else:
            unknown.append(obs['id']+': media registered; no semantic processor requested')
            inv.issue('missing_modality_processor','No semantic processor for '+obs['modality'])
    # Stable events support cross-round revisions. Ephemeral features stay in this request.
    persistent=events+[f for f in features if {'source_namespace','revision'}<=f.keys()]
    records,complete=merge(inv,old.get('records',[]),persistent,old.get('complete_set',True))
    event_keys={event_key(e,inv.scope) for e in events}
    old_event_keys={tuple(k) for k in old.get('event_keys',[])}
    all_event_keys=event_keys|old_event_keys
    active=[r for r in records if not r.get('retracted')]
    out_events=[r for r in active if event_key(r,inv.scope) in all_event_keys]
    out_features=[f for f in features if not {'source_namespace','revision'}<=f.keys()]+[
        r for r in active if event_key(r,inv.scope) not in all_event_keys]
    # Preserve explicit retractions in context so downstream facts cannot remain supported.
    retracted=[r for r in records if r.get('retracted')]
    content=dict(entities=out_features,events=out_events+retracted)
    if unknown:content['unknowns']=unknown
    focus=inv.request.get('request',{}).get('focus',[])
    if events or any('count' in x for x in focus):
        content.update(count_status='exact' if complete else 'incomplete',coverage=dict(
            domain='received_event_set',unique_active_events=len(out_events),complete_set=complete,
            actual_world_stream_complete=False))
    retained_keys={event_key(r,inv.scope) for r in records}
    update=state(inv,records,complete_set=complete,event_keys=[list(k) for k in sorted(all_event_keys & retained_keys)]) if persistent or old else None
    status='unavailable' if inv.issues and not active and not out_features else None
    return inv.finish(content,status=status,state=update)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('observation_context', request, **kwargs)
