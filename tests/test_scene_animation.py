# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scene transitions (core/scene_animation.py, views/scene_player.py):
showing a scene glides the camera there instead of jumping, the rest of
the scene comes in on arrival, Play runs through every scene in turn,
anything the user does takes the view back, and the document keeps its
transition and pause times."""
from __future__ import annotations

import math
import sys

import pytest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.scene_animation import (DEFAULT_PAUSE, DEFAULT_TRANSITION,  # noqa: E402
                                  MAX_SECONDS, Pose, Run, SceneAnimation,
                                  between, ease, glide, turn)


def _pose(x=0.0, distance=10.0, yaw=0.0, pitch=0.3, fov=45.0,
          perspective=True, two_point=False):
    return Pose((x, 0.0, 0.0), distance, yaw, pitch, fov, perspective,
                two_point)


# ---- The maths ------------------------------------------------------------------
def test_ease_starts_and_stops_gently():
    assert ease(0.0) == 0.0 and ease(1.0) == pytest.approx(1.0)
    assert ease(0.5) == pytest.approx(0.5)
    assert ease(-1.0) == 0.0 and ease(2.0) == pytest.approx(1.0)
    samples = [ease(i / 20) for i in range(21)]
    assert samples == sorted(samples)
    # Flat at the ends: the first and last steps are the smallest.
    steps = [b - a for a, b in zip(samples, samples[1:])]
    assert steps[0] < steps[10] and steps[-1] < steps[10]


def test_yaw_turns_the_short_way_round():
    a, b = math.radians(170), math.radians(-170)
    assert math.degrees(turn(a, b)) == pytest.approx(20.0)
    assert math.degrees(turn(b, a)) == pytest.approx(-20.0)
    mid = between(_pose(yaw=a), _pose(yaw=b), 0.5)
    assert math.degrees(mid.yaw) % 360 == pytest.approx(180.0)


def test_the_glide_starts_where_the_camera_is_and_ends_on_the_scene():
    a = _pose(x=0, distance=1, yaw=0.0, pitch=0.2, fov=40)
    b = _pose(x=10, distance=100, yaw=1.0, pitch=0.8, fov=60)
    assert between(a, b, 0.0) == a
    assert between(a, b, 1.0) == b
    mid = between(a, b, 0.5)
    assert mid.target[0] == pytest.approx(5.0)
    # Distance in proportion: halfway from 1 m to 100 m is 10 m, not 50.
    assert mid.distance == pytest.approx(10.0)
    assert (mid.yaw, mid.pitch, mid.fov_deg) == pytest.approx((0.5, 0.5, 50))


def test_a_glide_of_no_time_or_past_its_end_is_the_scene():
    a, b = _pose(x=0), _pose(x=4)
    assert glide(a, b, 0.0, 0.0) == b
    assert glide(a, b, 2.0, 2.5) == b
    assert glide(a, b, 2.0, 1.0).target[0] == pytest.approx(2.0)


@pytest.mark.parametrize("a_persp,b_persp,during", [
    (True, False, True),        # to a plan: perspective until it arrives
    (False, True, True),        # from a plan: perspective at once
    (False, False, False),      # plan to elevation: parallel all the way
    (True, True, True)])
def test_the_glide_is_parallel_only_between_two_parallel_scenes(
        a_persp, b_persp, during):
    a, b = _pose(perspective=a_persp), _pose(x=5, perspective=b_persp)
    assert between(a, b, 0.0).perspective is a_persp
    assert between(a, b, 0.5).perspective is during
    assert between(a, b, 1.0).perspective is b_persp


def test_two_point_holds_only_between_two_two_point_scenes():
    a, b = _pose(two_point=True), _pose(x=3, two_point=False)
    assert between(a, b, 0.5).two_point is False
    assert between(a, b, 1.0).two_point is False
    c = _pose(x=6, two_point=True)
    assert between(a, c, 0.5).two_point is True


def test_close_to_ignores_a_full_turn_and_rounding():
    a = _pose(yaw=0.1)
    assert a.close_to(_pose(yaw=0.1 + 2 * math.pi))
    assert a.close_to(_pose(yaw=0.1 + 1e-9))
    assert not a.close_to(_pose(yaw=0.2))
    assert not a.close_to(_pose(yaw=0.1, perspective=False))


def test_a_run_glides_pauses_and_goes_round():
    start = _pose(x=-1)
    poses = [_pose(x=0), _pose(x=10), _pose(x=20)]
    run = Run(start, poses, transition=2.0, pause=1.0)
    assert run.duration() == pytest.approx(9.0)
    pose, reached = run.at(0.0)
    assert pose == start and reached == -1
    pose, reached = run.at(1.0)                    # gliding to the first
    assert -1 < pose.target[0] < 0 and reached == -1
    assert run.at(2.0) == (poses[0], 0)            # arrived, pausing
    assert run.at(2.9) == (poses[0], 0)
    pose, reached = run.at(4.0)                    # on the way to the second
    assert pose.target[0] == pytest.approx(5.0) and reached == 0
    assert run.at(5.5) == (poses[1], 1)
    assert run.at(8.5) == (poses[2], 2)
    pose, reached = run.at(10.0)                   # round: last → first
    assert pose.target[0] == pytest.approx(10.0) and reached == 2
    assert run.at(11.0) == (poses[0], 0)


def test_a_run_with_no_time_shows_the_first_scene():
    run = Run(_pose(x=-1), [_pose(x=0), _pose(x=1)], 0.0, 0.0)
    assert run.at(5.0) == (run.poses[0], 0)
    assert Run(_pose(), [], 1.0, 1.0).at(3.0)[1] == -1


# ---- The settings -------------------------------------------------------------
def test_settings_default_and_write_nothing_when_untouched():
    anim = SceneAnimation()
    assert (anim.enabled, anim.transition, anim.pause) == \
        (True, DEFAULT_TRANSITION, DEFAULT_PAUSE)
    assert anim.to_dict() == {}
    assert anim.glide_seconds() == DEFAULT_TRANSITION
    assert SceneAnimation(enabled=False).glide_seconds() == 0.0


def test_settings_round_trip_and_refuse_nonsense():
    anim = SceneAnimation(enabled=False, transition=3.5, pause=0.0)
    assert SceneAnimation.from_dict(anim.to_dict()) == anim
    odd = SceneAnimation.from_dict({"transition": "x", "pause": -4})
    assert odd.transition == DEFAULT_TRANSITION and odd.pause == 0.0
    assert SceneAnimation(transition=2000).transition == MAX_SECONDS
    assert SceneAnimation(transition=float("nan")).transition == \
        DEFAULT_TRANSITION
    assert SceneAnimation.from_dict(None) == SceneAnimation()


def test_the_document_keeps_its_transition_times(tmp_path):
    from core.scene import Scene
    from formats import igz
    scene = Scene()
    assert scene.animation == SceneAnimation()
    scene.animation = SceneAnimation(transition=4.0, pause=2.5)
    path = tmp_path / "animada.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.animation == SceneAnimation(transition=4.0, pause=2.5)


def test_an_old_document_opens_with_the_default_times(tmp_path):
    from core.scene import Scene
    from formats import igz
    path = tmp_path / "sin-ajustes.igz"
    igz.save_scene(Scene(), path)
    back = Scene()
    back.animation = SceneAnimation(enabled=False)
    igz.load_into(back, path)
    assert back.animation == SceneAnimation()


def test_a_new_drawing_forgets_the_times():
    from core.scene import Scene
    scene = Scene()
    scene.animation = SceneAnimation(pause=5.0)
    scene.clear()
    assert scene.animation == SceneAnimation()


# ---- The player ----------------------------------------------------------------
class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class _Viewport:
    """What the player needs of a viewport: a camera, a scene, update,
    and event filters (a real QWidget for those)."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import QWidget

        from core.camera import OrbitCamera
        from core.scene import Scene
        self.widget = QWidget()
        self.camera = OrbitCamera()
        self.scene = Scene()
        self.updates = 0

    def update(self) -> None:
        self.updates += 1

    def installEventFilter(self, obj) -> None:  # noqa: N802
        self.widget.installEventFilter(obj)

    def removeEventFilter(self, obj) -> None:  # noqa: N802
        self.widget.removeEventFilter(obj)


