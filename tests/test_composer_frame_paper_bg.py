# SPDX-License-Identifier: GPL-3.0-or-later
"""The frame's «Paper background»: render on white with no sky whatever
the style says (Marco, 2026-09-08, the rebar in X-ray: «no me gusta que
tenga el fondo gris del model»)."""
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import Composicion, MarcoVista
from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow, FrameItem

_app = QApplication.instance() or QApplication([])


class _RecordingViewport(_FakeViewport):
    """Records the style the render ran with, like the GL viewport would."""

    def __init__(self):
        super().__init__()
        self.plano_style = None
        self.style_override = None
        self.seen = []

    def _effective_style(self):
        from core.style import Style
        return self.style_override or Style()

    def render_image(self, w, h, overlays=True):
        self.seen.append(self._effective_style())
        return None


def test_paper_bg_round_trips_and_defaults_off():
    comp = Composicion()
    comp.frames = [MarcoVista(paper_bg=True)]
    again = Composicion.from_dict(comp.to_dict())
    assert again.frames[0].paper_bg is True
    assert MarcoVista(**{"x_mm": 1.0}).paper_bg is False       # old .igz


def test_paper_bg_renders_white_without_sky_and_keeps_the_face_mode():
    host = QWidget()
    host.viewport = _RecordingViewport()
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.style = "style:X-ray"
    composer.render_frame(frame)
    grey = host.viewport.seen[-1]
    assert grey.face_mode == "xray" and grey.sky and grey.background != (1.0, 1.0, 1.0)
    frame.paper_bg = True
    composer._forget_frame(frame)
    composer.render_frame(frame)
    white = host.viewport.seen[-1]
    assert white.face_mode == "xray" and not white.sky
    assert white.background == (1.0, 1.0, 1.0)
    # the live viewport comes back untouched
    assert host.viewport.style_override is None
    # the panel shows and edits it
    composer._rebuild_canvas()
    item = next(i for i in composer.canvas.items()
                if isinstance(i, FrameItem) and i.model is frame)
    item.setSelected(True)
    composer.on_selection_changed()
    assert composer.paper_bg_check.isChecked()
    composer.paper_bg_check.setChecked(False)
    assert frame.paper_bg is False
