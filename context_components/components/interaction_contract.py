from ..common import unique


def run(inv):
    unique(inv.input['operations'])
    # Native normalization, ordering and grouping are retained, never inferred from shape.
    return inv.finish({k:v for k,v in inv.input.items() if k in ('operations','control_groups','execution_semantics')})


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('interaction_contract', request, **kwargs)