@pytest.fixture
def rig():
    from PySide6.QtCore import QObject

    from views.scene_player import ScenePlayer
    window = QObject()
    window.viewport = _Viewport()
    clock = _Clock()
    player = ScenePlayer(window, clock=clock)
    yield window, player, clock
    player.cancel()


def _view(name, view="top", x=0.0):
    from PySide6.QtGui import QVector3D

    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    from core.scene import Scene
    cam = OrbitCamera()
    cam.set_view(view)
    cam.target = QVector3D(x, 0, 0)
    return SavedView.capture(name, Scene(), cam)


def test_a_glide_moves_the_camera_bit_by_bit_and_arrives(rig):
    window, player, clock = rig
    cam = window.viewport.camera
    view = _view("Planta", "top", x=8.0)
    arrived = []
    assert player.glide_to(view, 2.0, arrived.append)
    assert player.is_active() and not player.is_playing()
    clock.now += 1.0
    player.tick()
    assert 0.0 < cam.target.x() < 8.0                # halfway, not there yet
    assert arrived == []
    clock.now += 1.5
    player.tick()
    assert cam.target.x() == pytest.approx(8.0)
    assert cam.pitch == pytest.approx(view.pitch)
    assert arrived == [view] and not player.is_active()
    assert window.viewport.updates == 2


