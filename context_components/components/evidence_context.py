from ..common import ContextError


def run(inv):
    entries=[]
    requested=inv.input.get('queries',[])
    for ref in inv.refs.values():
        row=dict(reference_id=ref['id'],media_type=ref['media_type'],status='registered')
        if ref.get('locator'):row['locator']=ref['locator']
        if any(q.get('reference_id')==ref['id'] and q.get('kind')=='readability' for q in requested):
            try:
                inv.read(ref['id'],raw='uri' in ref);row['status']='read_verified'
            except ContextError as exc:
                if exc.issue['code'] in ('forbidden_reference','reference_changed'):raise
                inv.issues.append(exc.issue);row['status']='unavailable'
        entries.append(row)
    return inv.finish(dict(entries=entries))


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('evidence_context', request, **kwargs)
