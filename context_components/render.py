"""Provider-neutral delivery. The host, not this module, sends and acknowledges it."""
import copy
import hashlib

from .common import at, dumps, equal, fail, same_scope, uid, unique, validate
from .presentation import CONTENT_FORMATS, render_error, render_view


def check_packet(packet):
    validate(packet,'delivery')
    resources=unique(packet.get('resources',[]))
    if len(set(packet['context_ids']))!=len(packet['context_ids']):fail('invalid_delta','Duplicate context ID')
    if packet['mode']=='full':
        blocks=unique(packet['blocks'])
        for block in blocks.values():
            if set(block.get('reference_ids',[]))-resources.keys():fail('dangling_reference','Delivery block resource is missing')
        for resource in resources.values():
            if resource['source']['context_id'] not in packet['context_ids']:fail('dangling_reference','Resource source context is missing')
    return packet


def apply_delta(base,delta):
    check_packet(base);validate(delta,'delivery')
    if base['mode']!='full' or delta['mode']!='delta':fail('invalid_delta','Expected full base and delta packet')
    if delta['base_delivery_id']!=base['delivery_id']:fail('delivery_base_missing','Delta base does not match retained packet')
    if any(delta[k]!=base[k] for k in ('receiver_id','session_id')) or not same_scope(base['scope'],delta['scope']):
        fail('invalid_delta','Delivery receiver/session/world differs or turn is stale')
    blocks={b['id']:copy.deepcopy(b) for b in base['blocks']};seen=set()
    for operation in delta['operations']:
        bid=operation['id'] if operation['op']=='remove' else operation['block']['id']
        if bid in seen:fail('invalid_delta','Repeated block operation')
        seen.add(bid)
        if operation['op']=='remove':
            if bid not in blocks:fail('invalid_delta','Cannot remove a nonexistent block')
            del blocks[bid]
        else:blocks[bid]=copy.deepcopy(operation['block'])
    if len(delta['block_order'])!=len(blocks) or set(delta['block_order'])!=blocks.keys():fail('invalid_delta','Final block order is not a permutation of the result')
    out={k:copy.deepcopy(v) for k,v in delta.items() if k not in ('base_delivery_id','operations','block_order')}
    out['mode']='full';out['blocks']=[blocks[k] for k in delta['block_order']]
    return check_packet(out)