def test_no_glide_without_time_or_when_already_there(rig):
    window, player, _clock = rig
    view = _view("Planta")
    assert not player.glide_to(view, 0.0, lambda v: None)
    view.apply_camera(window.viewport.camera)
    assert not player.glide_to(view, 2.0, lambda v: None)
    assert not player.is_active()


def test_moving_the_camera_mid_glide_stops_it_where_it_is(rig):
    window, player, clock = rig
    cam = window.viewport.camera
    view = _view("Planta", x=8.0)
    arrived = []
    player.glide_to(view, 2.0, arrived.append)
    clock.now += 0.5
    player.tick()
    cam.yaw += 0.4                               # the user orbits
    taken = Pose.of_camera(cam)
    clock.now += 0.5
    player.tick()
    assert not player.is_active()
    assert Pose.of_camera(cam) == taken          # left where the user put it
    assert arrived == [view]                     # its layers and style come


@pytest.mark.parametrize("kind", ["press", "wheel", "esc"])
def test_a_click_the_wheel_or_esc_in_the_view_stops_it(rig, kind):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
    window, player, clock = rig
    view = _view("Planta", x=8.0)
    player.glide_to(view, 2.0, lambda v: None)
    if kind == "press":
        ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5),
                         QPointF(5, 5), Qt.MiddleButton, Qt.MiddleButton,
                         Qt.NoModifier)
    elif kind == "wheel":
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                         QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                         Qt.NoScrollPhase, False)
    else:
        ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    # Straight to the player's filter: in a long run of test files, a
    # window an earlier file left behind keeps an application-wide key
    # filter that may take Esc first (the CI's sixth batch did).
    eaten = player.eventFilter(window.viewport.widget, ev)
    assert not player.is_active()
    assert eaten is (kind == "esc")          # Esc is the player's alone


def test_the_player_watches_the_viewport_while_it_moves(rig):
    """The filter is on the viewport only while a glide or a run is on."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    window, player, _clock = rig

    def press():
        QApplication.sendEvent(window.viewport.widget, QMouseEvent(
            QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    player.glide_to(_view("Planta", x=8.0), 2.0, lambda v: None)
    press()
    assert not player.is_active()
    arrived = []
    player.glide_to(_view("Alzado", "front", x=-8.0), 2.0, arrived.append)
    player.cancel()
    press()                                  # nothing to stop, nothing done
    assert arrived == [] and not player.is_active()


def test_another_project_in_front_stops_it(rig):
    window, player, clock = rig
    player.glide_to(_view("Planta", x=8.0), 2.0, lambda v: None)
    window.viewport = _Viewport()
    clock.now += 0.5
    player.tick()
    assert not player.is_active()


def test_a_new_scene_mid_glide_takes_over_without_the_old_ones_state(rig):
    window, player, clock = rig
    first, second = _view("A", x=8.0), _view("B", "front", x=-8.0)
    arrived = []
    player.glide_to(first, 2.0, arrived.append)
    clock.now += 0.5
    player.tick()
    assert player.glide_to(second, 2.0, arrived.append)
    clock.now += 3.0
    player.tick()
    assert arrived == [second]


def test_play_runs_through_every_scene_in_turn(rig):
    window, player, clock = rig
    views = [_view("A", x=0.0), _view("B", "front", x=10.0),
             _view("C", "right", x=20.0)]
    window.viewport.scene.saved_views = list(views)
    reached = []
    assert player.play(views, 1, 1.0, 1.0, reached.append)
    assert player.is_playing()
    for _ in range(14):                       # 7 s in half-second frames
        clock.now += 0.5
        player.tick()
    # From the scene after the one shown (index 1 → B), round to A again.
    assert [v.name for v in reached] == ["B", "C", "A", "B"]
    assert player.is_playing()
    player.stop()
    assert not player.is_active()


def test_play_stops_when_its_next_scene_was_deleted(rig):
    window, player, clock = rig
    views = [_view("A", x=0.0), _view("B", x=10.0)]
    window.viewport.scene.saved_views = [views[0]]     # B deleted meanwhile
    reached = []
    player.play(views, 0, 1.0, 0.0, reached.append)
    for _ in range(6):
        clock.now += 0.5
        player.tick()
    assert [v.name for v in reached] == ["A"]
    assert not player.is_active()


def test_play_with_a_parallel_scene_does_not_stop_itself(rig):
    """Arriving at a parallel scene switches the projection: that is the
    player's own doing, not the user taking the view back."""
    window, player, clock = rig
    plan = _view("Planta", "top", x=5.0)
    plan.perspective = False
    views = [plan, _view("Vista", "iso", x=0.0)]
    window.viewport.scene.saved_views = list(views)

    def arrive(view):
        view.apply_state(window.viewport.scene)
    player.play(views, 0, 1.0, 1.0, arrive)
    for _ in range(5):
        clock.now += 0.5
        player.tick()
    assert player.is_playing()


