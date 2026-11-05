from ..common import fail


def run(inv):
    focus=inv.request.get('request',{}).get('focus',[])
    capabilities=[{k:t[k] for k in ('id','purpose','input_schema','output_schema','effects','limits')} for t in inv.tools.values() if not focus or t['id'] in focus]
    content=dict(capabilities=capabilities)
    calls=inv.input.get('calls',[])
    for call in calls:
        if not {'call_id','tool_id','status','version','input_refs'}<=call.keys():
            fail('invalid_request','Tool call records require identity, version, status and bound inputs')
        if any(r not in inv.refs for r in call['input_refs']):fail('dangling_reference','Tool call input is undeclared')
    if calls:content['calls']=calls
    return inv.finish(content)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('tool_context', request, **kwargs)
