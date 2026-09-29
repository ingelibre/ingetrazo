# SPDX-License-Identifier: GPL-3.0-or-later
"""Asynchronous, cancellable OpenFOAM pipeline; no application-thread waits."""
from pathlib import Path
import json
import os
import shlex
import shutil
import uuid
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from core.wind_tunnel import IMAGE, STAGES


def executable(name):
    found = shutil.which(name)
    if found:
        return found
    for directory in ('/opt/homebrew/bin', '/usr/local/bin', '/Applications/Docker.app/Contents/Resources/bin'):
        path = Path(directory)/name
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def invocation(case, stage, args, backend, bashrc='', container=''):
    """All paths quoted or separate argv; never evaluate model/user names."""
    setup = f'source {shlex.quote(str(Path(bashrc).expanduser()))} && ' if bashrc else ''
    version = 'test "${WM_PROJECT_VERSION#v}" = 2312 || { echo "Requires OpenCFD OpenFOAM v2312; source its etc/bashrc."; exit 2; }; '
    cmd = setup + version + 'exec ' + shlex.join([stage, *args])
    if backend == 'docker':
        docker = executable('docker')
        if not docker:
            raise ValueError('Docker is not installed. Install and start Docker Desktop, or export this case to a Linux OpenFOAM machine.')
        cmd = 'source /usr/lib/openfoam/openfoam2312/etc/bashrc && ' + version + 'exec ' + shlex.join([stage, *args])
        return docker, ['run', '--rm', '--init', '--name', container, '--cpus', '4', '--memory', '6g',
                        '--mount', f'type=bind,source={Path(case).resolve()},target=/case',
                        '--workdir', '/case', '--entrypoint', '/bin/bash', IMAGE, '-c', cmd]
    if backend != 'native':
        raise ValueError('Choose a solver backend.')
    if bashrc and not Path(bashrc).expanduser().is_file():
        raise ValueError('OpenFOAM etc/bashrc does not exist.')
    return '/bin/bash', ['-c', cmd]


class Runner(QObject):
    output = Signal(str)
    stage_changed = Signal(str)
    completed = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = None
        self.stop_process = None
        self.active = False
        self.cancelled = False
        self.log = None
        self.step = 0
        self.tail = ''
        self.case = None
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self._kill)

    def start(self, case, backend, bashrc=''):
        if self.active:
            raise ValueError('A calculation is already running.')
        self.case = Path(case)
        if not (self.case/'ingetrazo-case.json').is_file():
            raise ValueError('Export an IngeTrazo wind-tunnel case first.')
        if (self.case/'constant/polyMesh').exists():
            raise ValueError('This case already has a mesh. Export a new case to protect results.')
        self.backend, self.bashrc = backend, bashrc
        self.container = 'ingetrazo-cfd-' + uuid.uuid4().hex[:12]
        # Validate before entering running state.
        invocation(self.case, *STAGES[0], backend, bashrc, self.container)
        self.cancelled = False; self.step = 0; self.active = True
        self._next()

    def _next(self):
        if self.step == len(STAGES):
            converged = 'SIMPLE solution converged' in self.tail
            self._finish(True, 'Solver finished; residual convergence reported. Check forces and mesh independence.' if converged else 'Solver reached its end. Convergence is not confirmed; inspect residuals and forces.')
            return
        name, args = STAGES[self.step]
        try:
            program, arguments = invocation(self.case, name, args, self.backend, self.bashrc, self.container)
            self.log = (self.case/f'log.{name}').open('w')
        except (ValueError, OSError) as exc:
            self._finish(False, str(exc)); return
        self.tail = ''
        self.stage_changed.emit(f'{self.step+1}/{len(STAGES)} — {name}')
        self._status('running', name)
        process = QProcess(self)
        self.process = process
        process.setWorkingDirectory(str(self.case))
        env = QProcessEnvironment.systemEnvironment()
        # A packaged Python app's library overrides must not leak into OpenFOAM.
        for key in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'PYTHONHOME', 'PYTHONPATH'):
            env.remove(key)
        process.setProcessEnvironment(env)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self._read)
        process.errorOccurred.connect(self._error)
        process.finished.connect(self._ended)
        process.start(program, arguments)

    def _read(self):
        if self.process is None:
            return
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        self.tail = (self.tail + text)[-65536:]
        if self.log:
            self.log.write(text); self.log.flush()
        self.output.emit(text)

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self._finish(False, 'Could not start the solver: '+self.process.errorString())

    def _ended(self, code, status):
        self._read()
        if not self.active:
            return
        if self.cancelled:
            # Docker completion alone does not prove container cleanup; wait
            # for the explicit stop command when it is still running.
            if self.stop_process and self.stop_process.state() != QProcess.NotRunning:
                return
            self._finish(False, 'Stopped. Partial results and logs retained.'); return
        stage = STAGES[self.step][0]
        if code != 0 or status != QProcess.NormalExit:
            self._finish(False, f'{stage} failed (exit {code}). See log.{stage}.'); return
        if stage == 'checkMesh' and 'Mesh OK.' not in self.tail:
            self._finish(False, 'Mesh quality checks did not pass. Solver was not started. See log.checkMesh.'); return
        if self.log:
            self.log.close(); self.log = None
        self.process.deleteLater(); self.process = None
        self.step += 1
        self._next()

    def stop(self):
        if not self.active or self.cancelled:
            return
        self.cancelled = True
        self.stage_changed.emit('Stopping…')
        if self.backend == 'docker':
            self.stop_process = QProcess(self)
            self.stop_process.finished.connect(self._docker_stopped)
            self.stop_process.errorOccurred.connect(self._stop_error)
            self.stop_process.start(executable('docker'), ['stop', '--time', '2', self.container])
        else:
            self.process.terminate()
            self.kill_timer.start(3000)

    def _stop_error(self, error):
        if error == QProcess.FailedToStart:
            self.output.emit(f'Could not stop container. Run: docker stop {self.container}\n')
            self.process.terminate()

    def _docker_stopped(self, code, status):
        text = bytes(self.stop_process.readAllStandardError()).decode(errors='replace')
        if code and 'No such container' not in text:
            self.output.emit(f'Container stop failed: {text}\nCheck: docker stop {self.container}\n')
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.terminate(); self.kill_timer.start(3000)
        else:
            self._finish(False, 'Stopped. Partial results retained.' if not code else f'Container cleanup needs checking: {self.container}')

    def _kill(self):
        if self.active and self.cancelled and self.process:
            self.process.kill()

    def _status(self, state, detail):
        try:
            (self.case/'ingetrazo-run.json').write_text(json.dumps(dict(status=state, detail=detail, container=self.container if self.backend == 'docker' else None), indent=2))
        except OSError as exc:
            self.output.emit(f'Could not save run status: {exc}\n')

    def _finish(self, success, message):
        self.kill_timer.stop()
        if self.log:
            self.log.close(); self.log = None
        self.active = False
        self._status('finished' if success else 'stopped' if self.cancelled else 'failed', message)
        self.completed.emit(success, message)