# ---- In the window ------------------------------------------------------------
@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w.scene_player.cancel()
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _scenes(win, *specs):
    from core.saved_views import SavedView
    cam = win.viewport.camera
    for name, view, hidden in specs:
        cam.set_view(view)
        scene = win.viewport.scene
        for ly in scene.layers:
            ly.visible = ly.name not in hidden
        scene.saved_views.append(SavedView.capture(name, scene, cam))
    win.tray.scenes.refresh()


def _visible(win):
    """Make the window's checks believe the viewport is on screen (the
    tests run with the window unshown, where a scene still jumps)."""
    win.viewport.isVisible = lambda: True


def _with_layer(win, name):
    from core.layers import Layer
    win.viewport.scene.layers.append(Layer(name))


def test_a_scene_tab_glides_and_its_layers_come_on_arrival(win):
    _with_layer(win, "Muebles")
    _scenes(win, ("Planta", "top", {"Muebles"}), ("Vista", "iso", set()))
    _visible(win)
    clock = _Clock()
    win.scene_player._clock = clock
    win.viewport.camera.set_view("iso")
    win._scene_tabs.tabs.tabBarClicked.emit(0)
    player = win.scene_player
    assert player.is_active()
    assert win._scene_tabs.tabs.currentIndex() == 0      # marked at once
    muebles = [ly for ly in win.viewport.scene.layers
               if ly.name == "Muebles"][0]
    assert muebles.visible                     # not yet: still on the way
    clock.now += 1.0
    player.tick()
    assert muebles.visible
    clock.now += 2.0
    player.tick()
    assert not player.is_active()
    assert not muebles.visible                 # arrived: the plan's layers
    top = type(win.viewport.camera)()
    top.set_view("top")
    assert win.viewport.camera.pitch == pytest.approx(top.pitch)


def test_with_transitions_off_a_scene_still_jumps(win):
    _scenes(win, ("Planta", "top", set()))
    _visible(win)
    win.viewport.scene.animation = SceneAnimation(enabled=False)
    win.viewport.camera.set_view("iso")
    win._scene_tabs.tabs.tabBarClicked.emit(0)
    assert not win.scene_player.is_active()
    top = type(win.viewport.camera)()
    top.set_view("top")
    assert win.viewport.camera.pitch == pytest.approx(top.pitch)


def test_next_and_previous_scene_go_round_the_ends(win):
    _scenes(win, ("A", "top", set()), ("B", "front", set()),
            ("C", "right", set()))
    # Qt marks the first tab as the scenes come: «next» is the one after
    # the scene underlined, as the row shows it.
    assert win._scene_tabs.tabs.currentIndex() == 0
    shown = []
    win.tray.scenes.show_view = lambda v, animate=True: (
        shown.append(v.name), win._scene_tabs.mark_view(v))
    win.step_scene(1)
    win.step_scene(1)
    win.step_scene(1)
    win.step_scene(1)
    win.step_scene(-1)
    assert shown == ["B", "C", "A", "B", "A"]


