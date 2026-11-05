import copy
from decimal import Decimal

from ..common import equal, fail, unique, same_scope, elapsed
from ..memory import merge,restore,state


def run(inv):
    executions=copy.deepcopy(inv.input['executions']);unique(executions)
    old=restore(inv)
    incoming=[]
    for execution in executions:
        incoming.append(dict(id=execution['id'],source_namespace=execution.get('source_namespace','published-execution'),
                             revision=execution.get('revision',0),execution=execution,evidence_refs=execution.get('evidence_refs',[]),
                             **{k:execution[k] for k in ('scope','origin_epoch','retracted') if k in execution}))
    records,complete=merge(inv,old.get('records',[]),incoming,old.get('complete_set',True))
    executions=[r['execution'] for r in records if not r.get('retracted')]
    segments=[];changes=[];failures=[];unknown=[]
    for item in executions:
        receipt={}
        for rid in item.get('evidence_refs',[]):
            value=inv.read(rid)
            if isinstance(value,dict) and value.get('id')==item['id']:
                if receipt and not equal(receipt,value):fail('conflicting_revision','Execution receipts disagree')
                receipt=value
        row=dict(id=item['id'],status=item['status'],evidence_refs=item.get('evidence_refs',[]))
        for key in ('entity_id','request_id','started_at','ended_at','termination'):
            if key in item:row[key]=item[key]
        counts={}
        for phase in ('submitted','accepted','executed'):
            source=item.get(phase,{})
            if set(source)-{'items','evidence_refs'}:fail('invalid_request','Execution phase requires items and evidence_refs')
            count=source.get('items',receipt.get(phase+'_items'))
            if count is not None:
                if isinstance(count,bool) or not isinstance(count,int) or count<0:fail('invalid_request','Execution count must be a nonnegative integer')
                counts[phase]=count;row[phase+'_items']=count
        if any(counts[b]>counts[a] for a,b in [('submitted','accepted'),('accepted','executed'),('submitted','executed')] if a in counts and b in counts):
            fail('invalid_request','Executed/accepted count exceeds predecessor count')
        if 'executed' not in counts:unknown.append(item['id']+': actual execution count unknown')
        if receipt.get('termination'):row.setdefault('termination',receipt['termination'])
        if item['status'] in ('failed','interrupted','cancelled'):failures.append(dict(execution_id=item['id'],status=item['status']))
        before=inv.read(item['before']) if 'before' in item else receipt.get('before')
        after=inv.read(item['after']) if 'after' in item else receipt.get('after')
        if isinstance(before,dict) and isinstance(after,dict):
            required={'scope','entity_id','time','values'}
            if not required<=before.keys() or not required<=after.keys():
                unknown.append(item['id']+': state difference needs named values, units, entity, scope and time')
            elif not same_scope(before['scope'],after['scope']) or before['entity_id']!=after['entity_id'] or elapsed(before['time'],after['time'])<0:
                inv.issue('identity_mismatch','Before/after measurement frames, entity or time do not align')
            else:
                for key in before['values'].keys()&after['values'].keys():
                    a,b=before['values'][key],after['values'][key]
                    if not isinstance(a,dict) or not isinstance(b,dict) or not {'value','unit'}<=a.keys() or not {'value','unit'}<=b.keys():
                        fail('invalid_request','Named measurements require value and unit')
                    if a['unit']!=b['unit']:fail('invalid_request','Measurement units differ')
                    if any(isinstance(x['value'],bool) or not isinstance(x['value'],(int,float,Decimal)) for x in (a,b)):continue
                    changes.append(dict(execution_id=item['id'],variable=key,delta=b['value']-a['value'],unit=a['unit'],evidence_refs=item.get('evidence_refs',[])))
        segments.append(row)
    content=dict(segments=segments)
    if changes:content['changes']=changes
    if failures:content['failures']=failures
    if unknown:content['unknowns']=unknown
    return inv.finish(content,state=state(inv,records,complete_set=complete) if records or old else None)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('execution_feedback', request, **kwargs)
