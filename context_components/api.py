import copy
from importlib import import_module

from .common import COMPONENTS, ContextError, Invocation, Services, equal, fail, same_scope, unique, validate


def build_context(component, request, *, services=None, resolver=None, dispatcher=None):
    if component not in COMPONENTS:fail('unsupported_operator','Unknown component: '+str(component))
    if services is not None and (resolver is not None or dispatcher is not None):fail('invalid_request','Use services or resolver/dispatcher')
    services=services or Services(resolver=resolver,tools=dispatcher or {})
    invocation=Invocation(component,request,services)
    # Module names come exclusively from the constant allowlist, never an input import path.
    return import_module('.components.'+component,__package__).run(invocation)


def compose(request, *, services=None):
    validate(request,'compose_input');nodes=unique(request['nodes']);order=[];active=set();done=set()
    def visit(nid):
        if nid not in nodes:fail('invalid_request','Unknown dependency node')
        if nid in active:fail('invalid_request','Composition cycle')
        if nid in done:return
        active.add(nid)
        node=nodes[nid]
        if not same_scope(node['request']['scope'],request['scope'],False):fail('identity_mismatch','Node scope differs from compose scope')
        # Validate every node before any node can call tools.
        validate(node['request'],'input');validate(node['request']['input'],component=node['component'])
        for dep in node.get('upstream_nodes',[]):visit(dep)
        active.remove(nid);done.add(nid);order.append(nid)
    for nid in nodes:visit(nid)
    services=services or Services();results={}
    for nid in order:
        node=nodes[nid];payload=copy.deepcopy(node['request'])
        try:
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
    validate(out,'composed_output');return out