def test_play_from_the_menu_and_stop_follows_the_menu(win):
    _scenes(win, ("A", "top", set()), ("B", "front", set()))
    win.play_scenes(True)
    assert win.scene_player.is_playing()
    assert win._act_play_scenes.isChecked()
    win.play_scenes(False)
    assert not win.scene_player.is_active()
    assert not win._act_play_scenes.isChecked()


def test_play_without_scenes_says_why(win):
    win.play_scenes(True)
    assert not win.scene_player.is_active()
    assert not win._act_play_scenes.isChecked()
    from core.i18n import tr
    assert win.statusBar().currentMessage().startswith(
        tr("This project has no scenes to play: keep a view as a scene "
           "first (Scenes panel, «+ Scene»).")[:20])


def test_the_scene_menus_offer_play_then_stop(win):
    _scenes(win, ("A", "top", set()), ("B", "front", set()))
    from core.i18n import tr
    texts = [a.text() for a in win._build_scene_tab_menu(0).actions()]
    assert tr("Play") in texts
    texts = [a.text() for a in win._build_scene_bar_menu().actions()]
    assert tr("Play") in texts
    win.play_scenes(True)
    texts = [a.text() for a in win._build_scene_bar_menu().actions()]
    assert tr("Stop") in texts and tr("Play") not in texts


def test_page_up_and_down_are_no_other_commands_shortcut(win):
    from PySide6.QtGui import QAction, QKeySequence
    from core.i18n import tr
    for keys, label in (("PgDown", "Next Scene"), ("PgUp", "Previous Scene")):
        seq = QKeySequence(keys)
        owners = {a.text() for a in win.findChildren(QAction)
                  if seq in a.shortcuts()}
        assert owners == {tr(label)}


def test_the_settings_change_the_document(win, monkeypatch):
    import views.scene_player as sp
    before = win.viewport.scene.version
    monkeypatch.setattr(sp, "ask_animation_settings",
                        lambda parent, cur: SceneAnimation(transition=5.0))
    win.ask_animation()
    assert win.viewport.scene.animation.transition == 5.0
    assert win.viewport.scene.version > before
    # Cancelled, or the same again: nothing changes.
    after = win.viewport.scene.version
    monkeypatch.setattr(sp, "ask_animation_settings", lambda p, c: None)
    win.ask_animation()
    assert win.viewport.scene.version == after


def test_the_settings_dialog_reads_and_returns_the_times(monkeypatch):
    from PySide6.QtWidgets import QDialog, QDoubleSpinBox

    import views.scene_player as sp

    def fake_exec(dlg):
        dlg.findChild(QDoubleSpinBox, "animation_transition").setValue(3.0)
        dlg.findChild(QDoubleSpinBox, "animation_pause").setValue(0.5)
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, "exec", fake_exec)
    got = sp.ask_animation_settings(None, SceneAnimation())
    assert got == SceneAnimation(transition=3.0, pause=0.5)


def test_the_menu_turns_the_transitions_off_and_on(win):
    """Camera ▸ Animation ▸ Scene Transitions: one click, no dialog."""
    _scenes(win, ("Planta", "top", set()))
    _visible(win)
    act = win._act_scene_transitions
    assert act.isChecked()
    before = win.viewport.scene.version
    act.trigger()                                   # off
    assert not win.viewport.scene.animation.enabled
    assert win.viewport.scene.version > before      # the project changed
    win.viewport.camera.set_view("iso")
    win._scene_tabs.tabs.tabBarClicked.emit(0)
    assert not win.scene_player.is_active()         # it jumped
    act.trigger()                                   # on again
    assert win.viewport.scene.animation.enabled
    win.viewport.camera.set_view("iso")
    win._scene_tabs.tabs.tabBarClicked.emit(0)
    assert win.scene_player.is_active()             # it glides


def test_turning_them_off_keeps_the_times_and_stops_a_glide(win):
    _scenes(win, ("Planta", "top", set()))
    _visible(win)
    win.viewport.scene.animation = SceneAnimation(transition=4.0, pause=0.5)
    win.viewport.camera.set_view("iso")
    win._scene_tabs.tabs.tabBarClicked.emit(0)
    assert win.scene_player.is_active()
    win.set_scene_transitions(False)
    assert not win.scene_player.is_active()
    assert win.viewport.scene.animation == SceneAnimation(
        enabled=False, transition=4.0, pause=0.5)


