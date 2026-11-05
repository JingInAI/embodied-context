"""Explicit task modes and caller-owned input variants; no task-name heuristics."""
import copy

from .common import fail, validate

KINDS = ('execution', 'reasoning', 'hybrid')

# Canonical recommendations describe each component's role, not new facts.
PURPOSES = {
    'task_context': {
        'execution': 'Organize work around the required environmental outcome and its completion evidence.',
        'reasoning': 'Organize the answer around claims, supporting evidence, and unresolved questions.',
        'hybrid': 'Track the required environmental outcome and the evidence-supported answer separately.',
    },
    'observation_context': {
        'execution': 'Use relevant observations to check the current situation and prerequisites for the next operation.',
        'reasoning': 'Use observations and event history to support claims about the supplied scene or sequence.',
        'hybrid': 'Use observations both to check operational progress and to support the required explanation.',
    },
    'spatial_context': {
        'execution': 'Use requested geometry to assess the spatial prerequisites of a proposed operation.',
        'reasoning': 'Use requested geometry to support spatial comparisons and explanations, without implying an action.',
        'hybrid': 'Use applicable spatial results for both operational checks and evidence-supported spatial explanations.',
    },
    'interaction_contract': {
        'execution': 'Interpret the declared operations before forming a request through the existing host interface.',
        'reasoning': 'Interpret declared interfaces or historical commands as evidence relevant to the question; their presence does not request execution.',
        'hybrid': 'Distinguish interfaces for environmental operations from interfaces for the required answer.',
    },
    'execution_feedback': {
        'execution': 'Use confirmed execution and partial effects to decide what work remains and what needs checking.',
        'reasoning': 'Use historical execution records to analyze what happened; a failure record does not request a retry.',
        'hybrid': 'Use execution evidence both to update remaining work and to explain the observed outcome.',
    },
    'response_evidence': {
        'execution': 'Assess supplied candidates using local measured response evidence before relying on their predicted effects.',
        'reasoning': 'Use local response evidence to analyze input-response associations without prescribing new controls.',
        'hybrid': 'Keep candidate response estimates separate from the measured evidence used to explain outcomes.',
    },
    'resource_context': {
        'execution': 'Allocate proposed work against the explicitly supplied execution resources and limits.',
        'reasoning': 'Budget evidence processing or answer preparation using declared resources; execution costs may instead be historical evidence.',
        'hybrid': 'Account for both environmental work and answer preparation where their costs are supplied, without counting shared costs twice.',
    },
    'evidence_context': {
        'execution': 'Locate sources needed for the next operational decision and its outcome check.',
        'reasoning': 'Locate sources that support or challenge the claims needed for the answer.',
        'hybrid': 'Reuse applicable sources across operational checks and explanation while preserving their provenance.',
    },
    'tool_context': {
        'execution': 'Select information tools that resolve uncertainty relevant to the next operational decision.',
        'reasoning': 'Select information tools for retrieval, analysis, or checking the evidence needed for an answer.',
        'hybrid': 'Select information tools for both operational uncertainty and answer support, reusing results only when their inputs still apply.',
    },
    'output_contract': {
        'execution': 'Check the explicitly requested operation payload or execution report without assuming either format.',
        'reasoning': 'Check the declared answer form without adding actuator fields or an execution request.',
        'hybrid': 'Check the declared combined or staged output; do not invent a wrapper joining operations and answers.',
    },
}


def combine(kinds):
    values = set()
    for kind in kinds:
        if kind is None:
            continue
        if not isinstance(kind, str) or kind not in KINDS:
            fail('invalid_request', 'Task kind must be execution, reasoning or hybrid', '/input/task/kind')
        values.add(kind)
    if len(values) > 1:
        fail('task_kind_mismatch', 'Explicit task kinds disagree: ' + ', '.join(sorted(values)))
    return next(iter(values), None)


def declared_task(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        fail('invalid_request', 'Task declaration must be an object', '/input/task')
    return value.get('kind')


def state_kind(state):
    if not state:
        return None
    kinds = [declared_task(state.get('task'))]
    if state.get('owner') == 'task_context':
        kinds.append(declared_task(state.get('value', {}).get('task')))
    return combine(kinds)


def context_kind(context):
    kinds = [declared_task(context.get('task'))]
    # Older task results carry an explicit kind in their requirement, not metadata.
    if context.get('component') == 'task_context':
        kinds.extend(r.get('kind') for r in context.get('content', {}).get('requirements', [])
                     if r.get('id') == 'task')
    if context.get('state_update'):
        kinds.append(state_kind(context['state_update']['state']))
    return combine(kinds)


def request_kind(request):
    kinds = [declared_task(request['input'].get('task')), state_kind(request.get('history'))]
    kinds.extend(context_kind(item['context']) for item in request.get('upstream', []) if 'context' in item)
    return combine(kinds)


def with_kind(request, kind):
    result = copy.deepcopy(request)
    kind = combine([kind, declared_task(result['input'].get('task'))])
    if kind is not None:
        task = result['input'].setdefault('task', {})
        if not isinstance(task, dict):
            fail('invalid_request', 'Task declaration must be an object', '/input/task')
        task['kind'] = kind
    return result


def select_variant(component, request, kind):
    """Shallow replacement of declared input fields, never data interpretation.

    Validate base and every configured variant before any component tool can run.
    Lists and nested objects replace their base field in full; hybrid has its own
    explicit variant and is never an automatic union of execution and reasoning.
    """
    result = with_kind(request, kind)
    options = result.get('request', {})
    variants = options.get('task_variants', {})
    validate(result['input'], component=component)
    for variant in variants.values():
        candidate = {**result['input'], **copy.deepcopy(variant.get('input', {}))}
        validate(candidate, component=component)
    if variants and kind is None:
        fail('invalid_request', 'task_variants requires an explicit or inherited task kind', '/request/task_variants')
    selected = variants.get(kind, {})
    result['input'].update(copy.deepcopy(selected.get('input', {})))
    if 'focus' in selected:
        options['focus'] = copy.deepcopy(selected['focus'])
    return result


def recommendation(component, kind):
    return dict(id='task_kind_usage', kind='recommendation', text=PURPOSES[component][kind])
