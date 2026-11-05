"""Bounded revision-aware history. Completeness is explicit and never inferred."""
import copy

from .common import equal, fail, uid


def restore(inv):
    state=copy.deepcopy(inv.state_value or {})
    mapping={}
    for reference in state.get('references',[]):
        rid=reference['id']
        if rid in inv.refs and not equal(inv.refs[rid],reference):
            mapping[rid]=uid('historical-ref');reference['id']=mapping[rid]
        inv.refs[reference['id']]=reference
    def rename(value):
        if isinstance(value,dict):
            for key,v in value.items():
                if key=='evidence_refs':value[key]=[mapping.get(r,r) for r in v]
                else:rename(v)
        elif isinstance(value,list):
            for v in value:rename(v)
    rename(state)
    return state


def event_key(item,scope):
    origin=item.get('scope',scope)
    epoch=item.get('origin_epoch',origin['epoch_id'])
    if epoch!=origin['epoch_id']:fail('identity_mismatch','Event origin epoch conflicts with its source scope')
    return (item['source_namespace'],origin['run_id'],epoch,item['id'])


def merge(inv, previous, incoming, complete=True):
    records={}
    for item in previous+incoming:
        item=copy.deepcopy(item)
        if not {'source_namespace','revision'}<=item.keys():
            fail('invalid_request','Reusable events need source_namespace and revision')
        key=event_key(item,inv.scope)
        # A redelivered event without an explicit source scope keeps its original
        # arrival scope. The current invocation must not rewrite event provenance.
        original=records.get(key,{}).get('scope',inv.scope)
        item.setdefault('scope',copy.deepcopy(original));item.setdefault('origin_epoch',item['scope']['epoch_id'])
        if key in records:
            old=records[key]
            if item['revision']<old['revision']:continue
            if item['revision']==old['revision']:
                if not equal(item,old):fail('conflicting_revision','Same event revision has different content')
                continue
        records[key]=item
    items=list(records.values())
    if len(items)>inv.services.max_records:
        complete=False;items=items[-inv.services.max_records:]
        inv.issue('history_gap','Bounded event window exceeded; exact counting unavailable')
    return items,complete


def state(inv, records, **extra):
    used={r for item in records for r in item.get('evidence_refs',[])}
    if used-inv.refs.keys():fail('dangling_reference','History evidence is missing')
    return dict(records=records,references=[inv.refs[r] for r in sorted(used)],**extra)
