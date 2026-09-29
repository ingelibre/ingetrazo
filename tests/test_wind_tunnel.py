import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QVector3D, QMatrix4x4
from PySide6.QtWidgets import QWidget
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from core.history import History
from core.wind_tunnel import (Settings, frame, validate_surface, group_triangles,
                              generate_case, terrain_solid)
from georef.terrain import TerrainObject


def tetra():
    vertices = [QVector3D(0,0,0), QVector3D(1,0,0), QVector3D(0,1,0), QVector3D(0,0,1)]
    group = Group(name='Test solid')
    for indices in [(0,2,1),(0,1,3),(0,3,2),(1,2,3)]:
        group.mesh.add_face([vertices[i] for i in indices])
    return group


def terrain():
    return TerrainObject([QVector3D(0,100,0), QVector3D(100,100,0),
                          QVector3D(0,0,0), QVector3D(100,0,0)], [],
                         [(0,2,1),(1,2,3)], (), nx=2, ny=2, bbox=(0,0,100,100))


def test_aircraft_case_geometry_and_settings(tmp_path):
    group = tetra(); group.xform = QMatrix4x4(); group.xform.translate(20,30,40); group.xform.scale(.001)
    path = tmp_path/'case with spaces'
    manifest = generate_case(path, [group], Settings(reference_area=.1, reference_length=.2, alpha=5))
    assert manifest['surfaces']['body'] == 4
    assert manifest['world_origin_m'] == pytest.approx([20.0005,30.0005,40.0005], abs=4e-6)
    assert (path/'constant/triSurface/body.stl').stat().st_size == 84+4*50
    assert 'Aref 0.1;' in (path/'system/controlDict').read_text()
    assert 'kOmegaSST' in (path/'constant/turbulenceProperties').read_text()
    assert (path/'0/omega').exists() and not (path/'0/epsilon').exists()
    assert json.loads((path/'ingetrazo-case.json').read_text())['status'].startswith('exported')
    with pytest.raises(ValueError, match='never overwritten'):
        generate_case(path, [group], Settings())


def test_terrain_is_closed_and_has_atmospheric_boundaries(tmp_path):
    path = tmp_path/'terrain'
    report = generate_case(path, [], Settings(mode='terrain', heading=45), terrain())
    assert report['surfaces']['terrain'] > 3000
    assert (path/'0/epsilon').exists()
    assert 'atmBoundaryLayerInletVelocity' in (path/'0/U').read_text()
    assert 'atmBoundaryLayerInletK' in (path/'0/k').read_text()
    assert 'atmBoundaryLayerInletEpsilon' in (path/'0/epsilon').read_text()
    assert 'atmNutkWallFunction' in (path/'0/nut').read_text()
    assert 'kEpsilon' in (path/'constant/turbulenceProperties').read_text()
    assert 'forceCoeffs' not in (path/'system/controlDict').read_text()


def test_bad_geometry_and_inputs_do_not_create_case(tmp_path):
    tri = group_triangles([tetra()])
    with pytest.raises(ValueError, match='watertight'):
        validate_surface(tri[:-1])
    tri[0] = tri[0][::-1]
    with pytest.raises(ValueError, match='directions'):
        validate_surface(tri)
    for s in [Settings(speed=float('nan')), Settings(speed=-1), Settings(mode='terrain', alpha=5)]:
        with pytest.raises(ValueError):
            generate_case(tmp_path/'bad', [tetra()], s)
        assert not (tmp_path/'bad').exists()


def test_wind_frame_is_reversible_and_flow_heading_correct():
    r = frame(Settings(heading=90))
    assert r @ np.array([0,1,0]) == pytest.approx([1,0,0], abs=1e-12)
    assert r.T @ r == pytest.approx(np.eye(3), abs=1e-12)


