from decimal import Decimal, ROUND_FLOOR

from ..common import ContextError, elapsed, fail, unique


def run(inv):
    inp=inv.input; unique(inp['resources']); balances=[]; unknown=[]
    for resource in inp['resources']:
        row=dict(resource)
        if 'deadline' in row:
            if 'now' not in inp:
                unknown.append(resource['id']+': now not provided')
            else:
                try:
                    remaining=elapsed(inp['now'],resource['deadline'])
                    row['remaining']=max(Decimal(0),remaining);row['unit']='s'
                    row['expired']=remaining<0
                except ContextError as exc:
                    inv.issues.append(exc.issue);unknown.append(resource['id']+': incomparable clock')
        balances.append(row)
    content=dict(balances=balances)
    if unknown: content['unknowns']=unknown
    if 'cost_model' in inp:
        model=inp['cost_model']
        if set(model)-{'per_item','version'} or 'per_item' not in model:
            fail('invalid_request','cost_model requires version and per_item resource costs')
        costs=model['per_item']; capacities={}
        for row in balances:
            if row['id'] not in costs or 'remaining' not in row:continue
            cost=costs[row['id']]
            if set(cost)!= {'value','unit'} or cost['unit']!=row['unit']:
                fail('invalid_request','Cost and resource units must match')
            value=Decimal(str(cost['value']))
            if isinstance(cost['value'],bool) or value<=0:fail('invalid_request','Per-item cost must be positive')
            capacities[row['id']]=int((Decimal(str(row['remaining']))/value).to_integral_value(rounding=ROUND_FLOOR))
        if capacities:content['supported_work']=dict(per_resource=capacities,joint_items=min(capacities.values()))
        if 'workload' in inp:
            workload=inp['workload']
            if set(workload)!={'items'} or isinstance(workload['items'],bool) or not isinstance(workload['items'],int) or workload['items']<0:
                fail('invalid_request','workload requires nonnegative integer items')
            content['shortfalls']=[dict(resource_id=k,items=workload['items']-v) for k,v in capacities.items() if v<workload['items']]
    if 'execution_window' in inp:
        window=inp['execution_window']
        if set(window)-{'max_items','minimum_items','interruptible'} or not {'max_items','interruptible'}<=window.keys():
            fail('invalid_request','execution_window needs max_items, interruptible and optional minimum_items')
        maximum=window['max_items'];minimum=window.get('minimum_items',1)
        if type(maximum) is not int or type(minimum) is not int or not 0<=minimum<=maximum or type(window['interruptible']) is not bool:
            fail('invalid_request','Invalid execution window bounds')
        content.setdefault('limits',[]).append(dict(kind='external_execution_window',**window))
        if 'supported_work' in content:
            supported=min(maximum,content['supported_work']['joint_items'])
            content['supported_work']['window_items']=supported
            if supported<minimum:content.setdefault('shortfalls',[]).append(dict(kind='minimum_window',items=minimum-supported))
        else:content.setdefault('unknowns',[]).append('Execution window is a limit; no cost evidence proves it affordable')
    return inv.finish(content)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('resource_context', request, **kwargs)
