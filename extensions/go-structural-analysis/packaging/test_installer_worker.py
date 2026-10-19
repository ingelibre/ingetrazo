"""Run using the installer runtime against the isolated installed plugin."""
import json
from pathlib import Path
import sys
root=Path(sys.argv[1]); sys.path.insert(0,str(root))
from examples import CATALOG,example
from client import analyze
import types
package=types.ModuleType('installer_examples'); package.__path__=[str(root)]; sys.modules['installer_examples']=package
from installer_examples.examples3d import CATALOG3D,example3d
checks=[]
for key,title,_ in CATALOG+CATALOG3D:
    try:
        result=analyze(example3d(key) if key.startswith('3d_') else example(key))
        passed=not (key.startswith('unstable') or key=='3d_unstable') and result['version']=='3.2.0'
        checks.append({'key':key,'status':'Passed' if passed else 'Failed','expected':'success'})
    except RuntimeError as exc:
        passed=(key.startswith('unstable') or key=='3d_unstable') and ('unstable' in str(exc).lower() or 'singular' in str(exc).lower())
        checks.append({'key':key,'status':'Passed' if passed else 'Failed','expected':'unstable rejection','message':str(exc)})
from thai_code import apply_manager
from model3d import cantilever3d
from model import benchmark
for dimension in (2,3):
    for method in ('ASD','LRFD'):
        d=cantilever3d() if dimension==3 else benchmark()
        if dimension==2: d['cases']=['DL','LL']; d['distributed_loads'][0]['case']='DL'
        config=dict(method=method,bindings={'D':['DL'],'L':['LL']},enabled=['TH2566-'+method+'-01'],custom={})
        try:
            r=analyze(apply_manager(d,config)); passed=r.get('extension_version')=='0.2.4' and r.get('safety',{}).get('validated') and method in r.get('envelope_groups',{})
            checks.append(dict(key=f'thai_{dimension}d_{method}',status='Passed' if passed else 'Failed'))
        except Exception as exc: checks.append(dict(key=f'thai_{dimension}d_{method}',status='Failed',error=str(exc)))
report={'python':sys.version.split()[0],'prefix':sys.base_prefix,'checks':checks,'passed':sum(v['status']=='Passed' for v in checks),'failed':sum(v['status']=='Failed' for v in checks)}
Path(sys.argv[2]).write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'passed':report['passed'],'failed':report['failed'],'prefix':report['prefix']}))
if report['failed']: raise SystemExit(1)