def test_the_toggle_shows_the_choice_of_the_project_in_front(win):
    win.viewport.scene.animation = SceneAnimation(enabled=False)
    win._sync_animation_menu()
    assert not win._act_scene_transitions.isChecked()
    win.viewport.scene.animation = SceneAnimation()
    win._refresh_scene_tabs()
    assert win._act_scene_transitions.isChecked()


# ---- The video ---------------------------------------------------------------
def _need_video():
    """Skip where Qt Multimedia cannot load. Not only when it is missing:
    on a Linux machine without PulseAudio (the CI's) the module is there
    but its import fails on libpulse.so.0 — an ImportError that
    ``pytest.importorskip`` does not treat as a reason to skip."""
    from views.video_export import multimedia_available
    if not multimedia_available():
        pytest.skip("Qt Multimedia does not load here")


def test_a_video_shows_the_first_scene_glides_and_ends_on_the_last():
    from core.scene_animation import video_at, video_frame_count, video_seconds
    poses = [_pose(x=0), _pose(x=10), _pose(x=20)]
    assert video_seconds(3, 2.0, 1.0) == pytest.approx(7.0)   # 1 + 2·(2+1)
    assert video_frame_count(3, 2.0, 1.0, 10) == 71
    assert video_at(poses, 2.0, 1.0, 0.0) == (poses[0], 0)
    assert video_at(poses, 2.0, 1.0, 0.9) == (poses[0], 0)
    pose, shown = video_at(poses, 2.0, 1.0, 2.0)      # halfway to the second
    assert pose.target[0] == pytest.approx(5.0) and shown == 0
    assert video_at(poses, 2.0, 1.0, 3.5) == (poses[1], 1)
    assert video_at(poses, 2.0, 1.0, 7.0) == (poses[2], 2)
    assert video_at(poses, 2.0, 1.0, 99.0) == (poses[2], 2)   # no round
    assert video_frame_count(0, 2.0, 1.0, 30) == 0
    assert video_frame_count(1, 2.0, 0.0, 30) == 1
    with pytest.raises(ValueError):
        video_at([], 1.0, 1.0, 0.0)


def test_the_mkv_writer_writes_a_matroska_file(tmp_path):
    _need_video()
    from PySide6.QtGui import QColor, QImage

    from views.video_export import MkvWriter
    path = tmp_path / "prueba.mkv"
    writer = MkvWriter(path, 65, 48, 10)               # odd → even
    assert (writer.width, writer.height) == (64, 48)
    for i in range(12):
        img = QImage(64, 48, QImage.Format_ARGB32)
        img.fill(QColor.fromHsv(i * 30, 200, 200))
        writer.write(img)
    writer.close()
    assert writer.frames == 12
    data = path.read_bytes()
    assert data[:4] == b"\x1a\x45\xdf\xa3"            # Matroska (EBML)
    assert len(data) > 1000


def test_a_discarded_video_leaves_no_file(tmp_path):
    _need_video()
    from PySide6.QtGui import QImage

    from views.video_export import MkvWriter
    path = tmp_path / "a-medias.mkv"
    writer = MkvWriter(path, 64, 48, 10)
    writer.write(QImage(64, 48, QImage.Format_ARGB32))
    writer.discard()
    assert not path.exists()


def _fake_render(win, log):
    """The tests' window is never shown, so it has no GL: each frame is
    a plain picture, and the log keeps what the camera and layers were."""
    from PySide6.QtGui import QImage

    def render(width, height=None, overlays=True, annotations_only=False):
        cam = win.viewport.camera
        log.append((round(cam.pitch, 3), cam.perspective, cam.aspect,
                    tuple(ly.visible for ly in win.viewport.scene.layers)))
        img = QImage(width, height, QImage.Format_ARGB32)
        img.fill(0xFF808080)
        return img
    win.viewport.render_image = render


