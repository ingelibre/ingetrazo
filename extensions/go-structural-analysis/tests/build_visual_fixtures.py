"""Real solver data used to inspect graphics without editing the live model."""
import contextlib
import io
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from examples import example
from worker import solve

root=Path(__file__).parents[1]/'artifacts/visual-update'
root.mkdir(parents=True,exist_ok=True)
fixtures=[]
for key in ['simple_udl','simple_point','continuous_3','portal_horizontal','truss','cantilever_point','inclined','moment_jump']:
    model=example(key)
    with contextlib.redirect_stdout(io.StringIO()): result=solve(model)
    fixtures.append({'key':key,'model':model,'result':result})
(root/'fixtures.json').write_text(json.dumps(fixtures),encoding='utf-8')