def test_shell_paths_are_quoted_and_docker_has_bounded_resources(tmp_path, monkeypatch):
    from core import wind_tunnel_runner as runner
    bashrc = tmp_path/"foo ' $(false)"; bashrc.touch()
    program, args = runner.invocation(tmp_path, 'blockMesh', [], 'native', str(bashrc))
    import shlex
    assert 'source '+shlex.quote(str(bashrc)) in args[1]
    monkeypatch.setattr(runner, 'executable', lambda name: '/usr/bin/docker')
    program, args = runner.invocation(tmp_path, 'simpleFoam', [], 'docker', container='test-cfd')
    assert args[args.index('--cpus')+1] == '4'
    assert args[args.index('--memory')+1] == '6g'
    assert args[args.index('--name')+1] == 'test-cfd'


def run_fake(tmp_path, monkeypatch, outputs, failing=None, cancel=False):
    from core import wind_tunnel_runner as mod
    generate_case(tmp_path/'case', [tetra()], Settings())
    seen = []
    def invocation(case, stage, args, backend, bashrc='', container=''):
        seen.append(stage)
        if cancel:
            return '/bin/sleep', ['10']
        code = 3 if stage == failing else 0
        import shlex
        return '/bin/sh', ['-c', 'printf %s '+shlex.quote(outputs.get(stage, 'done'))+f'; exit {code}']
    monkeypatch.setattr(mod, 'invocation', invocation)
    runner = mod.Runner(); loop = QEventLoop(); result = []
    runner.completed.connect(lambda success, message: (result.append((success,message)), loop.quit()))
    runner.start(tmp_path/'case', 'native')
    if cancel:
        QTimer.singleShot(30, runner.stop)
    timer = QTimer(); timer.setSingleShot(True); timer.timeout.connect(loop.quit); timer.start(5000)
    loop.exec(); timer.stop()
    assert result, 'runner did not finish'
    return result[0], seen, runner


def test_runner_stops_on_failed_mesh(tmp_path, monkeypatch):
    (success, message), seen, _ = run_fake(tmp_path, monkeypatch, {'checkMesh':'Failed 1 mesh checks.'})
    assert not success and 'simpleFoam' not in seen
    assert 'quality' in message


def test_runner_failure_and_no_false_convergence(tmp_path, monkeypatch):
    (success, message), seen, _ = run_fake(tmp_path, monkeypatch, {}, failing='snappyHexMesh')
    assert not success and 'checkMesh' not in seen


def test_runner_success_distinguishes_iteration_limit(tmp_path, monkeypatch):
    (success, message), _, _ = run_fake(tmp_path, monkeypatch, {'checkMesh':'Mesh OK.', 'simpleFoam':'End'})
    assert success and 'not confirmed' in message
    assert (tmp_path/'case/log.simpleFoam').read_text() == 'End'


def test_runner_cancel(tmp_path, monkeypatch):
    (success, message), seen, runner = run_fake(tmp_path, monkeypatch, {}, cancel=True)
    assert not success and runner.cancelled and not runner.active
    assert 'Stopped' in message


def test_dialog_loads_modes_and_logs_without_solver():
    from plugins.wind_tunnel import WindTunnelDialog
    scene = Scene(); scene.groups.append(tetra()); window = QWidget()
    vp = SimpleNamespace(scene=scene, history=History(scene), window=lambda: window,
                         notify_scene_changed=lambda: None)
    dialog = WindTunnelDialog(vp)
    dialog.mode.setCurrentIndex(1)
    assert not dialog.fields['alpha'].isEnabled()
    assert dialog.fields['roughness'].isEnabled()
    dialog.append_log('test output\n')
    assert 'test output' in dialog.log.toPlainText()
    assert not dialog.run_button.isEnabled()
    dialog.reject()


def test_small_aerofoil_details_survive_export(tmp_path):
    from core.maker import aerofoil
    wing = aerofoil(code="0012", chord=100, span=300)
    report = generate_case(tmp_path/'small-wing', [wing], Settings(reference_area=.03, reference_length=.1))
    assert report['surfaces']['body'] > 400
    tri = group_triangles([wing])
    assert np.ptp(tri.reshape(-1,3), axis=0)[0] == pytest.approx(.1)
