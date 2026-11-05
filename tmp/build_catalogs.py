"""Build static adapter catalogs from reviewed inert text; never imports benchmarks.

Maintenance tool uses sibling design evidence. Installed package contains the
generated JSON and has no dependency on this tool or on the original scripts.
"""
import ast
import hashlib
import json
from pathlib import Path
import re

MAINTENANCE=Path(__file__).resolve().parent
ROOT=MAINTENANCE.parent
DOCS=ROOT.parent/'docs'
RESEARCH=MAINTENANCE/'research'


def load(path):return json.loads(path.read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def static_dict(path):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node,ast.Assign):
            try:value=ast.literal_eval(node.value)
            except (ValueError,TypeError):continue
            if isinstance(value,dict):return value
    raise ValueError('No literal dictionary: '+str(path))


def build():
    sources={s['id']:s for s in load(DOCS/'source-lock.json')['sources']}
    coverage=load(DOCS/'coverage-matrix.json')['benchmarks']
    inventory=load(DOCS/'catalog-source-inventory.json')
    fourth=load(DOCS/'catalog-evidence-round4.json')['entries']
    catalogs={};evidence={}
    def catalog(name,ids,kind,source_paths,**extra):
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate catalog identity: '+name)
        catalogs[name]=dict(catalog_id='sha256:'+hashlib.sha256(json.dumps(ids,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),task_ids=ids,kind=kind,**extra)
        evidence[name]=[dict(path=str(p.relative_to(ROOT.parent)),sha256=digest(p)) for p in source_paths]
    libero=inventory['libero']['task_map']
    catalog('libero',[suite+':'+task for suite,tasks in libero.items() for task in tasks],'native_task_map',[DOCS/'references/review3_libero_tasks.txt'],groups=libero)
    plus=load(DOCS/'references/review4_plus_classification.txt')
    catalog('libero_plus',[suite+':'+str(v['id']) for suite,rows in plus.items() for v in rows],'suite_local_variant_catalog',[DOCS/'references/review4_plus_classification.txt'])
    labels={'Background Textures':'texture','Robot Initial States':'robot_initial_state','Camera Viewpoints':'camera','Language Instructions':'language','Sensor Noise':'sensor_noise','Objects Layout':'object_layout','Light Conditions':'light'}
    catalogs['libero_plus']['task_modes']={suite+':'+str(v['id']):labels[v['category']] for suite,rows in plus.items() for v in rows}
    pro=static_dict(RESEARCH/'pro_tasks.txt')
    # Same task string may occur twice within a native suite; preserve row identity.
    catalog('libero_pro',[suite+':'+str(i)+':'+task for suite,tasks in pro.items() for i,task in enumerate(tasks)],'native_task_map_rows',[RESEARCH/'pro_tasks.txt'],groups={k:len(v) for k,v in pro.items()})
    catalog('metaworld',inventory['metaworld']['environment_ids'],'environment_type_catalog',[DOCS/'references/review3_metaworld_registry.txt'],splits=inventory['metaworld']['explicit_splits'])
    twin=sorted(fourth['B05']['task_limits'])
    modules=set(re.findall(r'envs/([a-zA-Z0-9_]+)\.py',(RESEARCH/'robotwin_envs_html.txt').read_text()))-{'_GLOBAL_CONFIGS','__init__','_base_task','model_utils'}
    if set(twin)!=modules:raise ValueError('RoboTwin module/limit catalog differs')
    catalog('robotwin2',twin,'module_and_limit_intersection',[DOCS/'references/review4_twin_limits.txt',RESEARCH/'robotwin_envs_html.txt'])
    casa=fourth['B06']['task_names']
    catalog('robocasa365',[t for group in casa.values() for t in group],'registered_import_candidates',[DOCS/'references/review4_casa_init.txt',DOCS/'references/review4_casa_kitchen.txt'],groups=casa)
    catalogs['robocasa365']['task_modes']={t:group for group,tasks in casa.items() for t in tasks}
    dojo=load(RESEARCH/'dojo_native_inventory.json')
    dojo_ids=['sim:'+t['upstream_id'] for t in dojo['tasks']]
    real=(RESEARCH/'dojo_task_catalog.txt').read_text().split('## 真实任务',1)[1]
    embodiment=None
    for line in real.splitlines():
        if line.startswith('### '):embodiment=line[4:]
        match=re.match(r'\| \[([^]]+)\]\(https://robodojo-benchmark.com/doc/real-tasks/',line)
        if match:dojo_ids.append('real:'+embodiment+':'+match[1])
    if len(dojo_ids)!=72:raise ValueError('Expected 54 simulation and 18 real task descriptors')
    catalog('robodojo',dojo_ids,'simulation_and_embodiment_qualified_real_tasks',[RESEARCH/'dojo_native_inventory.json',RESEARCH/'dojo_task_catalog.txt'])
    catalogs['robodojo']['task_modes']={**{'sim:'+t['upstream_id']:t['dimension'].replace('-','_') for t in dojo['tasks']},**{tid:'real_world_descriptors' for tid in dojo_ids if tid.startswith('real:')}}
    cerebra=[x['path'] for x in load(RESEARCH/'cerebra_pinned_tree.txt') if re.fullmatch(r'[^/]+/case\d+',x['path'])]
    if len(cerebra)!=60:raise ValueError('Unexpected Cerebra dataset task count')
    catalog('robocerebra',cerebra,'fixed_dataset_directories',[RESEARCH/'cerebra_pinned_tree.txt'],dataset_revision='4e386b9aa266f05b199739d7b58950252244ea21')
    catalog('robomme',fourth['B09']['task_ids'],'native_resolver_task_list',[DOCS/'references/review4_robomme_resolver.txt'])
    catalogs['robomme']['task_modes']={tid:['Counting','Permanence','Reference','Imitation'][i//4] for i,tid in enumerate(fourth['B09']['task_ids'])}
    arena_ids=[];arena_sources=[]
    for path in sorted(RESEARCH.glob('arena_*environment.txt')):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                if any(isinstance(t,ast.Name) and t.id=='name' for t in targets) and isinstance(node.value,ast.Constant):
                    arena_ids.append('factory:'+node.value.value);arena_sources.append(path)
    excluded_yaml=[]
    for source in load(RESEARCH/'lookup.json'):
        if source['id'].startswith('arena_yaml_') and 'error' not in source:
            path=RESEARCH/(source['id']+'.txt')
            if not re.search(r'^env_name:',path.read_text(),re.M):
                excluded_yaml.append(dict(source_id=source['id'],reason='Shared defaults without an environment identity; not a selectable task spec'))
                continue
            arena_ids.append('yaml:'+source['url'].split('/isaaclab_arena_environments/',1)[1]);arena_sources.append(path)
    catalog('isaac_lab_arena',arena_ids,'first_party_factories_and_published_yaml_specs',arena_sources,
            external_catalog_required_for_partner_packages=True,excluded_shared_yaml=excluded_yaml)
    vla_ids=[];vla_sources=[]
    for path in sorted(RESEARCH.glob('vla_*.txt')):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node,ast.ClassDef):continue
            for dec in node.decorator_list:
                if isinstance(dec,ast.Call) and isinstance(dec.func,ast.Attribute) and dec.func.attr=='add_task' and dec.args and isinstance(dec.args[0],ast.Constant):
                    vla_ids.append(dec.args[0].value);vla_sources.append(path)
    catalog('vlabench',vla_ids,'native_task_registration_decorators',sorted(set(vla_sources)))
    catalogs['vlabench']['vlm_dimensions']=load(RESEARCH/'vlabench_dim2task.txt')
    catalogs['vlabench']['upstream_naming_difference']={'cli':'PhysicalLaw','dim2task':'PhysicsLaw','normalization':'none; preserve explicit profile spelling'}
    evidence['vlabench'].append(dict(path=str((RESEARCH/'vlabench_dim2task.txt').relative_to(ROOT.parent)),sha256=digest(RESEARCH/'vlabench_dim2task.txt')))
    profiles=[]
    for row in coverage:
        name=row['adapter'];source=sources[row['source_id']]
        profiles.append(dict(adapter=name,benchmark_revision=source['commit'],modes=row['required_modes_or_families'],catalog=catalogs[name],
            capabilities=row['required_capabilities'],negative_cases=row['negative_cases'],source_url=source['url'],
            export_schema_version='published-native.v1',verification='Configuration only; measured verification is recorded in the standalone validation-report.json'))
    target=ROOT/'context_components/adapters/profiles.json'
    target.write_text(json.dumps(dict(schema_version='context.adapter.profiles.v1',benchmarks=profiles),ensure_ascii=False,indent=2)+'\n')
    (MAINTENANCE/'catalog-evidence.json').write_text(json.dumps(dict(method='Static AST, fixed directory listings, local reviewed inventories; no upstream imports',sources=evidence,
        counts={k:len(v['task_ids']) for k,v in catalogs.items()}),ensure_ascii=False,indent=2)+'\n')
    for row in profiles:
        path=ROOT/'context_components/adapters'/(row['adapter']+'.py')
        path.write_text('"""Frozen '+row['adapter']+' published-data adapter."""\nfrom .core import adapt as _adapt\n\ndef adapt(export, *, policy, components=None):\n    return _adapt('+repr(row['adapter'])+', export, policy=policy, components=components)\n')
    print({k:len(v['task_ids']) for k,v in catalogs.items()})


if __name__=='__main__':build()
