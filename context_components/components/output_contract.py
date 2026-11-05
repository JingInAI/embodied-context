from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from ..common import ContextError, at, equal, fail, loads, pointer


def run(inv):
    inp=inv.input;contract=inp['contract']
    allowed={'schema','schema_reference_id','version','formats','rules'}
    if set(contract)-allowed:fail('invalid_request','Unknown output contract field')
    if 'schema' in contract and 'schema_reference_id' in contract:fail('invalid_request','Provide schema or schema_reference_id, not both')
    doc=contract.get('schema')
    if 'schema_reference_id' in contract:doc=inv.read(contract['schema_reference_id'])
    requirements=[dict(id='delivery',contract=inp['delivery'])]
    if doc is not None:requirements.append(dict(id='json_schema',schema=doc))
    requirements.extend(contract.get('rules',[]))
    content=dict(requirements=requirements)
    if 'candidate' not in inp:return inv.finish(content)
    candidate=inp['candidate'];checks=[]
    if doc is not None:
        status='passed';message='Declared structural rules evaluated; annotations do not modify the candidate'
        try:
            if isinstance(doc, dict) and doc.get('$schema','https://json-schema.org/draft/2020-12/schema') not in (
                'https://json-schema.org/draft/2020-12/schema','https://json-schema.org/draft/2020-12/schema#'):
                fail('unsupported_operator','Unsupported JSON Schema dialect')
            formats=set(contract.get('formats',[]));checker=FormatChecker()
            if formats-set(checker.checkers):fail('unsupported_operator','Unknown requested format checker')
            known=set(Draft202012Validator.VALIDATORS)|{'$schema','$id','$defs','$anchor','$comment','$dynamicAnchor','title','description','default','examples','readOnly','writeOnly','deprecated','format','contentEncoding','contentMediaType','contentSchema'}
            def inspect(schema):
                if isinstance(schema,bool):return
                if not isinstance(schema,dict):fail('invalid_request','Invalid subschema')
                if set(schema)-known:fail('unsupported_operator','Unrecognized schema keyword')
                if 'format' in schema and schema['format'] not in formats:fail('unsupported_operator','Format assertion was not enabled')
                for k in ('properties','patternProperties','$defs','dependentSchemas'):
                    for child in schema.get(k,{}).values():inspect(child)
                for k in ('allOf','anyOf','oneOf','prefixItems'):
                    for child in schema.get(k,[]):inspect(child)
                for k in ('items','contains','additionalProperties','unevaluatedProperties','unevaluatedItems','not','if','then','else','propertyNames'):
                    if k in schema:inspect(schema[k])
            inspect(doc);Draft202012Validator.check_schema(doc)
            registry=Registry()
            for rid,ref in inv.refs.items():
                if ref.get('media_type')=='application/schema+json':
                    sub=inv.read(rid)
                    if '$id' in sub:registry=registry.with_resource(sub['$id'],Resource.from_contents(sub))
            errors=list(Draft202012Validator(doc,registry=registry,format_checker=FormatChecker(formats=formats)).iter_errors(candidate))
            if errors:
                checks.extend(dict(rule_id='json_schema',status='failed',path=pointer(e.absolute_path),message=e.message) for e in errors)
            else:checks.append(dict(rule_id='json_schema',status=status,message=message))
        except Exception as exc:
            # No network retrieval and no permissive successful fallback.
            checks.append(dict(rule_id='json_schema',status='not_evaluated',message=str(exc)))
    for rule in contract.get('rules',[]):
        if not {'id','kind'}<=rule.keys():fail('invalid_request','Output rule needs id and kind')
        kind=rule['kind'];status='not_evaluated';message='No executable checker for this rule'
        if kind=='parsed_value_equal':
            actual=at(candidate,rule.get('path',''));status='passed' if equal(actual,rule['value']) else 'failed';message='Exact structural comparison'
        elif kind=='exact_text':
            a=inv.read(rule['candidate_reference_id'],raw=True);b=inv.read(rule['expected_reference_id'],raw=True)
            status='passed' if a==b else 'failed';message='Exact resource byte comparison'
        checks.append(dict(rule_id=rule['id'],status=status,path=rule.get('path',''),message=message))
    if inp.get('validation_report'):
        checks.append(dict(rule_id='external_report',status='not_evaluated',message='External report is not executed or trusted as candidate validation'))
    content['checks']=checks
    return inv.finish(content)


def build_context(request, **kwargs):
    from ..api import build_context as build
    return build('output_contract', request, **kwargs)
