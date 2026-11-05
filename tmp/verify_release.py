"""Run offline implementation validation and write an evidence-bound report."""
import ast
from datetime import datetime,timezone
import hashlib
import io
import json
import platform
from pathlib import Path
import sys
import time
import unittest

MAINTENANCE=Path(__file__).resolve().parent
ROOT=MAINTENANCE.parent
sys.path[:0]=[str(ROOT),str(MAINTENANCE/'tests')]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from context_components.adapters.core import profiles
    from context_components.common import schema,validator,loads,dumps
    from context_components import build_context
    from jsonschema import Draft202012Validator
    code_files=sorted([*ROOT.glob('context_components/**/*.py'),*ROOT.glob('context_components/**/*.json'),*MAINTENANCE.glob('tests/*.py'),*MAINTENANCE.glob('examples/*.json')])
    hashes={str(p.relative_to(ROOT)):sha(p) for p in code_files}
    implementation_digest=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    issues=[]
    for p in ROOT.glob('**/*.py'):
        if '__pycache__' not in p.parts:ast.parse(p.read_text(),filename=str(p),feature_version=(3,10))
    for path in (ROOT/'context_components/schemas').glob('*.json'):Draft202012Validator.check_schema(loads(path.read_bytes()))
    baseline=json.loads((ROOT.parent/'docs/scripts-baseline.json').read_text())['files']
    changed=[x['path'] for x in baseline if not (ROOT.parent/x['path']).is_file() or sha(ROOT.parent/x['path'])!=x['sha256']]
    expected={x['path'] for x in baseline}
    original_files=[p for p in (ROOT.parent/'scripts').rglob('*') if p.is_file()]
    repository_metadata=[str(p.relative_to(ROOT.parent)) for p in original_files if p.relative_to(ROOT.parent/'scripts').parts[0]=='.git']
    actual={str(p.relative_to(ROOT.parent)) for p in original_files}-set(repository_metadata)
    if changed or actual!=expected:issues.append('Original scripts baseline changed')
    catalog=json.loads((MAINTENANCE/'catalog-evidence.json').read_text())
    for items in catalog['sources'].values():
        for item in items:
            path=ROOT.parent/item['path']
            if not path.exists() or sha(path)!=item['sha256']:issues.append('Catalog evidence mismatch: '+item['path'])
    research=json.loads((MAINTENANCE/'research/lookup.json').read_text())
    for source in research:
        if 'error' in source:continue
        path=MAINTENANCE/'research'/(source['id']+'.txt')
        if not path.is_file() or sha(path)!=source['sha256'] or path.stat().st_size!=source['bytes']:issues.append('Research snapshot mismatch: '+source['id'])
    stream=io.StringIO();suite=unittest.defaultTestLoader.discover(str(MAINTENANCE/'tests'))
    started=time.perf_counter();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite);duration=time.perf_counter()-started
    if not result.wasSuccessful():issues.append('Implementation test failures')
    if any(sha(ROOT/name)!=value for name,value in hashes.items()):issues.append('Implementation changed while verification was running')
    examples=json.loads((MAINTENANCE/'examples/protocol-examples.json').read_text())['examples'];measurements=[]
    for ex in examples:
        durations=[];out=None
        for _ in range(5):
            start=time.perf_counter();out=build_context(ex['component'],ex['input']);durations.append((time.perf_counter()-start)*1000)
        from context_components.render import render_context
        packet=render_context(out,dict(receiver_id='measurement',session_id='offline'))
        measurements.append(dict(case=ex['id'],component=ex['component'],canonical_bytes=len(dumps(out).encode()),
                                 delivered_text_bytes=sum(len(b.get('text','').encode()) for b in packet['blocks']),
                                 duration_samples_ms=durations,measurement='5 warm samples; no claim about end-to-end real model cost'))
    report_path=MAINTENANCE/'validation-report.json'
    old=json.loads(report_path.read_text()) if report_path.exists() else {}
    environments=old.get('environments',{}) if old.get('implementation_digest')==implementation_digest else {}
    envkey='python-'+platform.python_version()
    environments[envkey]=dict(status='passed' if not issues else 'failed',tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                             duration_seconds=duration,checked_at_utc=datetime.now(timezone.utc).isoformat(),issues=issues)
    log=MAINTENANCE/('validation-'+envkey+'.log');log.write_text(stream.getvalue())
    mapped=[]
    for definition in profiles():
        mapped.append(dict(benchmark=definition['adapter'],benchmark_revision=definition['benchmark_revision'],catalog_id=definition['catalog']['catalog_id'],
                           catalog_kind=definition['catalog']['kind'],catalog_identities=len(definition['catalog']['task_ids']),
                           modes=definition['modes'],mapped=not issues,contract_tested=not issues,replay_tested=False,runtime_tested=False,
                           evidence_kind='synthetic exported-data conversion and frozen static catalog validation'))
    python_310='not_run'
    python_310_runs=[value for key,value in environments.items() if key.startswith('python-3.10.')]
    if python_310_runs:
        python_310='passed' if all(value.get('status')=='passed' for value in python_310_runs) else 'failed'
    limitations=['No model, GPU, simulator, robot or backend execution','All adapter behavioral inputs are synthetic published exports; no replay-tested claim',
                 'Directory kinds are not equivalent episode/task counts','Host owns permissions, tool process supervision, state storage and actual message delivery',
                 'No task-success improvement or token-reduction percentage has been measured']
    if python_310 == 'not_run':
        limitations.insert(4,'Python 3.10 was not available for execution; syntax/dependencies target 3.10+')
    report=dict(schema_version='context.implementation.validation.v1',status='passed' if not issues else 'failed',implementation_digest=implementation_digest,
        environments=environments,python_310=python_310,original_scripts=dict(files=len(baseline),changed=changed,added=sorted(actual-expected),unchanged=not changed and actual==expected,excluded_repository_metadata=sorted(repository_metadata)),
        benchmark_coverage=mapped,catalog_total=sum(catalog['counts'].values()),source_checks=dict(catalog_evidence='passed' if not issues else 'see_issues',successful_research_snapshots=sum('error' not in s for s in research)),
        synthetic_measurements=measurements,source_hashes=hashes,
        limitations=limitations)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],python=platform.python_version(),tests=result.testsRun,catalog_total=report['catalog_total'],issues=issues),ensure_ascii=False))
    if issues:print(stream.getvalue())
    return bool(issues)


if __name__=='__main__':raise SystemExit(main())
