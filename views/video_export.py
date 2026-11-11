# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Export the scenes as a video (.mkv): the run of Camera ▸ Animation ▸
Play, once through, rendered frame by frame and written to a Matroska file.

- The frames are the scene player's poses (core/scene_animation.py,
  ``video_at``) at the fps chosen, each drawn off screen by the viewport
  (``render_image``), so the video holds what the view would show:
  style, shadows, sections, the layers of the scene reached.
- Qt Multimedia writes the file (``QMediaRecorder`` fed by a
  ``QVideoFrameInput``): no program or library besides Qt. Matroska takes
  MPEG-4 video from Qt's own encoders, which every usual player opens.
- The view comes back exactly as it was: camera, layers, style, section…
  (a snapshot taken before, recalled after).
"""
from __future__ import annotations

import time
from pathlib import Path

from core.i18n import tr

#: Video sizes offered, (width, height) in pixels.
VIDEO_SIZES = ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160))
DEFAULT_SIZE = (1920, 1080)
DEFAULT_FPS = 30
#: Bits per pixel per frame: about 12 Mbit/s at 1080p 30 — a presentation
#: with fine lines stays sharp.
BITS_PER_PIXEL = 0.2
#: How long to wait for the encoder before giving up (seconds).
TIMEOUT = 30.0


class VideoError(RuntimeError):
    """The video could not be written (the message says why)."""


def even(n: int) -> int:
    """Video encoders want even sizes."""
    return max(2, int(n) // 2 * 2)


def multimedia_available() -> bool:
    """Whether Qt Multimedia loads. Missing is not the only way to fail:
    on Linux it is there but needs the system's PulseAudio library
    (libpulse.so.0), and without it the import fails all the same."""
    try:
        import PySide6.QtMultimedia  # noqa: F401
    except ImportError:
        return False
    return True


def no_video_message() -> str:
    return tr("This build of IngeTrazo has no video support (Qt Multimedia).")


class MkvWriter:
    """Frames in, a .mkv file out."""

    def __init__(self, path, width: int, height: int, fps: int) -> None:
        from PySide6.QtCore import QSize, QUrl
        try:
            from PySide6.QtMultimedia import (QMediaCaptureSession,
                                              QMediaFormat, QMediaRecorder,
                                              QVideoFrameInput)
        except ImportError as exc:
            raise VideoError(no_video_message()) from exc
        from PySide6.QtWidgets import QApplication
        self._app = QApplication.instance()
        self.path = Path(path).resolve()   # a relative URL lands elsewhere
        self.width, self.height = even(width), even(height)
        self.fps = int(fps)
        self.frames = 0
        self._errors: list[str] = []
        self._ready = False
        self._session = QMediaCaptureSession()
        self._input = QVideoFrameInput()
        self._session.setVideoFrameInput(self._input)
        rec = self._recorder = QMediaRecorder()
        self._session.setRecorder(rec)
        rec.setMediaFormat(QMediaFormat(QMediaFormat.Matroska))
        rec.setVideoResolution(QSize(self.width, self.height))
        rec.setVideoFrameRate(self.fps)
        rec.setQuality(QMediaRecorder.VeryHighQuality)
        rec.setVideoBitRate(int(self.width * self.height * self.fps
                                * BITS_PER_PIXEL))
        rec.setOutputLocation(QUrl.fromLocalFile(str(self.path)))
        rec.errorOccurred.connect(lambda _e, text: self._errors.append(text))
        self._input.readyToSendVideoFrame.connect(self._on_ready)
        rec.record()
        self._wait(lambda: rec.recorderState() == QMediaRecorder.RecordingState)

    def _on_ready(self) -> None:
        self._ready = True

    def _wait(self, done) -> None:
        from PySide6.QtCore import QEventLoop
        t0 = time.monotonic()
        while not done():
            if self._errors:
                raise VideoError(self._errors[-1])
            if time.monotonic() - t0 > TIMEOUT:
                raise VideoError(tr("The video encoder did not answer."))
            self._app.processEvents(QEventLoop.AllEvents, 20)
        if self._errors:
            raise VideoError(self._errors[-1])

    def write(self, image) -> None:
        """Add ``image`` (a QImage of the video's size) as the next frame."""
        from PySide6.QtGui import QImage
        from PySide6.QtMultimedia import QVideoFrame
        if image.width() != self.width or image.height() != self.height:
            image = image.scaled(self.width, self.height)
        frame = QVideoFrame(image.convertToFormat(QImage.Format_RGBX8888))
        frame.setStartTime(int(self.frames * 1_000_000 / self.fps))
        frame.setEndTime(int((self.frames + 1) * 1_000_000 / self.fps))
        while not self._input.sendVideoFrame(frame):
            self._ready = False
            self._wait(lambda: self._ready)
        self.frames += 1

    def close(self) -> None:
        """Finish the file (waits for the encoder to write it all)."""
        from PySide6.QtMultimedia import QMediaRecorder
        rec = self._recorder
        if rec.recorderState() != QMediaRecorder.StoppedState:
            rec.stop()
        self._wait(lambda: rec.recorderState() == QMediaRecorder.StoppedState)

    def discard(self) -> None:
        """Stop and remove the half-written file (cancelled or failed)."""
        try:
            self.close()
        except VideoError:
            pass
        try:
            self.path.unlink()
        except OSError:
            pass


def export_video(window, path, width: int, height: int, fps: int,
                 progress=None) -> int:
    """Write the active project's scenes as a video to ``path``.

    ``progress(done, total)`` is called after every frame; returning False
    cancels (the file is removed). Returns the frames written, or 0 when
    cancelled. Raises :class:`VideoError` when it cannot be written."""
    from core.saved_views import SavedView, shown_state
    from core.scene_animation import Pose, video_at, video_frame_count
    viewport = window.viewport
    scene = viewport.scene
    views = list(getattr(scene, "saved_views", []) or [])
    if not views:
        raise VideoError(tr("This project has no scenes to play: keep a view "
                            "as a scene first (Scenes panel, «+ Scene»)."))
    player = getattr(window, "scene_player", None)
    if player is not None:
        player.cancel()
    anim = scene.animation
    poses = [Pose.of_view(v) for v in views]
    total = video_frame_count(len(poses), anim.transition, anim.pause, fps)
    camera = viewport.camera
    before = SavedView.capture("", scene, camera)
    aspect = camera.aspect
    width, height = even(width), even(height)
    # The annotations (dimensions, texts) are drawn for the widget's shape:
    # only a video of that shape can carry them where they belong.
    same_shape = abs(width / height
                     - max(viewport.width(), 1) / max(viewport.height(), 1)) \
        < 0.01
    writer = MkvWriter(path, width, height, fps)
    shown = -1
    done = False
    try:
        for i in range(total):
            pose, reached = video_at(poses, anim.transition, anim.pause,
                                     i / fps)
            if reached != shown:
                shown = reached
                state = shown_state(scene)
                views[reached].apply_state(scene)
                if shown_state(scene) != state:
                    scene.version += 1
            pose.put_on(camera)
            camera.aspect = width / height
            image = viewport.render_image(width, height, overlays=same_shape,
                                          annotations_only=True)
            if image is None or image.isNull():
                raise VideoError(tr("Could not render the view."))
            writer.write(image)
            if progress is not None and progress(i + 1, total) is False:
                writer.discard()
                return 0
        writer.close()
        done = True
        return writer.frames
    finally:
        if not done:                        # cancelled or failed: no half file
            writer.discard()
        state = shown_state(scene)
        before.apply(scene, camera)
        camera.aspect = aspect
        if shown_state(scene) != state:
            scene.version += 1
        viewport.update()


class VideoOptionsDialog:
    """Size and frames per second, and how long the video will last."""

    def __init__(self, parent, scene, view_size) -> None:
        from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                                       QFormLayout, QLabel)

        from core.scene_animation import (VIDEO_FPS, video_frame_count,
                                          video_seconds)
        self.dialog = dlg = QDialog(parent)
        dlg.setWindowTitle(tr("Export Video"))
        form = QFormLayout(dlg)
        self.size_box = QComboBox(dlg)
        self.size_box.setObjectName("video_size")
        vw, vh = even(view_size[0]), even(view_size[1])
        for w, h in VIDEO_SIZES:
            self.size_box.addItem(f"{w} × {h}", (w, h))
        self.size_box.addItem(tr("Like the view ({w} × {h})", w=vw, h=vh),
                              (vw, vh))
        self.size_box.setCurrentIndex(VIDEO_SIZES.index(DEFAULT_SIZE))
        form.addRow(tr("Video size:"), self.size_box)
        self.fps_box = QComboBox(dlg)
        self.fps_box.setObjectName("video_fps")
        for fps in VIDEO_FPS:
            self.fps_box.addItem(str(fps), fps)
        self.fps_box.setCurrentIndex(VIDEO_FPS.index(DEFAULT_FPS))
        form.addRow(tr("Frames per second:"), self.fps_box)
        anim = scene.animation
        count = len(scene.saved_views)
        self.length = QLabel(dlg)
        self.length.setObjectName("video_length")

        def show_length() -> None:
            fps = self.fps_box.currentData()
            self.length.setText(tr(
                "{scenes} scenes, {seconds} s ({frames} frames)",
                scenes=count,
                seconds=f"{video_seconds(count, anim.transition, anim.pause):.1f}",
                frames=video_frame_count(count, anim.transition, anim.pause,
                                         fps)))
        show_length()
        self.fps_box.currentIndexChanged.connect(lambda _i: show_length())
        form.addRow(tr("Duration:"), self.length)
        hint = QLabel(tr("The times are those of Camera ▸ Animation ▸ "
                         "Animation Settings…"), dlg)
        hint.setWordWrap(True)
        form.addRow(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

    def exec(self) -> bool:
        from PySide6.QtWidgets import QDialog
        return self.dialog.exec() == QDialog.Accepted

    def choice(self) -> tuple:
        """((width, height), fps)."""
        return self.size_box.currentData(), self.fps_box.currentData()


def run_export(window) -> None:
    """File ▸ Export ▸ Scenes as Video…: ask where and how, then write it
    with a progress dialog that can cancel."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox, QProgressDialog

    from views.filedialogs import file_dialogs
    scene = window.viewport.scene
    if not getattr(scene, "saved_views", None):
        QMessageBox.information(window, tr("Export Video"), tr(
            "This project has no scenes to play: keep a view as a scene "
            "first (Scenes panel, «+ Scene»)."))
        return
    if not multimedia_available():
        QMessageBox.critical(window, tr("Export Video failed"),
                             no_video_message())
        return
    path_cur = getattr(window, "_current_path", None)
    base = path_cur.stem if path_cur is not None else "untitled"
    path_str, _ = file_dialogs.getSaveFileName(
        window, tr("Export Video"), f"{base}.mkv",
        tr("Matroska video (*.mkv)"))
    if not path_str:
        return
    path = Path(path_str)
    if path.suffix.lower() != ".mkv":
        path = path.with_suffix(".mkv")
    vp = window.viewport
    options = VideoOptionsDialog(window, scene, (vp.width(), vp.height()))
    if not options.exec():
        return
    (width, height), fps = options.choice()
    bar = QProgressDialog(tr("Rendering the video…"), tr("Cancel"), 0, 100,
                          window)
    bar.setWindowTitle(tr("Export Video"))
    bar.setWindowModality(Qt.WindowModal)
    bar.setMinimumDuration(0)

    def progress(done: int, total: int) -> bool:
        bar.setMaximum(total)
        bar.setValue(done)
        return not bar.wasCanceled()
    try:
        frames = export_video(window, path, width, height, fps, progress)
    except VideoError as exc:
        bar.close()
        QMessageBox.critical(window, tr("Export Video failed"), str(exc))
        return
    bar.close()
    if frames:
        window.statusBar().showMessage(tr(
            "Exported video {w}×{h}, {frames} frames → {name}",
            w=even(width), h=even(height), frames=frames, name=path.name),
            6000)
    else:
        window.statusBar().showMessage(tr("Video export cancelled."), 3000)
