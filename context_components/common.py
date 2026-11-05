"""Bounded JSON, validation, immutable resource access and host-owned state helpers."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import stat
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable
from functools import lru_cache

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


COMPONENTS = ('task_context', 'observation_context', 'spatial_context', 'interaction_contract',
              'execution_feedback', 'response_evidence', 'resource_context', 'evidence_context',
              'tool_context', 'output_contract')


class ContextError(Exception):
    def __init__(self, code, message, path=''):
        super().__init__(message)
        self.issue = dict(code=code, path=path, message=message)

    def packet(self):
        return dict(schema_version='context.error.v1', issues=[self.issue])


def fail(code, message, path=''):
    raise ContextError(code, message, path)


def pointer(parts):
    return ''.join('/' + str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def at(value, path):
    if path == '':
        return value
    if not path.startswith('/'):
        fail('invalid_request', 'Expected JSON Pointer')
    for part in path[1:].split('/'):
        import re
        if re.search(r'~(?![01])', part):
            fail('invalid_request', 'Invalid JSON Pointer escape')
        part = part.replace('~1', '/').replace('~0', '~')
        try:
            if isinstance(value, list):
                if not part.isdigit() or (part != '0' and part.startswith('0')):
                    raise KeyError(part)
                value = value[int(part)]
            else:
                value = value[part]
        except (KeyError, IndexError, TypeError):
            fail('dangling_reference', 'JSON Pointer does not resolve', path)
    return value


def loads(raw, max_bytes=8 * 1024 * 1024):
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('utf-8')
        except UnicodeError:
            fail('invalid_request', 'Expected UTF-8 JSON')
    if len(raw.encode('utf-8')) > max_bytes:
        fail('invalid_request', 'JSON byte limit exceeded')

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                fail('invalid_request', 'Duplicate JSON key: ' + key)
            out[key] = value
        return out

    def numeric(text):
        if len(text) > 1024:
            fail('invalid_request', 'Numeric representation exceeds 1024 characters')
        val = Decimal(text)
        if not val.is_finite() or abs(val.adjusted()) > 10000:
            fail('invalid_request', 'Nonfinite or excessive numeric exponent')
        return val

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=numeric,
                           parse_constant=lambda _: fail('invalid_request', 'Nonfinite JSON number'))
        check_tree(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail('invalid_request', str(exc))


def check_tree(value, depth=0):
    if depth > 64:
        fail('invalid_request', 'JSON nesting exceeds 64 levels')
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            fail('invalid_request', 'JSON keys must be strings')
        for v in value.values():
            check_tree(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            check_tree(v, depth + 1)
    elif isinstance(value, (float, Decimal)):
        if not (value.is_finite() if isinstance(value, Decimal) else math.isfinite(value)):
            fail('invalid_request', 'Nonfinite number')
    elif value is not None and not isinstance(value, (str, int, bool)):
        fail('invalid_request', 'Value is not a JSON type')


def dumps(value):
    """Encode Decimal without losing precision; IDs never depend on this encoding."""
    check_tree(value)
    def emit(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, dict):
            return '{' + ','.join(json.dumps(k, ensure_ascii=False) + ':' + emit(x) for k, x in v.items()) + '}'
        if isinstance(v, (list, tuple)):
            return '[' + ','.join(emit(x) for x in v) + ']'
        return json.dumps(v, ensure_ascii=False, allow_nan=False)
    return emit(value)


def equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return Decimal(str(a)) == Decimal(str(b))
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    return a == b


def uid(kind):
    return 'context-components:' + kind + ':' + uuid.uuid4().hex


SCHEMA_DIR = Path(__file__).parent / 'schemas'


@lru_cache(maxsize=8)
def schema(name):
    return loads((SCHEMA_DIR / name).read_bytes())


def validator(document):
    registry = Registry()
    for name in ('protocol.schema.json', 'component-payload.schema.json'):
        item = schema(name)
        registry = registry.with_resource(item['$id'], Resource.from_contents(item))
    return Draft202012Validator(document, registry=registry)


@lru_cache(maxsize=64)
def compiled_schema(definition=None, component=False):
    doc = schema('component-payload.schema.json' if component else 'protocol.schema.json')
    if definition:
        doc = {**doc, '$ref': '#/$defs/' + definition}
        doc.pop('oneOf', None)
    return validator(doc)


def validate(value, definition=None, component=None, direction='input'):
    check_tree(value)
    if component:
        value = dict(component=component, direction=direction, payload_version='1', payload=value)
    errors = list(compiled_schema(definition, bool(component)).iter_errors(value))
    if errors:
        e = errors[0]
        fail('invalid_request', e.message, pointer(e.absolute_path))


def unique(items, key='id'):
    out = {}
    for item in items:
        if item[key] in out:
            fail('identity_mismatch', 'Duplicate ' + key + ': ' + str(item[key]))
        out[item[key]] = item
    return out


def same_scope(a, b, allow_past=True):
    return all(equal(a.get(k), b.get(k)) for k in ('run_id', 'task_id', 'epoch_id', 'perspective_id')) and (
        a['turn_index'] <= b['turn_index'] if allow_past else a['turn_index'] == b['turn_index'])


def seconds(point):
    scale = {'s': 1, 'ms': 1000, 'us': 1000000, 'ns': 1000000000}
    return Decimal(str(point['value'])) / scale[point['unit']]


def elapsed(a, b):
    if (a['clock_id'], a['clock_epoch']) != (b['clock_id'], b['clock_epoch']):
        fail('clock_mismatch', 'Times use different clocks or clock epochs')
    return seconds(b) - seconds(a)


@dataclass(frozen=True)
class Resolved:
    data: bytes
    version: str


class FileResolver:
    """Explicit URI allowlist, rooted no-follow traversal, bounded stable reads."""
    def __init__(self, root, paths, max_bytes=8 * 1024 * 1024):
        self.root, self.paths, self.max_bytes = Path(root), dict(paths), max_bytes

    def __call__(self, reference):
        uri = reference['uri']
        if uri not in self.paths:
            fail('forbidden_reference', 'URI is not in the host allowlist')
        path = Path(self.paths[uri])
        if path.is_absolute() or not path.parts or any(p in ('..', '.') for p in path.parts):
            fail('forbidden_reference', 'Resource must be a relative file under the configured root')
        handles = []
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            handles.append(fd)
            for part in self.root.absolute().parts[1:]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                handles.append(fd)
            for part in path.parts[:-1]:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                handles.append(fd)
            leaf = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            handles.append(leaf)
            before = os.fstat(leaf)
            if not stat.S_ISREG(before.st_mode) or before.st_size > self.max_bytes:
                fail('forbidden_reference', 'Expected bounded regular file')
            chunks, total = [], 0
            while True:
                chunk = os.read(leaf, min(65536, self.max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk); total += len(chunk)
                if total > self.max_bytes:
                    fail('reference_changed', 'Resource grew beyond read limit')
            after = os.fstat(leaf)
            if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                fail('reference_changed', 'Resource changed while reading')
            data = b''.join(chunks)
            return Resolved(data, 'sha256:' + hashlib.sha256(data).hexdigest())
        except OSError:
            fail('reference_unavailable', 'Allowed resource cannot be opened safely')
        finally:
            for handle in reversed(handles):
                os.close(handle)


@dataclass
class Services:
    resolver: Callable | None = None
    tools: dict = field(default_factory=dict)
    max_records: int = 256
    max_calls: int = 8
    max_tool_bytes: int = 8 * 1024 * 1024
    timeout_seconds: float = 30.0
    clock: Callable = time.monotonic
    calls_used: int = 0
    tool_bytes_used: int = 0
    tokenizers: dict = field(default_factory=dict)


class Invocation:
    def __init__(self, component, request, services=None):
        validate(request, 'input')
        validate(request['input'], component=component)
        self.component, self.request = component, copy.deepcopy(request)
        self.services = services or Services()
        if type(self.services.max_records) is not int or self.services.max_records < 1:
            fail('invalid_request', 'History capacity must be a positive integer')
        if self.services.max_calls < 0 or self.services.max_tool_bytes < 0 or self.services.timeout_seconds <= 0:
            fail('invalid_request', 'Invalid host processing limits')
        self.input, self.scope = self.request['input'], self.request['scope']
        self.refs = unique(self.request.get('references', []))
        self.tools = unique(self.request.get('tools', []))
        def reference_closure(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('evidence_refs','input_refs','output_refs'):
                        if set(item)-self.refs.keys():fail('dangling_reference','Input references are undeclared')
                    elif key.endswith('reference_id') and isinstance(item,str):
                        if item not in self.refs:fail('dangling_reference','Input reference is undeclared: '+item)
                    elif key not in ('claim','candidate','schema','input_schema','output_schema','parameters','inline','value'):
                        reference_closure(item)
            elif isinstance(value,list):
                for item in value:reference_closure(item)
        reference_closure(self.input)
        self.issues, self.upstream = [], []
        self.history = self.request.get('history')
        self.state_value = None
        availability=self.request.get('request',{}).get('availability',{})
        if set(availability)-{'reference_ids','latest_time'}:
            fail('invalid_request','Availability supports explicit reference_ids and latest_time only')
        if 'reference_ids' in availability and set(self.refs)-set(availability['reference_ids']):
            fail('forbidden_reference','Request includes a resource outside its declared availability set')
        if 'latest_time' in availability:
            cutoff=availability['latest_time'];validate(cutoff,'time_point')
            for reference in self.refs.values():
                stamp=reference.get('time')
                if stamp:
                    endpoint={k:v for k,v in stamp.items() if k not in ('start','end')}
                    endpoint['value']=stamp.get('end',stamp.get('value'))
                    if elapsed(endpoint,cutoff)<0:fail('forbidden_reference','Resource exceeds the published temporal window')
        for name, extension in self.request.get('extensions', {}).items():
            if extension['required']:
                fail('unsupported_required_extension', 'Unknown required extension: ' + name)
        if self.history:
            if self.history['owner'] != component or self.history['state_schema_version'] != '1':
                fail('identity_mismatch', 'History owner or schema differs')
            if not same_scope(self.history['scope'], self.scope):
                fail('identity_mismatch', 'History is from another scope or future turn')
            if not all(equal(v, self.request.get('bindings', {}).get(k)) for k, v in self.history['bindings'].items()):
                self.issue('binding_mismatch', 'Dependent history invalidated by configuration change')
            else:
                self.state_value = copy.deepcopy(self.history['value'])
                state_schema = schema('state-values.schema.json')
                if component not in state_schema['$defs']:
                    fail('invalid_request', 'This component does not maintain state')
                errors = list(validator({**state_schema, '$ref': '#/$defs/' + component}).iter_errors(self.state_value))
                if errors:
                    fail('invalid_request', 'Invalid component state: ' + errors[0].message)
                if len(self.state_value.get('records', [])) > self.services.max_records:
                    fail('invalid_request', 'History exceeds configured record capacity')
        for item in self.request.get('upstream', []):
            context = item.get('context')
            if context is None:
                context = self.read(item['reference_id'])
                if context.get('context_id') != item['context_id'] or context.get('component') != item['component']:
                    fail('identity_mismatch', 'Referenced upstream identity differs')
            validate(context, 'output')
            validate(context['content'], component=context['component'], direction='output')
            if not same_scope(context['scope'], self.scope):
                fail('identity_mismatch', 'Upstream scope differs or is from the future')
            for key, value in context.get('bindings', {}).items():
                if key in self.request.get('bindings', {}) and not equal(value, self.request['bindings'][key]):
                    fail('binding_mismatch', 'Upstream configuration differs: ' + key)
            prior = next((c for c in self.upstream if c['context_id'] == context['context_id']), None)
            if prior and not equal(prior, context):
                fail('identity_mismatch', 'Context ID reused for different bytes')
            if not prior:
                self.upstream.append(copy.deepcopy(context))

    def issue(self, code, message, path=''):
        self.issues.append(dict(code=code, path=path, message=message))

    def read(self, rid, raw=False):
        if rid not in self.refs:
            fail('dangling_reference', 'Reference is not declared: ' + rid)
        ref = self.refs[rid]
        if 'inline' in ref:
            value = ref['inline']
            if isinstance(value, dict) and value.get('kind') == 'context_pointer':
                matches = [c for c in self.upstream if c['context_id'] == value['context_id']]
                if not matches:
                    fail('dangling_reference', 'Context pointer source is unavailable')
                return copy.deepcopy(at(matches[0], value['pointer']))
            if raw:
                fail('invalid_request', 'Exact bytes require a byte resource, not inline JSON')
            return copy.deepcopy(value)
        if not self.services.resolver:
            fail('reference_unavailable', 'No host resolver was injected')
        resolved = self.services.resolver(copy.deepcopy(ref))
        if not isinstance(resolved, Resolved) or not resolved.version:
            fail('reference_unavailable', 'Resolver must return immutable bytes and a version')
        data = resolved.data
        if not isinstance(data, bytes):
            fail('reference_unavailable', 'Resolver returned non-byte data')
        if len(data) > self.services.max_tool_bytes:
            fail('reference_unavailable', 'Resource exceeds configured byte budget')
        if 'size_bytes' in ref and len(data) != ref['size_bytes']:
            fail('reference_changed', 'Resource size differs')
        digest = 'sha256:' + hashlib.sha256(data).hexdigest()
        if 'digest' in ref and ref['digest'] != digest:
            fail('reference_changed', 'Resource digest differs')
        ref['digest'], ref['size_bytes'] = digest, len(data)
        if raw:
            return data
        loc = ref.get('locator', {})
        if ref['media_type'].split(';', 1)[0].startswith('text/') and loc.get('kind') != 'json_pointer':
            try:
                return data.decode('utf-8')
            except UnicodeError:
                fail('invalid_request', 'Published text resource must use UTF-8')
        value = loads(data)
        return at(value, loc['pointer']) if loc.get('kind') == 'json_pointer' else value

    def bind_upstream(self, context, path):
        rid = uid('ref')
        self.refs[rid] = dict(id=rid, media_type='application/json', inline=dict(
            kind='context_pointer', context_id=context['context_id'], pointer=path))
        return rid

    def call(self, tool_id, arguments, input_refs):
        if tool_id not in self.tools or tool_id not in self.services.tools:
            fail('missing_modality_processor', 'No matching explicitly injected tool: ' + tool_id)
        spec = self.tools[tool_id]
        # Trusted injection, never imports or interprets code from the JSON descriptor.
        provider = self.services.tools[tool_id]
        if not isinstance(provider, InformationTool):
            fail('invalid_request', 'Tool provider must be an InformationTool')
        if provider.effects != set(spec['effects']):
            fail('identity_mismatch', 'Injected tool effects differ from descriptor')
        for rid in input_refs:
            if rid not in self.refs:
                fail('dangling_reference', 'Tool input is not declared')
            if 'uri' in self.refs[rid]:
                self.read(rid, raw=True)
        try:
            validator(spec['input_schema']).validate(arguments)
        except Exception:
            fail('invalid_request', 'Tool arguments do not match its schema')
        size = len(dumps(arguments).encode())
        limits = spec['limits']
        if self.services.calls_used >= min(self.services.max_calls, limits.get('max_calls', self.services.max_calls)):
            fail('tool_budget_exceeded', 'Shared tool call budget exhausted')
        if self.services.tool_bytes_used + size > self.services.max_tool_bytes:
            fail('tool_budget_exceeded', 'Shared tool byte budget exhausted')
        if size > limits.get('max_input_bytes', self.services.max_tool_bytes):
            fail('tool_budget_exceeded', 'Tool input exceeds limit')
        self.services.calls_used += 1
        self.services.tool_bytes_used += size
        deadline = self.services.clock() + min(self.services.timeout_seconds, limits.get('timeout_seconds', self.services.timeout_seconds))
        try:
            result = provider.call(copy.deepcopy(arguments), [copy.deepcopy(self.refs[r]) for r in input_refs],
                                   dict(deadline=deadline, max_output_bytes=limits.get('max_output_bytes', self.services.max_tool_bytes)))
        except ContextError:
            raise
        except Exception:
            fail('tool_failed', 'Injected information processor failed')
        if self.services.clock() > deadline:
            fail('tool_timeout', 'Late tool result discarded')
        try:
            check_tree(result)
            validator(spec['output_schema']).validate(result)
        except Exception:
            fail('tool_output_invalid', 'Tool result does not match its schema')
        out_size = len(dumps(result).encode())
        if out_size > limits.get('max_output_bytes', self.services.max_tool_bytes) or self.services.tool_bytes_used + out_size > self.services.max_tool_bytes:
            fail('tool_budget_exceeded', 'Tool output exceeds shared budget')
        self.services.tool_bytes_used += out_size
        return result

    def finish(self, content, status=None, state=None):
        validate(content, component=self.component, direction='output')
        # Every evidence reference must be independently locatable in the result.
        used = set()
        def walk(value):
            if isinstance(value, dict):
                for key, val in value.items():
                    if key in ('evidence_refs', 'input_refs', 'output_refs'):
                        used.update(val)
                    elif key.endswith('reference_id') and isinstance(val, str):
                        used.add(val)
                    elif key not in ('claim','schema','input_schema','output_schema','parameters','inline','value'):
                        walk(val)
            elif isinstance(value, list):
                for v in value: walk(v)
        walk(content)
        if used - self.refs.keys():
            fail('dangling_reference', 'Output evidence reference is undeclared')
        out = dict(schema_version='context.v1', component=self.component, payload_version='1',
                   context_id=uid('result'), scope=copy.deepcopy(self.scope),
                   status=status or ('partial' if self.issues else 'ready'), content=content)
        if self.component == 'evidence_context':
            used.update(self.refs)
        if self.component == 'observation_context':
            used.update(o['reference_id'] for o in self.input.get('observations', []))
        if used:
            out['references'] = [self.refs[r] for r in sorted(used)]
        if self.request.get('bindings'):
            out['bindings'] = copy.deepcopy(self.request['bindings'])
        if self.issues:
            out['issues'] = self.issues
        if state is not None:
            state_schema = schema('state-values.schema.json')
            errors = list(validator({**state_schema, '$ref': '#/$defs/' + self.component}).iter_errors(state))
            if errors:
                fail('invalid_request', 'Invalid generated state: ' + errors[0].message)
            out['state_update'] = dict(base_state_id=self.history['state_id'] if self.history else None,
                state=dict(state_id=uid('state'), owner=self.component, state_schema_version='1',
                           scope=copy.deepcopy(self.scope), bindings=copy.deepcopy(self.request.get('bindings', {})), value=state))
        validate(out, 'output')
        budget=self.request.get('request',{}).get('budget',{})
        if len(dumps(out).encode('utf-8'))>budget.get('max_bytes',float('inf')):
            fail('context_budget_insufficient','Complete semantic result exceeds generation byte budget')
        if 'max_tokens' in budget:
            tokenizer=self.services.tokenizers.get(budget['tokenizer_id'])
            if tokenizer is None:fail('unsupported_operator','Generation tokenizer was not injected')
            if tokenizer(dumps(out))>budget['max_tokens']:fail('context_budget_insufficient','Complete semantic result exceeds generation token budget')
        return out


@dataclass(frozen=True)
class InformationTool:
    call: Callable
    effects: set

    def __post_init__(self):
        if not self.effects <= {'read_published_data', 'process_data', 'write_scratch_artifacts'}:
            fail('invalid_request', 'Only information processing tools can be injected')


def cas(current, update):
    """Pure host helper. Host must protect its slot with its own lock/transaction."""
    validate(update, 'state_update')
    if current is not None:
        validate(current, 'state')
    new = update['state']
    if current and current['state_id'] == new['state_id']:
        if not equal(current, new): fail('state_conflict', 'State ID content conflict')
        return copy.deepcopy(current)
    if (current['state_id'] if current else None) != update['base_state_id']:
        fail('state_conflict', 'State base changed; recompute against accepted history')
    if current and (current['owner'] != new['owner'] or not same_scope(current['scope'], new['scope'])):
        fail('state_conflict', 'State slot identity or turn differs')
    return copy.deepcopy(new)
