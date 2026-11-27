# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scene videos rendered in the background, for the AI bridge (#1714).

``export_video`` over MCP must not hold IngeTrazo for the minutes a video
takes: the bridge answers one call at a time on the Qt main thread, and a
call that renders every frame would stall every other request (and hit
the bridge's three-minute reply limit). So a call only STARTS a job; the
frames are rendered one per turn of the event loop, between whatever else
the app and the agent do, and the agent asks how far it got
(``video_status``), looks at the frame where each scene is reached
(``video_keyframe``) or stops it (``cancel_video``).

Rendering has to happen on the main thread (the GL context lives there),
so «in the background» means interleaved, not on a thread of its own:

- Each step puts the video's camera and the scene's layers and style up,
  renders one frame and puts the user's view back BEFORE the frame goes to
  the encoder (``MkvWriter.write`` runs the event loop while it waits, and
  nothing else may see the video's camera). A saved document stays saved.
- No step runs while a bridge call is running (its event loop may be a
  nested one) or inside another step.
- At most :attr:`VideoJobs.max_jobs` videos run at once (1 by default,
  ``--max-videos N`` or ``INGETRAZO_MAX_VIDEOS``); more are refused, not
  queued, so the agent knows at once. Several videos share the one GPU and
  the one view, so they take turns frame by frame: two are not faster
  than one after the other.
- A document replaced while its video renders (``open_document``) fails
  that video: its scenes are gone.
- A video cancelled or failed leaves no half file (the writers'
  ``discard``); the keyframes stay, small, in the bridge's own folder.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer

from views.video_export import (PNG, VideoError, even, frame_folder)

#: Videos that may render at the same time unless configured otherwise.
DEFAULT_MAX_JOBS = 1
#: The environment variable that sets it for a windowed IngeTrazo.
MAX_JOBS_ENV = "INGETRAZO_MAX_VIDEOS"
#: Width of the keyframe previews (pixels): enough to judge the framing,
#: small enough to send over MCP in a moment.
KEYFRAME_WIDTH = 480
#: Finished videos remembered for ``video_status`` (the oldest go first).
KEEP_FINISHED = 20

RUNNING, DONE, FAILED, CANCELLED = "running", "done", "failed", "cancelled"


def max_jobs_from_env(default: int = DEFAULT_MAX_JOBS) -> int:
    """``INGETRAZO_MAX_VIDEOS`` as a count of at least 1, else ``default``."""
    raw = os.environ.get(MAX_JOBS_ENV, "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


class VideoJob:
    """One video being written: the scenes, the settings, the writer, and
    how far it got."""

    def __init__(self, viewport, writer, views, animation, fps: int,
                 width: int, height: int, fmt: str, transparent: bool,
                 path: Path, keyframe_root: Path) -> None:
        from core.scene_animation import Pose, video_frame_count, \
            video_seconds
        self.id = uuid.uuid4().hex[:12]
        #: Where the keyframes go: a folder of this job's own.
        self.keyframe_dir = Path(keyframe_root) / f"video-{self.id}"
        self.viewport = viewport
        self.scene = viewport.scene
        self.writer = writer
        self.views = list(views)
        self.animation = animation
        self.poses = [Pose.of_view(v) for v in self.views]
        self.fps = int(fps)
        self.width, self.height = even(width), even(height)
        self.fmt = fmt
        self.transparent = bool(transparent)
        self.path = Path(frame_folder(path) if fmt == PNG else path)
        self.total = video_frame_count(len(self.poses), animation.transition,
                                       animation.pause, self.fps)
        self.seconds = video_seconds(len(self.poses), animation.transition,
                                     animation.pause)
        self.frames = 0
        self.state = RUNNING
        self.error: str | None = None
        self.keyframes: list[dict] = []
        self.started = time.monotonic()
        self.ended: float | None = None
        self._reached = -1

    # ---- One frame -------------------------------------------------------------
    def step(self) -> None:
        """Render and write the next frame; finish the file after the last.
        The user's view is back before the frame goes to the encoder."""
        from core.saved_views import SavedView, shown_state
        from core.scene_animation import video_at
        vp = self.viewport
        scene = vp.scene
        if scene is not self.scene:
            raise VideoError("the document was replaced while its video "
                             "rendered")
        anim = self.animation
        pose, reached = video_at(self.poses, anim.transition, anim.pause,
                                 self.frames / self.fps)
        cam = vp.camera
        window = vp.window()
        dirty = getattr(window, "_is_dirty", None)
        was_clean = callable(dirty) and not dirty()
        before = SavedView.capture("__video__", scene, cam)
        aspect = cam.aspect
        users = shown_state(scene)
        image = None
        try:
            self.views[reached].apply_state(scene)
            videos = shown_state(scene)
            if videos != users:
                scene.version += 1
            pose.put_on(cam)
            cam.aspect = self.width / self.height
            # Annotations are drawn for the widget's shape: only a video of
            # that shape carries them where they belong (as export_video).
            same_shape = abs(self.width / self.height
                             - max(vp.width(), 1) / max(vp.height(), 1)) \
                < 0.01
            image = vp.render_image(
                self.width, self.height, overlays=same_shape,
                annotations_only=True,
                transparent=self.fmt == PNG and self.transparent)
        finally:
            during = shown_state(scene)
            before.apply(scene, cam)
            cam.aspect = aspect
            if shown_state(scene) != during:
                scene.version += 1
            if was_clean:
                window._saved_version = scene.version
            vp.update()
        if image is None or image.isNull():
            raise VideoError("the view did not render")
        if reached != self._reached:
            self._reached = reached
            self._keep_keyframe(image, reached)
        self.writer.write(image)
        self.frames += 1
        if self.frames >= self.total:
            self.writer.close()
            self._end(DONE)

    def _keep_keyframe(self, image, reached: int) -> None:
        """The frame where scene ``reached`` is reached, small, as a PNG."""
        self.keyframe_dir.mkdir(parents=True, exist_ok=True)
        path = self.keyframe_dir / f"key_{reached + 1:02d}.png"
        small = image.scaledToWidth(min(KEYFRAME_WIDTH, image.width()),
                                    Qt.SmoothTransformation)
        if small.save(str(path), "PNG"):
            self.keyframes.append({"index": len(self.keyframes),
                                   "scene": self.views[reached].name,
                                   "frame": self.frames,
                                   "path": str(path)})

    # ---- Ends ------------------------------------------------------------------
    def _end(self, state: str, error: str | None = None) -> None:
        self.state = state
        self.error = error
        self.ended = time.monotonic()

    def cancel(self) -> None:
        if self.state == RUNNING:
            self.writer.discard()
            self._end(CANCELLED)

    def fail(self, exc: BaseException) -> None:
        if self.state == RUNNING:
            self.writer.discard()
            self._end(FAILED, str(exc) or type(exc).__name__)

    # ---- What the agent is told ----------------------------------------------------
    def status(self) -> dict:
        end = self.ended if self.ended is not None else time.monotonic()
        elapsed = end - self.started
        out = {"job_id": self.id, "state": self.state,
               "path": str(self.path), "format": self.fmt,
               "frames_done": self.frames, "frames_total": self.total,
               "percent": round(100.0 * self.frames / max(self.total, 1), 1),
               "elapsed_s": round(elapsed, 1),
               "fps": self.fps, "width": self.width, "height": self.height,
               "seconds": round(self.seconds, 3),
               "scenes": [v.name for v in self.views],
               "transition": self.animation.transition,
               "pause": self.animation.pause,
               "keyframes": list(self.keyframes)}
        if self.state == RUNNING and self.frames:
            out["eta_s"] = round(elapsed / self.frames
                                 * (self.total - self.frames), 1)
        if self.error:
            out["error"] = self.error
        return out


class VideoJobs(QObject):
    """The videos of one bridge, stepped by a timer on the main thread."""

    def __init__(self, parent=None, busy=None,
                 max_jobs: int | None = None) -> None:
        super().__init__(parent)
        #: How many videos may render at once (at least 1).
        self.max_jobs = max(1, int(max_jobs)) if max_jobs else \
            max_jobs_from_env()
        self._busy = busy or (lambda: False)
        self._jobs: dict[str, VideoJob] = {}
        self._stepping = False
        self._turn = 0
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)

    def running(self) -> list[VideoJob]:
        return [j for j in self._jobs.values() if j.state == RUNNING]

    def check_room(self) -> None:
        """Refuse a new video when ``max_jobs`` are rendering already."""
        run = self.running()
        if len(run) >= self.max_jobs:
            raise RuntimeError(
                f"{len(run)} video(s) already rendering (at most "
                f"{self.max_jobs} at a time): wait for "
                + ", ".join(j.id for j in run)
                + " (video_status) or cancel it (cancel_video)")

    def add(self, job: VideoJob) -> VideoJob:
        self.check_room()
        self._jobs[job.id] = job
        self._prune()
        self._timer.start()
        return job

    def get(self, job_id: str) -> VideoJob:
        job = self._jobs.get(str(job_id or ""))
        if job is None:
            known = ", ".join(self._jobs) or "none"
            raise KeyError(f"no video job {job_id!r}; the jobs are: {known}")
        return job

    def all(self) -> list[VideoJob]:
        return list(self._jobs.values())

    def cancel(self, job_id: str) -> VideoJob:
        job = self.get(job_id)
        job.cancel()
        return job

    def cancel_all(self) -> None:
        for job in self.running():
            job.cancel()
        self._timer.stop()

    def _prune(self) -> None:
        finished = [j for j in self._jobs.values() if j.state != RUNNING]
        for job in finished[:max(0, len(finished) - KEEP_FINISHED)]:
            del self._jobs[job.id]

    def _tick(self) -> None:
        if self._stepping or self._busy():
            return
        run = self.running()
        if not run:
            self._timer.stop()
            return
        job = run[self._turn % len(run)]
        self._turn += 1
        self._stepping = True
        try:
            job.step()
        except Exception as exc:  # noqa: BLE001 — the job reports it
            job.fail(exc)
        finally:
            self._stepping = False
