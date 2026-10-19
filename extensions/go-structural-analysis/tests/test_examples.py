"""Exercise every UI example with the real solver and independent references."""
import contextlib
import io
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
from examples import CATALOG, example
from worker import solve
from results import evaluate
from reference_frame import reference


@pytest.mark.parametrize('key',[row[0] for row in CATALOG])
def test_catalogue_solver(key):
    model=example(key)
    if key.startswith('unstable'):
        with pytest.raises(RuntimeError,match='singular|unstable'):
            solve(model)
        return
    with contextlib.redirect_stdout(io.StringIO()): result=solve(model)
    assert set(result['cases']) == set(model['cases'])
    for case,r in result['cases'].items():
        assert r['equilibrium']['passed']
        assert set(r['members']) == {m['id'] for m in model['members']}
    if key.startswith('portal') or key=='inclined' or key.startswith('continuous'):
        ref,_,_=reference(model)
        for node,values in ref.items():
            for component in ['ux','uz','rotation','Rx','Rz','My']:
                assert result['cases']['LC1']['nodes'][node][component] == pytest.approx(values[component],rel=1e-7,abs=1e-8)
    if key=='simple_point':
        r=result['cases']['LC1']
        assert r['nodes']['N1']['Rz'] == pytest.approx(10.)
        assert evaluate(r['members']['B1'],3.)['M'] == pytest.approx(-30.)


def test_catalogue_independent_models():
    first=example('truss'); first['nodes'][0]['x']=100.
    assert example('truss')['nodes'][0]['x']==0.
    assert len({row[0] for row in CATALOG})==len(CATALOG)
    with pytest.raises(ValueError,match='Unknown'): example('unknown')
