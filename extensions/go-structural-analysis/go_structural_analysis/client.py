import json
import os
import subprocess
from pathlib import Path

def analyze(model,python=None,timeout=90):
    root=Path(__file__).parent
    if python is None:
        python=json.loads((root/'worker_config.json').read_text(encoding='utf-8-sig'))['python']
    if not Path(python).is_file(): raise RuntimeError('Solver Python missing. Run install.ps1 again.')
    env=os.environ.copy()
    for k in ['PYTHONHOME','PYTHONPATH','_MEIPASS2']: env.pop(k,None)
    try:
        proc=subprocess.run([str(python),'-I','-X','utf8',str(root/'worker.py')],input=json.dumps({'protocol':1,'model':model},allow_nan=False),
                            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,env=env,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except subprocess.TimeoutExpired as exc: raise RuntimeError(f'Solver timeout after {timeout}s') from exc
    try: reply=json.loads(proc.stdout)
    except ValueError as exc: raise RuntimeError('Invalid solver JSON: '+proc.stderr[-1500:]) from exc
    if not isinstance(reply,dict): raise RuntimeError('Invalid solver response object')
    if reply.get('protocol')!=1: raise RuntimeError('Worker protocol mismatch')
    if not reply.get('ok'):
        error=reply.get('error',{})
        raise RuntimeError(str(error.get('message','Solver failed') if isinstance(error,dict) else error or 'Solver failed'))
    if proc.returncode: raise RuntimeError('Solver exited unexpectedly: '+proc.stderr[-1500:])
    if not isinstance(reply.get('result'),dict) or not isinstance(reply['result'].get('cases'),dict): raise RuntimeError('Invalid solver result structure')
    if __package__: from .safety import validate_result
    else: from safety import validate_result
    try: validate_result(reply['result'])
    except ValueError as exc: raise RuntimeError(str(exc)) from exc
    return reply['result']