def render_context(result, delivery_request, *, sources=None, tokenizers=None):
    """Render a canonical result without modifying its data or state updates.

    content_format selects json, text_json (default), or text for agent-facing
    blocks only. Retain result for downstream components and history in all modes.
    Generated explanations are English; quoted source data is not translated.
    """
    allowed={'mode','audience','budget','retained','receiver_id','session_id','reconstructs_context','language','content_format'}
    if set(delivery_request)-allowed:fail('invalid_request','Unknown render request field')
    if delivery_request.get('mode','full') not in ('full','delta'):fail('invalid_request','Unknown delivery mode')
    if not {'receiver_id','session_id'}<=delivery_request.keys():fail('invalid_request','Render request needs receiver_id and session_id')
    content_format=delivery_request.get('content_format','text_json')
    if content_format not in CONTENT_FORMATS:fail('invalid_request','Unknown content_format; use json, text_json or text')
    if delivery_request.get('language','en')!='en':fail('invalid_request','Generated explanations are available in English (en) only')
    audience=delivery_request.get('audience',{'modalities':['text']});validate(audience,'audience')
    if result['schema_version']=='context.composed.v1':
        validate(result,'composed_output');nodes=result['nodes']
    else:
        validate(result,'output');nodes=[dict(id=result['component'],result=result)]
    available=dict(sources or {})
    available.update({n['result']['context_id']:n['result'] for n in nodes if 'result' in n})
    blocks=[];resources=[];context_ids=[]
    for node in nodes:
        if 'error' in node:
            blocks.append(dict(id=node['id']+':error',kind='text',text=render_error(node['error'],content_format),critical=True));continue
        context=node['result'];context_ids.append(context['context_id'])
        view=dict(component=context['component'],status=context['status'],content=context['content'])
        for key in ('issues','guidance'):
            if key in context:view[key]=context[key]
        blocks.append(dict(id=node['id']+':context',kind='text',text=render_view(context,view,content_format),critical=True))
        aliases=[]
        for reference in context.get('references',[]):
            ref=copy.deepcopy(reference)
            if isinstance(ref.get('inline'),dict) and ref['inline'].get('kind')=='context_pointer':
                origin=ref['inline'];source=available.get(origin['context_id'])
                if source is None:fail('dangling_reference','Render needs the source context for an upstream pointer')
                ref['inline']=dict(source_context_id=origin['context_id'],pointer=origin['pointer'],value=copy.deepcopy(at(source,origin['pointer'])))
            alias='r:'+hashlib.sha256(dumps([context['context_id'],ref['id']]).encode()).hexdigest()[:24]
            resources.append(dict(id=alias,source=dict(context_id=context['context_id'],reference_id=ref['id']),reference=ref))
            modality=ref['media_type'].split('/')[0]
            if modality in audience['modalities'] and modality in ('image','video','audio'):aliases.append(alias)
        if aliases:blocks.append(dict(id=node['id']+':media',kind='media',reference_ids=aliases,critical=True))
    packet=dict(schema_version='context.delivery.v1',delivery_id=uid('delivery'),receiver_id=delivery_request['receiver_id'],session_id=delivery_request['session_id'],
        scope=copy.deepcopy(result['scope']),mode='full',context_ids=list(dict.fromkeys(context_ids)),blocks=blocks)
    if resources:packet['resources']=resources
    check_packet(packet)
    budget=delivery_request.get('budget',{});validate(budget,'budget')
    # All retained blocks are decision-relevant; do not silently trim hard information.
    text='\n'.join(b.get('text','') for b in blocks)
    if len(dumps(packet).encode())>budget.get('max_bytes',float('inf')):fail('context_budget_insufficient','Complete required context exceeds byte budget')
    if 'max_tokens' in budget:
        tokenizer=(tokenizers or {}).get(budget['tokenizer_id'])
        if not tokenizer:fail('unsupported_operator','Requested tokenizer was not injected')
        if tokenizer(text)>budget['max_tokens']:fail('context_budget_insufficient','Required text exceeds token budget')
    retained=delivery_request.get('retained')
    if delivery_request.get('mode','full')=='delta' and retained and delivery_request.get('reconstructs_context') is True:
        base=retained['base_packet']
        if retained['base_delivery_id']!=base['delivery_id'] or any(retained.get(k)!=packet[k] for k in ('receiver_id','session_id')):
            return packet
        if not same_scope(base['scope'],packet['scope']):return packet
        check_packet(base)
        old={b['id']:b for b in base['blocks']};new={b['id']:b for b in blocks}
        operations=[dict(op='remove',id=k) for k in old if k not in new]
        operations.extend(dict(op='upsert',block=b) for k,b in new.items() if k not in old or not equal(old[k],b))
        delta={k:v for k,v in packet.items() if k!='blocks'}
        delta.update(mode='delta',base_delivery_id=base['delivery_id'],operations=operations,block_order=[b['id'] for b in blocks])
        apply_delta(base,delta)
        return delta
    return packet


class ReceiverState:
    """Optional in-memory host helper; submission order and explicit acceptance are separate."""
    def __init__(self):
        self.latest_request=-1;self.accepted_order=-1;self.packet=None;self.identities={}

    def submitted(self,order):
        if type(order) is not int or order<0:fail('invalid_request','Host request order must be a nonnegative integer')
        if order<=self.latest_request:fail('stale_delivery','Request order must increase')
        self.latest_request=order

    def accept(self,order,packet):
        if order!=self.latest_request:fail('stale_delivery','Result belongs to an older submitted request')
        key=packet['delivery_id']
        if key in self.identities and not equal(self.identities[key],packet):fail('invalid_delta','Delivery ID reused with different content')
        if order==self.accepted_order:
            if key not in self.identities:fail('stale_delivery','A different delivery was already accepted for this request')
            return copy.deepcopy(self.packet)
        full=apply_delta(self.packet,packet) if packet['mode']=='delta' and self.packet else check_packet(packet)
        if full['mode']!='full':fail('delivery_base_missing','No accepted base')
        self.packet=copy.deepcopy(full);self.identities[key]=copy.deepcopy(packet);self.accepted_order=order
        return copy.deepcopy(full)
