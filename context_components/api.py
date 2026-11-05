import copy
from importlib import import_module

from .common import COMPONENTS, ContextError, Invocation, Services, equal, fail, same_scope, unique, validate, schema, validator
from .task_modes import combine, declared_task, select_variant, with_kind, state_kind


def build_context(component, request, *, services=None, resolver=None, dispatcher=None):
    if component not in COMPONENTS:fail('unsupported_operator','Unknown component: '+str(component))
    if services is not None and (resolver is not None or dispatcher is not None):fail('invalid_request','Use services or resolver/dispatcher')
    services=services or Services(resolver=resolver,tools=dispatcher or {})
    invocation=Invocation(component,request,services)
    # Module names come exclusively from the constant allowlist, never an input import path.
    return import_module('.components.'+component,__package__).run(invocation)


def compose(request, *, services=None):
    validate(request,'compose_input');nodes=unique(copy.deepcopy(request['nodes']));order=[];active=set();done=set()
    def visit(nid):
        if nid not in nodes:fail('invalid_request','Unknown dependency node')
        if nid in active:fail('invalid_request','Composition cycle')
        if nid in done:return
        active.add(nid)
        node=nodes[nid]
        if not same_scope(node['request']['scope'],request['scope'],False):fail('identity_mismatch','Node scope differs from compose scope')
        # Validate every node before any node can call tools.
        validate(node['request'],'input')
        for dep in node.get('upstream_nodes',[]):visit(dep)
        active.remove(nid);done.add(nid);order.append(nid)
    for nid in nodes:visit(nid)
    services=services or Services();results={}
    kind=combine([declared_task(request.get('task')), *[declared_task(n['request']['input'].get('task')) for n in nodes.values()]])
    # Resolve external upstream declarations before executing ANY component tools.
    # The probe only applies existing scope/binding/availability and reader checks;
    # failures remain local to their node, as with ordinary composition failures.
    preflight_errors={}
    for nid,node in nodes.items():
        payload=node['request']
        history=payload.get('history')
        if history:
            try:
                if history['owner']!=node['component'] or history['state_schema_version']!='1' or not same_scope(history['scope'],payload['scope']):
                    fail('identity_mismatch','History owner, schema or scope differs')
                state_schema=schema('state-values.schema.json')
                if node['component'] not in state_schema['$defs']:
                    fail('invalid_request','This component does not maintain state')
                if all(equal(v,payload.get('bindings',{}).get(k)) for k,v in history['bindings'].items()):
                    errors=list(validator({**state_schema,'$ref':'#/$defs/'+node['component']}).iter_errors(history['value']))
                    if errors:fail('invalid_request','Invalid component state: '+errors[0].message)
                kind=combine([kind,state_kind(history)])
            except ContextError as exc:
                if exc.issue['code']=='task_kind_mismatch':raise
                preflight_errors[nid]=exc.packet();continue
        if payload.get('upstream'):
            probe=copy.deepcopy(payload);probe['input']={};probe.pop('history',None)
            probe['request']={k:v for k,v in probe.get('request',{}).items() if k not in ('task_variants','focus')}
            try:
                checked=Invocation('evidence_context',probe,services)
                payload['upstream']=[dict(context=copy.deepcopy(c)) for c in checked.upstream]
                payload['references']=list(copy.deepcopy(checked.refs).values())
                kind=combine([kind,checked.task_kind])
            except ContextError as exc:
                if exc.issue['code']=='task_kind_mismatch':raise
                preflight_errors[nid]=exc.packet()
    for node in nodes.values():
        node['request']=with_kind(node['request'],kind)
        # Validate all configured inputs, including the selected overrides, before
        # any independent node can invoke an information processor.
        select_variant(node['component'],node['request'],kind)
    for nid in order:
        node=nodes[nid];payload=copy.deepcopy(node['request'])
        try:
            if nid in preflight_errors:
                results[nid]=dict(id=nid,error=preflight_errors[nid]);continue
            for dep in node.get('upstream_nodes',[]):
                previous=results[dep]
                if 'error' in previous or previous['result']['status']=='unavailable':fail('upstream_unavailable','Required upstream node failed: '+dep)
                payload.setdefault('upstream',[]).append(dict(context=previous['result']))
            result=build_context(node['component'],payload,services=services)
            results[nid]=dict(id=nid,result=result)
        except ContextError as exc:
            results[nid]=dict(id=nid,error=exc.packet())
    slots={}
    for node in results.values():
        result=node.get('result',{});update=result.get('state_update')
        if update:
            owner=update['state']['owner']
            if owner in slots and not equal(slots[owner],update):fail('competing_state_updates','Multiple updates for the same owner/scope slot')
            slots[owner]=update
    statuses=[v.get('result',{}).get('status','unavailable') for v in results.values()]
    usable=any(s in ('ready','partial') for s in statuses)
    bad=any(s in ('partial','unavailable') for s in statuses)
    status='partial' if usable and bad else 'unavailable' if bad else 'ready' if usable else 'not_applicable'
    out=dict(schema_version='context.composed.v1',scope=request['scope'],nodes=[results[nid] for nid in nodes],status=status)
    if kind is not None:out['task']=dict(kind=kind)
    validate(out,'composed_output');return out