def test_export_video_renders_every_frame_and_puts_the_view_back(
        win, tmp_path):
    _need_video()
    from views.video_export import export_video
    _with_layer(win, "Muebles")
    _scenes(win, ("Vista", "iso", set()), ("Planta", "top", {"Muebles"}))
    win.viewport.scene.animation = SceneAnimation(transition=1.0, pause=0.5)
    cam = win.viewport.camera
    cam.set_view("front")
    before = Pose.of_camera(cam), cam.aspect
    layers = [ly.visible for ly in win.viewport.scene.layers]
    log = []
    _fake_render(win, log)
    seen = []
    path = tmp_path / "casa.mkv"
    frames = export_video(win, path, 320, 180, 10,
                          lambda d, t: seen.append((d, t)))
    # 0.5 + (1 + 0.5) = 2 s at 10 fps, and the last frame: 21.
    assert frames == 21 and seen[-1] == (21, 21) and len(log) == 21
    assert path.read_bytes()[:4] == b"\x1a\x45\xdf\xa3"
    assert all(abs(aspect - 320 / 180) < 1e-9 for _p, _q, aspect, _l in log)
    muebles = [ly.name for ly in win.viewport.scene.layers].index("Muebles")
    assert log[0][3][muebles] is True              # the first scene's layers
    assert log[-1][3][muebles] is False            # the plan's, on arrival
    assert log[10][3][muebles] is True             # not while gliding
    # The view is as it was: camera, aspect and layers.
    assert Pose.of_camera(cam) == before[0] and cam.aspect == before[1]
    assert [ly.visible for ly in win.viewport.scene.layers] == layers


def test_cancelling_the_video_removes_the_file(win, tmp_path):
    _need_video()
    from views.video_export import export_video
    _scenes(win, ("A", "iso", set()), ("B", "top", set()))
    _fake_render(win, [])
    path = tmp_path / "cancelado.mkv"
    assert export_video(win, path, 160, 90, 10, lambda d, t: d < 3) == 0
    assert not path.exists()


def test_no_scenes_no_video(win, tmp_path):
    from views.video_export import VideoError, export_video
    with pytest.raises(VideoError):
        export_video(win, tmp_path / "nada.mkv", 160, 90, 10)
    assert not (tmp_path / "nada.mkv").exists()


def test_the_video_options_offer_sizes_fps_and_the_length(win):
    from views.video_export import VideoOptionsDialog
    _scenes(win, ("A", "iso", set()), ("B", "top", set()),
            ("C", "front", set()))
    dlg = VideoOptionsDialog(win, win.viewport.scene, (1001, 601))
    (size, fps) = dlg.choice()
    assert size == (1920, 1080) and fps == 30
    sizes = [dlg.size_box.itemData(i) for i in range(dlg.size_box.count())]
    assert (1000, 600) in sizes                     # like the view, even
    # 3 scenes, 2 s glide + 1 s pause: 1 + 2·3 = 7 s, 211 frames at 30.
    assert "7.0" in dlg.length.text() and "211" in dlg.length.text()
    dlg.fps_box.setCurrentIndex(dlg.fps_box.findData(24))
    assert "169" in dlg.length.text()


def test_the_video_is_in_file_export_and_in_the_animation_menu(win):
    from PySide6.QtWidgets import QMenu

    from core.i18n import tr
    entries = {(m.title(), a.text()) for m in win.findChildren(QMenu)
               for a in m.actions()}
    assert (tr("Export"), tr("Scenes as Video (.mkv)…")) in entries
    assert (tr("Animation"), tr("Export Video (.mkv)…")) in entries


def _without_multimedia(monkeypatch):
    """What the CI's Linux machine does: the import of Qt Multimedia
    fails (there, on libpulse.so.0)."""
    import sys
    monkeypatch.setitem(sys.modules, "PySide6.QtMultimedia", None)


def test_without_multimedia_the_writer_says_why(monkeypatch, tmp_path):
    from views.video_export import (MkvWriter, VideoError,
                                    multimedia_available, no_video_message)
    _without_multimedia(monkeypatch)
    assert not multimedia_available()
    with pytest.raises(VideoError) as err:
        MkvWriter(tmp_path / "x.mkv", 64, 48, 10)
    assert str(err.value) == no_video_message()
    assert not (tmp_path / "x.mkv").exists()


def test_without_multimedia_the_export_says_so_and_asks_nothing(
        win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    import views.video_export as ve
    from views.filedialogs import file_dialogs
    _scenes(win, ("A", "iso", set()))
    _without_multimedia(monkeypatch)
    said, asked = [], []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda *a, **k: said.append(a[2]))
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda *a, **k: asked.append(a) or ("", ""))
    ve.run_export(win)
    assert said == [ve.no_video_message()] and asked == []
