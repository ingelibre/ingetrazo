"""A View moved on the sheet must re-project its endpoints (#122): the move
ends in push_geometry_edit, which deliberately does not rebuild the canvas, so
nothing dropped the page-mm caches and the frame kept catching vertices where
it used to be.

The drag and the nudge drop those caches outright; the snap set also carries
the page geometry it was computed at, so a door that drops nothing (an undo,
a rebuild) can no longer serve the endpoints of where the frame used to be."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

_app = QApplication.instance() or QApplication([])


def _frame_item(comp):
    from views.composer import FrameItem
    return next(it for it in comp.canvas.items() if isinstance(it, FrameItem))


def _seed_page_caches(comp, frame):
    """The page-mm caches and the picture, as a finished render leaves them."""
    import numpy as np
    comp.snap_cache[id(frame)] = (
        (frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm),
        (np.zeros((0, 2)), np.zeros((0, 3))))
    comp.circle_cache[id(frame)] = []
    comp.annot_cache[id(frame)] = []
    comp.render_cache[id(frame)] = QImage(4, 4, QImage.Format_RGB32)


def _drag_and_release(item, dx_mm, dy_mm):
    """The tail of a mouse drag: the model moved, then the button came up."""
    item._press_state = {"x_mm": item.model.x_mm, "y_mm": item.model.y_mm}
    item._resizing = False
    item.model.x_mm += dx_mm
    item.model.y_mm += dy_mm
    event = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMouseRelease)
    event.setPos(QPointF(1.0, 1.0))
    event.setScenePos(QPointF(1.0, 1.0))
    event.setButton(Qt.LeftButton)
    event.setButtons(Qt.NoButton)
    item.mouseReleaseEvent(event)


def test_a_moved_view_re_projects_its_endpoints():
    from views.composer import ComposerWindow
    from views.main_window import MainWindow

    win = MainWindow()
    comp = ComposerWindow(win)
    comp.show()
    was_auto = comp._auto_render
    try:
        comp._auto_render = False
        item = _frame_item(comp)
        frame = item.model
        _seed_page_caches(comp, frame)

        _drag_and_release(item, 20.0, 0.0)

        assert comp.snap_cache.get(id(frame)) is None      # collected again
        assert comp.circle_cache.get(id(frame)) is None
        assert comp.annot_cache.get(id(frame)) is None
        assert id(frame) in comp.render_cache              # but not the picture
    finally:
        comp._auto_render = was_auto
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_arrow_keys_do_not_leave_the_endpoints_behind():
    """The nudge is the same move through another door."""
    from views.composer import ComposerWindow
    from views.main_window import MainWindow

    win = MainWindow()
    comp = ComposerWindow(win)
    comp.show()
    was_auto = comp._auto_render
    try:
        comp._auto_render = False
        item = _frame_item(comp)
        frame = item.model
        item.setSelected(True)
        _seed_page_caches(comp, frame)

        assert comp.nudge_selected(5.0, 0.0)

        assert comp.snap_cache.get(id(frame)) is None
        assert comp.circle_cache.get(id(frame)) is None
        assert id(frame) in comp.render_cache
    finally:
        comp._auto_render = was_auto
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_cache_only_serves_the_geometry_it_was_computed_at():
    """The belt to the drag's braces: the entry says which page geometry it
    was built for, so a door that drops nothing cannot hand out a pair that
    belongs to where the frame used to be."""
    import numpy as np

    from views.composer import ComposerWindow
    from views.main_window import MainWindow

    win = MainWindow()
    comp = ComposerWindow(win)
    comp.show()
    was_auto = comp._auto_render
    try:
        comp._auto_render = False
        item = _frame_item(comp)
        frame = item.model
        seeded = (np.zeros((0, 2)), np.zeros((0, 3)))
        comp.snap_cache[id(frame)] = (comp._frame_page_stamp(frame), seeded)

        assert comp.frame_snap_points(frame) is seeded       # same spot: served

        frame.x_mm += 20.0                             # moved behind its back
        assert comp.frame_snap_points(frame) is not seeded   # recomputed
    finally:
        comp._auto_render = was_auto
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_undoing_a_move_takes_the_endpoints_back():
    """Ctrl+Z walks _on_history_change -> _rebuild_after_change, which drops
    nothing at all; the endpoints must come back on their own."""
    from views.composer import ComposerWindow
    from views.main_window import MainWindow

    win = MainWindow()
    comp = ComposerWindow(win)
    comp.show()
    was_auto = comp._auto_render
    try:
        comp._auto_render = False
        item = _frame_item(comp)
        frame = item.model
        before = (frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm)
        comp.frame_snap_points(frame)                  # endpoints cached here

        _drag_and_release(item, 20.0, 0.0)
        comp.frame_snap_points(frame)                  # ... and cached there
        moved = comp.snap_cache[id(frame)]
        assert moved[0][:4] != before

        assert comp.history.undo()                     # Ctrl+Z
        comp._rebuild_after_change()                   # the queued rebuild

        assert (frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm) == before
        assert comp.frame_snap_points(frame) is not moved[1]     # not those
        assert comp.snap_cache[id(frame)][0][:4] == before       # and not stale
    finally:
        comp._auto_render = was_auto
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
