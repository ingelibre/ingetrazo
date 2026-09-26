# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IngeTrazo main window: toolbar, viewport, side panels, status bar.

Owns the open document path and dispatches File menu actions (New, Open,
Save, Save As) onto :mod:`formats.igz`.
"""
from __future__ import annotations

from views import prompts as _prompts

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSettings, QEvent, QCoreApplication, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QVector3D
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStatusBar,
    QToolBar,
    QWidget,
)

from core.i18n import (LANGUAGE_NAMES, available_languages, current_language,
                       set_language, tr)
from views.theme import style as theme_style
from core.units import fmt_pair
from views.filedialogs import file_dialogs
from core.version import __version__
from core.group import Group
from core.history import (
    ExplodeGroupCommand,
    HealOverlapsCommand,
    MakeGroupCommand,
    RebuildPlanarFacesCommand,
    SnapshotImport,
    SnapshotMutation,
)
from core.mesh import Edge, Face
from formats import igz as igz_format
from formats import dae as dae_format
from formats import obj as obj_format
from formats import ifc as ifc_format
from formats import stl as stl_format
from formats import gltf as gltf_format
from formats import skp_out as skp_out_format
from tools.arc import CenterArcTool, ArcTool, ThreePointArcTool
from tools.circle import CircleTool, PolygonTool
from tools.dimension import DimensionTool
from tools.eraser import EraserTool
from tools.geopath import GeoPathTool
from tools.line import LineTool
from tools.protractor import ProtractorTool
from tools.tape import TapeMeasureTool
from tools.text import TextTool
from tools.move import MoveTool
from tools.rotate import RotateTool
from tools.scale import ScaleTool
from tools.fillet import FilletTool
from tools.followme import FollowMeTool
from tools.rotated_rectangle import RotatedRectangleTool
from tools.offset import OffsetTool
from tools.texture_position import TexturePositionTool
from tools.walkthrough import (FirstPersonTool, LookAroundTool,
                               PositionCameraTool, WalkTool)
from tools.paint import PaintTool
from tools.paste import PasteTool
from tools.arc import PieTool
from tools.flip import FlipTool
from tools.freehand import FreehandTool
from tools.section import SectionPlaneTool
from tools.pushpull import PushPullTool
from tools.rectangle import RectangleTool
from tools.select import SelectTool
from views.tray import BimTray, GeorefTray, Tray
from views.icons import tool_icon
from views.viewport import Viewport


IGZ_FILE_FILTER = "IngeTrazo document (*.igz);;All files (*)"



def _obj_parts(temp):
    """The container a multi-part OBJ imported as, its pieces' facet seams
    softened like any library model's, or ``None`` for a single-piece file
    (which the callers keep handling as one mesh)."""
    if not temp.groups or not temp.groups[0].children:
        return None
    from formats.fuse import soften_smooth_edges
    group = temp.groups[0]
    for kid in group.children:
        soften_smooth_edges(kid.mesh, cos_threshold=0.55)
    return group

class MainWindow(QMainWindow):
    """Top-level IngeTrazo window."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(1280, 800)

        self._tools = {
            "select": SelectTool(),
            "line": LineTool(),
            "freehand": FreehandTool(),
            "rectangle": RectangleTool(),
            "rotated_rect": RotatedRectangleTool(),
            "circle": CircleTool(),
            "polygon": PolygonTool(),
            "arc": ArcTool(),
            "arc3": ThreePointArcTool(),
            "center_arc": CenterArcTool(),
            "pie": PieTool(),
            "pushpull": PushPullTool(),
            "offset": OffsetTool(),
            "move": MoveTool(),
            "rotate": RotateTool(),
            "scale": ScaleTool(),
            "flip": FlipTool(),
            "followme": FollowMeTool(),
            "fillet": FilletTool(),
            # Entered from a textured face's right-click menu, never from
            # the toolbar (SketchUp's Texture ▸ Position).
            "texture_position": TexturePositionTool(),
            "paint": PaintTool(),
            "dimension": DimensionTool(),
            "eraser": EraserTool(),
            "tape": TapeMeasureTool(),
            "protractor": ProtractorTool(),
            "text": TextTool(),
            # Georef trace (Track G) — draws a GeoPath, never mesh geometry.
            "geopath": GeoPathTool(),
            # SketchUp's Tools ▸ Section Plane (core/section.py).
            "section": SectionPlaneTool(),
            # SketchUp's Camera ▸ Position Camera / Walk / Look Around
            # (tools/walkthrough.py) — Rafael's «pasitos» for interiors.
            "position_camera": PositionCameraTool(),
            "walk": WalkTool(),
            "look_around": LookAroundTool(),
            # Walking as a game plays it (W/A/S/D + mouse look), beside
            # SketchUp's Walk rather than instead of it.
            "first_person": FirstPersonTool(),
        }
        # SketchUp's Solid Tools (tools/solid_tools.py, core/solids.py).
        from tools.solid_tools import SOLID_TOOLS
        for key, cls in SOLID_TOOLS:
            self._tools[key] = cls()
        # Right-click ▸ Change Axes (issue #44) — no toolbar button, as in
        # SketchUp.
        from tools.change_axes import ChangeAxesTool
        self._tools["change_axes"] = ChangeAxesTool()
        # Tag each tool with its icon key so the viewport can turn the mouse
        # pointer into the tool's icon (SketchUp-style cursors).
        for key, tool in self._tools.items():
            if not getattr(tool, "icon", None):
                tool.icon = key
        self._tool_actions: dict[str, QAction] = {}

        self._current_path: Optional[Path] = None
        # Name of an IMPORTED file (.skp/.dae) shown in the title until the
        # model is saved as .igz — opening a SketchUp file natively should
        # read as opening THAT file (user request).
        self._import_name: Optional[str] = None
        self._saved_version: int = 0

        self._setup_ui()
        # The user's own keyboard shortcuts over the factory ones (#138).
        from views import shortcuts as _shortcuts
        _shortcuts.remember_defaults(self)
        _shortcuts.apply_user_shortcuts(self)
        self._activate_tool("select")
        self._apply_new_document_units()
        self._insert_scale_figure()
        self._update_title()

    # ---- Layout -------------------------------------------------------------
    def _setup_ui(self) -> None:
        self.viewport = Viewport(self)
        try:                                        # issue #56
            self.viewport.history.max_steps = int(
                QSettings().value("general/undo_steps", 200))
        except (TypeError, ValueError):
            self.viewport.history.max_steps = 200
        self.viewport.glReady.connect(self._on_gl_ready)
        self.setCentralWidget(self.viewport)

        self._extension_docks: list = []   # side panels added by plugins
        self._build_toolbar()
        self._build_tray()
        self._build_menubar()
        self._build_statusbar()

        self._saved_version = self.viewport.scene.version
        self.viewport.sceneVersionChanged.connect(self._on_scene_version_changed)

        # Toolbar/dock layout: the user's own arrangement survives sessions
        # (saved on close); a fresh profile starts from the factory layout
        # blob when one is shipped. Restored AFTER every toolbar and dock
        # exists — saveState matches them by objectName.
        st = QSettings()
        state = st.value("ui/window_state")
        if state is None:
            from core.paths import app_root
            factory = app_root() / "resources" / "ui" / "default_layout.state"
            if factory.is_file():
                state = factory.read_bytes()
        if state:
            self.restoreState(state)
        self._show_default_trays(st)
        self._place_new_toolbars(st)
        # Packed on the first show (see showEvent): the toolbars have no
        # geometry to read their order from until the window is laid out.
        self._toolbars_packed = False
        geo = st.value("ui/window_geometry")
        if geo:
            self.restoreGeometry(geo)

        self._setup_autosave()
        # An untitled recovery slot on disk means the last session died with
        # unsaved work (a clean exit clears it) — offer it back, once the
        # window is up (QTimer 0: not during __init__, the viewport isn't
        # ready to paint a restored scene yet).
        from core import autosave
        if autosave.pending(None):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._offer_untitled_recovery)

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().showEvent(event)
        if not getattr(self, "_toolbars_packed", True):
            from PySide6.QtCore import QTimer
            self._toolbars_packed = True
            QTimer.singleShot(0, self._pack_toolbars)
        if not getattr(self, "_ndof_connected", False):
            self._connect_ndof()

    # ---- 3D mouse (issue #108) ----------------------------------------------
    def _route_window_toggle(self, name: str, own):
        """A slot for a Window-menu toggle (clean screen, sidebar) that acts
        on the window being worked in. On macOS the menu bar is global: its
        Cmd+0 answered for the MODEL window even with the sheet composer in
        front — «al pulsarlo me lleva a la ventana del Modelador y le oculta
        todo» (#114). When the composer is the active window, the press goes
        to its own action and this one keeps its state."""
        def slot(on: bool) -> None:
            from PySide6.QtWidgets import QApplication
            comp = getattr(self, "_composer", None)
            if comp is not None and QApplication.activeWindow() is comp:
                mine = getattr(self, name)
                mine.blockSignals(True)
                mine.setChecked(not on)
                mine.blockSignals(False)
                getattr(comp, name).toggle()
                return
            own(on)
        return slot

    def _connect_ndof(self) -> None:
        """Listen to the 3D mouse, if the machine has one (spacenavd on
        Linux, Raw Input on Windows). Silent when there is none."""
        self._ndof_connected = True
        try:
            from views.ndof_input import shared_input
            dev = shared_input()
            dev.motion.connect(self._on_ndof_motion)
            dev.button.connect(self._on_ndof_button)
        except Exception as exc:  # noqa: BLE001 — never block the window
            import sys as _sys
            print(f"IngeTrazo: 3D mouse unavailable ({exc!r})",
                  file=_sys.stderr)

    def _on_ndof_motion(self, sample, dt: float) -> None:
        # Only the window being worked in moves (New Window makes several).
        if not self.isActiveWindow():
            return
        from core.ndof import apply_ndof
        from views.ndof_input import current_settings
        vp = self.viewport
        if apply_ndof(vp.camera, sample, dt, vp.height(), current_settings()):
            vp.update()

    def _on_ndof_button(self, number: int, down: bool) -> None:
        # The two buttons every model has: both fit the model, SketchUp's
        # default for the right one and the most useful single command.
        if down and number in (0, 1) and self.isActiveWindow():
            self._on_zoom_extents()

    def _pack_toolbars(self) -> None:
        """Re-seat every docked toolbar so each takes exactly the length of
        what it holds, in the area, order and rows it already has.

        A saved layout (the factory blob or the user's own) stores each
        toolbar's LENGTH along its line, and ``restoreState`` applies it
        whatever the toolbar holds today: the Annotate bar came back 100 px
        longer than its six buttons (saved with bigger icons) and left a
        hole before Walkthrough — the youtuber's fresh install showed the
        walk icons stranded at the bottom of the column, and Marco's too
        (2026-09-20). Removing and adding a toolbar back drops the stored
        length for its size hint, which is all we ever want; nothing here
        lets a toolbar be stretched on purpose."""
        from PySide6.QtCore import Qt
        areas = (Qt.LeftToolBarArea, Qt.RightToolBarArea,
                 Qt.TopToolBarArea, Qt.BottomToolBarArea)
        for area in areas:
            vertical = area in (Qt.LeftToolBarArea, Qt.RightToolBarArea)
            bars = [tb for tb in self.findChildren(QToolBar)
                    if not tb.isFloating() and self.toolBarArea(tb) == area]
            if len(bars) < 2:
                continue
            # rows first, then along the row — so breaks come back in place
            bars.sort(key=(lambda tb: (tb.geometry().x(), tb.geometry().y()))
                      if vertical else
                      (lambda tb: (tb.geometry().y(), tb.geometry().x())))
            seats = [(tb, self.toolBarBreak(tb), tb.isVisibleTo(self))
                     for tb in bars]
            for tb, brk, shown in seats:
                self.removeToolBar(tb)
                if brk:
                    self.addToolBarBreak(area)
                self.addToolBar(area, tb)
                tb.setVisible(shown)

    def _place_new_toolbars(self, st) -> None:
        """A toolbar born after a profile saved its layout is unknown to
        that saved state, so Qt leaves it wherever it was created (the
        top). Put it where the factory layout has it, ONCE, and remember
        that: Marco's own arrangement keeps it from then on.

        Walkthrough (2026-09-19) goes at the left, under Annotate — below
        the 3D Text button, where Marco asked for it."""
        from PySide6.QtCore import Qt
        key = "ui/placed/walkthrough"
        tb = self.toolbars.get("walkthrough")
        if tb is None or st.value(key) is not None:
            return
        if self.toolBarArea(tb) != Qt.LeftToolBarArea:
            self.removeToolBar(tb)
            self.addToolBar(Qt.LeftToolBarArea, tb)
            tb.show()
        st.setValue(key, 1)

    # ---- Auto-save (Preferences ▸ General) ----------------------------------
    def _setup_autosave(self) -> None:
        """(Re)arm the auto-save timer from settings — called at startup and
        by the Preferences dialog after a change."""
        from PySide6.QtCore import QTimer
        timer = getattr(self, "_autosave_timer", None)
        if timer is None:
            timer = self._autosave_timer = QTimer(self)
            timer.timeout.connect(self._on_autosave_tick)
        st = QSettings()
        enabled = str(st.value("general/autosave", "1")) != "0"
        minutes = max(1, min(60, int(st.value("general/autosave_min", 5))))
        timer.stop()
        if enabled:
            timer.start(minutes * 60 * 1000)

    def _on_autosave_tick(self) -> None:
        """Write the recovery slot — only when there is something new to
        keep, and never under the user's hands (a 283k-face save takes real
        time; mid-drag it would read as a freeze)."""
        from PySide6.QtWidgets import QApplication
        # Housekeeping that rides the same slow tick: a clean collection
        # now and then — never mid-gesture (over a big model it is ~0.3 s).
        if getattr(self.viewport, "_last_pos", None) is None:
            import gc
            gc.collect()
        if not self._is_dirty():
            return
        version = self.viewport.scene.version
        if version == getattr(self, "_autosaved_version", None):
            return
        if QApplication.mouseButtons() != Qt.NoButton:
            return                      # try again next tick
        from core import autosave
        try:
            self.viewport.scene.camera_home = self._camera_dict()
            autosave.write(self.viewport.scene, self._current_path)
        except Exception:  # noqa: BLE001 — recovery must never break modeling
            return
        self._autosaved_version = version
        self.statusBar().showMessage(tr("Auto-saved."), 2000)

    def _offer_untitled_recovery(self) -> None:
        from core import autosave
        slot = autosave.pending(None)
        if slot is None:
            return
        answer = QMessageBox.question(
            self, tr("Recovered drawing"),
            tr("The last session ended without saving an untitled drawing "
               "(auto-saved copy found). Recover it?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            autosave.clear(None)
            return
        try:
            igz_format.load_into(self.viewport.scene, slot)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Open failed"), str(exc))
            return
        self.viewport.history.clear()
        self.viewport.reset_texture_cache()
        self._current_path = None
        self._import_name = None
        self._saved_version = -1        # recovered ≠ saved: title shows *
        self.viewport.notify_scene_changed()
        self._sync_style_menu()
        self._sync_section_menu()
        self._update_title()

    def _build_tray(self) -> None:
        # Two role-based right-side docks (tabbed): Properties (what you're
        # working with) and Georef (the location workspace).
        self.tray = Tray(self)
        self.bim_tray = BimTray(self)
        self.georef_tray = GeorefTray(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tray)
        self.addDockWidget(Qt.RightDockWidgetArea, self.bim_tray)
        self.addDockWidget(Qt.RightDockWidgetArea, self.georef_tray)
        self.tabifyDockWidget(self.tray, self.bim_tray)
        self.tabifyDockWidget(self.bim_tray, self.georef_tray)
        # The trays are tabbed: the tab bar already names the active panel,
        # so each dock's own title bar would say the same thing right above
        # it. An empty title-bar widget removes the duplicate (SketchUp-tray
        # look); panels are toggled from the View menu, not dragged around.
        for dock in (self.tray, self.bim_tray, self.georef_tray):
            dock.setTitleBarWidget(QWidget(dock))
        self.tray.raise_()
        self._build_sidebar_handle()
        self.viewport.sceneVersionChanged.connect(
            lambda _v: self.tray.on_scene_changed())
        self.viewport.sceneVersionChanged.connect(
            lambda _v: self.bim_tray.on_scene_changed())
        self.viewport.sceneVersionChanged.connect(
            lambda _v: self.georef_tray.on_scene_changed())

        # Styles, Shadows and Dimension style hang OFF THE TOOLBAR as
        # dropdown panels (user: the lateral bar was drowning, and floating
        # windows felt loose — "¿no hay forma de integrarlo en el
        # toolbar?"). Click the button, the panel drops under it; click
        # outside, it folds away.
        from PySide6.QtWidgets import QToolButton, QWidgetAction
        from views.tray import DimensionStylePanel, ShadowsPanel, StylesPanel
        self.styles_panel = StylesPanel(self)
        self.shadows_panel = ShadowsPanel(self)
        self.dimstyle_panel = DimensionStylePanel(self)
        panels_tb = self._new_toolbar(tr("Panels"), "panels_toolbar")
        for panel, key, title in (
                (self.styles_panel, "styles", tr("Styles")),
                (self.shadows_panel, "shadows", tr("Shadows")),
                (self.dimstyle_panel, "dimension_style", tr("Dimension style"))):
            btn = QToolButton(panels_tb)
            btn.setIcon(tool_icon(key))
            btn.setToolTip(title)
            btn.setPopupMode(QToolButton.InstantPopup)
            btn.setStyleSheet(
                "QToolButton::menu-indicator { image: none; }")
            menu = QMenu(btn)
            wa = QWidgetAction(menu)
            wa.setDefaultWidget(panel)
            menu.addAction(wa)
            btn.setMenu(menu)
            panels_tb.addWidget(btn)
            self._icon_actions.append((btn, key))

        # Terrain profile dock (Track G, G4) — hidden until requested.
        from views.profile_panel import ProfileDock
        self.profile_dock = ProfileDock(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.profile_dock)
        self.profile_dock.hide()
        self.viewport.sceneVersionChanged.connect(
            lambda _v: self.profile_dock.on_scene_changed())
        self.viewport.sceneVersionChanged.connect(
            lambda _v: self._on_surfaces_scene_changed())
        self.viewport.tilesChanged.connect(self._build_terrain)

    def _new_toolbar(self, title: str, object_name: str) -> QToolBar:
        """A separate, independently draggable/floatable icons-only toolbar
        (SketchUp-style — Draw, Modify, View… each move on their own)."""
        from PySide6.QtCore import QSize
        tb = QToolBar(title, self)
        tb.setObjectName(object_name)
        tb.setMovable(True)
        tb.setFloatable(True)
        tb.setAllowedAreas(Qt.AllToolBarAreas)
        from views.icons import toolbar_icon_px
        px = toolbar_icon_px()
        tb.setIconSize(QSize(px, px))
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.addToolBar(Qt.TopToolBarArea, tb)
        from views.icons import style_overflow_button
        style_overflow_button(tb)
        return tb

    def set_toolbar_icon_size(self, px: int) -> None:
        """Icon size for every toolbar — this window's and the composer's
        (open now or later: it reads the setting when it builds). From
        Preferences ▸ General; persisted."""
        from PySide6.QtCore import QSize
        from views.icons import save_toolbar_icon_px
        px = int(px)
        save_toolbar_icon_px(px)
        for tb in self.findChildren(QToolBar):
            tb.setIconSize(QSize(px, px))
        comp = getattr(self, "_composer", None)
        if comp is not None and hasattr(comp, "set_toolbar_icon_size"):
            comp.set_toolbar_icon_size(px)

    def _add_tool_button(self, tb: QToolBar, key: str) -> QAction:
        tool = self._tools[key]
        name = tr(tool.name)
        action = QAction(tool_icon(key), name, self)
        self._icon_actions.append((action, key))
        action.setCheckable(True)
        if tool.shortcut:
            seqs = [QKeySequence(tool.shortcut)]
            alt = getattr(tool, "shortcut_alt", None)
            if alt:
                seqs.append(QKeySequence(alt))
            action.setShortcuts(seqs)
            action.setToolTip(f"{name}  ({tool.shortcut})")
        else:
            action.setToolTip(name)
        action.triggered.connect(lambda _c, k=key: self._activate_tool(k))
        self._tool_group.addAction(action)
        tb.addAction(action)
        self._tool_actions[key] = action
        return action

    def _build_toolbar(self) -> None:
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self.toolbars: dict[str, QToolBar] = {}
        # Icon size: Preferences ▸ General (views.icons.toolbar_icon_px).
        # (action, icon_key) pairs so programmatic icons can be re-drawn when
        # the palette flips (dark ↔ light) at runtime — see changeEvent below.
        self._icon_actions: list[tuple[QAction, str]] = []

        # One toolbar per task, each independently movable (SketchUp).
        layout = [
            ("main", tr("Main"), ["select", "eraser", "paint"]),
            ("draw", tr("Draw"),
             ["line", "freehand", "rectangle", "rotated_rect", "circle",
              "polygon", "arc", "arc3", "center_arc", "pie"]),
            # Push/Pull first (Marco, 2026-09-14), then move, rotate, scale, flip…
            ("modify", tr("Modify"), ["pushpull", "move", "rotate", "scale", "flip", "followme", "offset", "fillet"]),
            ("annotate", tr("Annotate"), ["tape", "protractor", "dimension", "text", "geopath"]),
            ("sections", tr("Sections"), ["section"]),
            # SketchUp's Solid Tools toolbar, in its help's order.
            ("solids", tr("Solid Tools"),
             ["outer_shell", "solid_union", "solid_subtract", "solid_trim",
              "solid_intersect", "solid_split"]),
            # SketchUp's Walkthrough toolbar, in its order.
            ("walkthrough", tr("Walkthrough"),
             ["position_camera", "walk", "look_around", "first_person"]),
        ]
        for oname, title, keys in layout:
            tb = self._new_toolbar(title, oname)
            self.toolbars[oname] = tb
            for key in keys:
                self._add_tool_button(tb, key)

        # Save, first on the Main bar (the composer's Sheet bar has had it
        # since the start; Marco, 2026-09-14: «el icono de guardar también en
        # modelo, antes de la flechita»). The shortcut stays on the menu
        # action, so Ctrl+S never becomes ambiguous.
        main_tb = self.toolbars["main"]
        act_save = QAction(tool_icon("save"), tr("Save"), self)
        act_save.setToolTip(tr("Save the document (Ctrl+S)"))
        act_save.triggered.connect(self._on_save)
        first = main_tb.actions()[0] if main_tb.actions() else None
        main_tb.insertAction(first, act_save)
        main_tb.insertSeparator(first)
        self._icon_actions.append((act_save, "save"))
        self._act_save_tb = act_save

        # SketchUp keeps a pipette beside the material you paint with: it is
        # how you FIND the eyedropper. Alt+click does the same for people who
        # know the modifier — Marco asked for the button because that is what
        # he reaches for ("hay un icono al costado de pintura").
        self._act_eyedropper = QAction(
            tool_icon("eyedropper"), tr("Sample material"), self)
        self._act_eyedropper.setCheckable(True)
        self._act_eyedropper.setToolTip(tr(
            "Sample material — click a face to pick up its paint or texture "
            "(or hold Alt with the Paint tool)"))
        self._act_eyedropper.toggled.connect(self._on_toggle_eyedropper)
        main_tb.addAction(self._act_eyedropper)
        self._icon_actions.append((self._act_eyedropper, "eyedropper"))

        # The Sections toolbar carries SketchUp's three display toggles next
        # to the tool: Display Section Planes / Cuts / Fill. Created here
        # (the menubar builds later and reuses the same actions).
        sec_tb = self.toolbars["sections"]
        sec_tb.addSeparator()

        def _sec_toggle(key: str, text: str, slot):
            act = QAction(tool_icon(key), text, self)
            act.setCheckable(True)
            act.setChecked(True)
            act.setToolTip(text)
            act.toggled.connect(slot)
            self._icon_actions.append((act, key))
            sec_tb.addAction(act)
            return act

        self._act_show_splanes = _sec_toggle(
            "section_planes", tr("Section Planes"),
            lambda on: self._set_section_visibility("show_section_planes", on))
        self._act_show_scuts = _sec_toggle(
            "section_cuts", tr("Section Cuts"),
            lambda on: self._set_section_visibility("show_section_cuts", on))
        self._act_section_fill = _sec_toggle(
            "section_fill", tr("Section Fill"),
            lambda on: self._set_style_field("section_fill", on))

        # 3D Text opens a dialog (it's a one-shot action, not a checkable tool),
        # so it gets its own button on the Annotate bar next to the 2D Text tool.
        self._act_3dtext = QAction(tool_icon("text3d"), tr("3D Text"), self)
        self._act_3dtext.setToolTip(tr("3D Text — build extruded text as a solid"))
        self._act_3dtext.triggered.connect(self._on_insert_3d_text)
        self.toolbars["annotate"].addAction(self._act_3dtext)
        self._icon_actions.append((self._act_3dtext, "text3d"))

        # Spacebar returns to Select, like SketchUp's pointer ("S" now
        # belongs to Scale, matching SketchUp).
        select_action = self._tool_actions["select"]
        select_action.setShortcuts([QKeySequence(Qt.Key_Space)])
        select_action.setToolTip(tr(
            "Select (Space) — Shift+click adds or takes away, Ctrl+click "
            "adds, Shift+Ctrl+click takes away. Same with the box."))

        # View toolbar: camera nav (Orbit / Pan / Zoom / Zoom Window) + Zoom
        # Extents + iso view.
        view_tb = self._new_toolbar(tr("View"), "view")
        self.toolbars["view"] = view_tb
        self._nav_actions: dict[str, QAction] = {}
        for key, label, short, tip in [
            ("orbit", "Orbit", "O", "Orbit (O) — left-drag to rotate the view"),
            ("pan", "Pan", "H", "Pan (H) — left-drag to slide the view"),
            ("zoom", "Zoom", "Z", "Zoom (Z) — drag up/down to zoom in/out"),
            ("zoom_window", "Zoom Window", "",
             "Zoom Window — drag a box to zoom to that region"),
        ]:
            action = QAction(tool_icon(key), tr(label), self)
            action.setCheckable(True)
            if short:
                action.setShortcut(QKeySequence(short))
            action.setToolTip(tr(tip))
            action.triggered.connect(lambda _c, k=key: self._activate_nav(k))
            self._tool_group.addAction(action)
            view_tb.addAction(action)
            self._nav_actions[key] = action
            self._icon_actions.append((action, key))
        view_tb.addSeparator()
        # ONE action for Zoom Extents, shared with the Camera menu below.
        # It used to be built twice — same key on two QActions is a Qt
        # ambiguity, and an ambiguous shortcut fires NEITHER, so F2 did
        # nothing at all. Shift+Z is SketchUp's own key for it; F2 stays as
        # an alternate because it is the one that was documented here.
        act_ze = QAction(tool_icon("zoom_extents"), tr("Zoom Extents"), self)
        self._icon_actions.append((act_ze, "zoom_extents"))
        act_ze.setShortcuts([QKeySequence("Shift+Z"), QKeySequence("F2")])
        act_ze.setToolTip(f"{tr('Zoom Extents')}  (Shift+Z)")
        act_ze.triggered.connect(self._on_zoom_extents)
        view_tb.addAction(act_ze)
        self._act_zoom_extents = act_ze

        # Standard-views toolbar: one-shot camera orientations, icon-only.
        views_tb = self._new_toolbar(tr("Standard Views"), "views")
        self.toolbars["views"] = views_tb
        # Order as Marco reads them (2026-09-14): iso, top, front, right,
        # left, back, bottom — the two you use most right after the iso.
        for key, label, icon in [
            ("iso", "Isometric", "view_iso"),
            ("top", "Top", "view_top"),
            ("front", "Front", "view_front"),
            ("right", "Right", "view_right"),
            ("left", "Left", "view_left"),
            ("back", "Back", "view_back"),
            ("bottom", "Bottom", "view_bottom"),
        ]:
            act = QAction(tool_icon(icon), tr(label), self)
            act.setToolTip(tr(label))
            act.triggered.connect(lambda _c, k=key: self._on_standard_view(k))
            views_tb.addAction(act)
            self._icon_actions.append((act, icon))

    def _refresh_toolbar_icons(self) -> None:
        """Re-draw the programmatic toolbar icons for the current palette so a
        dark ↔ light theme switch (while the app is open) doesn't leave the
        icons in the previous theme's ink — they were baked at build time."""
        for action, key in getattr(self, "_icon_actions", []):
            action.setIcon(tool_icon(key))

    def changeEvent(self, event) -> None:
        # Qt posts these when the OS/Qt theme (palette) flips at runtime.
        if event.type() in (
            QEvent.ApplicationPaletteChange,
            QEvent.PaletteChange,
            QEvent.ThemeChange,
        ):
            self._refresh_toolbar_icons()
        super().changeEvent(event)

    def _build_menubar(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu(tr("File"))
        for action in self._file_actions():
            if isinstance(action, QMenu):
                file_menu.addMenu(action)
            else:
                file_menu.addAction(action)

        # Edit menu
        edit_menu = menubar.addMenu(tr("Edit"))

        self._undo_action = QAction(tr("Undo"), self)
        self._undo_action.setShortcut(QKeySequence.Undo)
        self._undo_action.triggered.connect(self._on_undo)
        edit_menu.addAction(self._undo_action)

        self._redo_action = QAction(tr("Redo"), self)
        # Cover both classic Windows (Ctrl+Y) and Linux/macOS (Ctrl+Shift+Z).
        self._redo_action.setShortcuts(
            [QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")]
        )
        self._redo_action.triggered.connect(self._on_redo)
        edit_menu.addAction(self._redo_action)
        # On the Main toolbar right after the pointer, as SketchUp has them
        # (Marco, 23-09). The SAME actions as the Edit menu: a second QAction
        # with Ctrl+Z would make the shortcut ambiguous, and an ambiguous
        # shortcut fires neither (the F2 lesson on Zoom Extents).
        main_tb = getattr(self, "toolbars", {}).get("main")
        if main_tb is not None:
            from views.icons import tool_icon
            for act, key, tip in ((self._undo_action, "undo", tr("Undo")),
                                  (self._redo_action, "redo", tr("Redo"))):
                act.setIcon(tool_icon(key))
                act.setToolTip(f"{tip}  ({act.shortcut().toString(QKeySequence.NativeText)})")
                self._icon_actions.append((act, key))
            after = self._tool_actions.get("select")
            acts = main_tb.actions()
            nxt = (acts[acts.index(after) + 1]
                   if after in acts and acts.index(after) + 1 < len(acts)
                   else None)
            for act in (self._undo_action, self._redo_action):
                if nxt is None:
                    main_tb.addAction(act)
                else:
                    main_tb.insertAction(nxt, act)

        edit_menu.addSeparator()

        cut_action = QAction(tr("Cut"), self)
        cut_action.setShortcut(QKeySequence.Cut)
        cut_action.triggered.connect(lambda: self.viewport.cut_selection())
        edit_menu.addAction(cut_action)

        copy_action = QAction(tr("Copy"), self)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(lambda: self.viewport.copy_selection())
        edit_menu.addAction(copy_action)

        paste_action = QAction(tr("Paste"), self)
        paste_action.setShortcut(QKeySequence.Paste)
        paste_action.triggered.connect(self._on_paste)
        edit_menu.addAction(paste_action)

        edit_menu.addSeparator()

        select_all_action = QAction(tr("Select All"), self)
        select_all_action.setShortcut(QKeySequence.SelectAll)
        select_all_action.triggered.connect(self._on_select_all)
        edit_menu.addAction(select_all_action)

        # SketchUp's Edit ▸ Invert Selection, same shortcut.
        invert_action = QAction(tr("Invert Selection"), self)
        invert_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        invert_action.triggered.connect(self._on_invert_selection)
        edit_menu.addAction(invert_action)

        edit_menu.addSeparator()

        group_action = QAction(tr("Make Group"), self)
        group_action.setShortcut(QKeySequence("Ctrl+G"))
        group_action.triggered.connect(self._on_make_group)
        edit_menu.addAction(group_action)

        component_action = QAction(tr("Make Component…"), self)
        component_action.setShortcut(QKeySequence("G"))   # SketchUp's G
        component_action.triggered.connect(self._on_make_component)
        edit_menu.addAction(component_action)

        explode_action = QAction(tr("Explode Group"), self)
        explode_action.setShortcut(QKeySequence("Ctrl+Shift+G"))
        explode_action.triggered.connect(self._on_explode_group)
        edit_menu.addAction(explode_action)

        # SketchUp's Edit ▸ Intersect Faces (core/intersect.py).
        self._intersect_menu = QMenu(tr("Intersect Faces"), edit_menu)
        self._fill_intersect_menu(self._intersect_menu)
        edit_menu.addMenu(self._intersect_menu)

        split_action = QAction(tr("Split into Pieces"), self)
        split_action.triggered.connect(self._on_split_into_pieces)
        edit_menu.addAction(split_action)

        convert_path_action = QAction(tr("Convert Path to Geometry"), self)
        convert_path_action.triggered.connect(self._on_convert_geopath)
        edit_menu.addAction(convert_path_action)

        delete_guides_action = QAction(tr("Delete Guides"), self)
        delete_guides_action.triggered.connect(self._on_delete_guides)
        edit_menu.addAction(delete_guides_action)

        edit_menu.addSeparator()

        # SketchUp's Edit ▸ Hide and Edit ▸ Unhide ▸ Last / All. Hide takes
        # the selected OBJECTS (groups, components) and edges; there was
        # only «Ocultar aristas» and Rafael looked for the object one and
        # did not find it (2026-09-16, 38:40).
        hide_action = QAction(tr("Hide"), self)
        hide_action.triggered.connect(self._on_hide)
        edit_menu.addAction(hide_action)

        unhide_menu = edit_menu.addMenu(tr("Unhide"))
        unhide_selected_action = QAction(tr("Selected"), self)
        unhide_selected_action.triggered.connect(self._on_unhide_selected)
        unhide_menu.addAction(unhide_selected_action)
        unhide_last_action = QAction(tr("Last"), self)
        unhide_last_action.triggered.connect(self._on_unhide_last)
        unhide_menu.addAction(unhide_last_action)
        unhide_all_action = QAction(tr("All"), self)
        unhide_all_action.triggered.connect(self._on_unhide_all)
        unhide_menu.addAction(unhide_all_action)

        reverse_action = QAction(tr("Reverse Faces"), self)
        reverse_action.triggered.connect(self._on_reverse_faces)
        edit_menu.addAction(reverse_action)

        orient_action = QAction(tr("Orient Faces"), self)
        orient_action.triggered.connect(self._on_orient_faces)
        edit_menu.addAction(orient_action)

        heal_action = QAction(tr("Heal Overlapping Faces"), self)
        heal_action.triggered.connect(self._on_heal_overlaps)
        edit_menu.addAction(heal_action)

        rebuild_action = QAction(tr("Rebuild Faces (Planar)"), self)
        rebuild_action.triggered.connect(self._on_rebuild_planar)
        edit_menu.addAction(rebuild_action)

        # Camera menu (SketchUp: navigation + projection + canned views)
        camera_menu = menubar.addMenu(tr("Camera"))

        standard_menu = camera_menu.addMenu(tr("Standard Views"))
        for label, key in [
            ("Top", "top"),
            ("Bottom", "bottom"),
            ("Front", "front"),
            ("Back", "back"),
            ("Left", "left"),
            ("Right", "right"),
            ("Isometric", "iso"),
        ]:
            action = QAction(tr(label), self)
            action.triggered.connect(lambda _checked, k=key: self._on_standard_view(k))
            standard_menu.addAction(action)

        camera_menu.addAction(self._act_zoom_extents)   # la MISMA del botón

        camera_menu.addSeparator()

        action_proj = QAction(tr("Toggle Perspective / Parallel"), self)
        # P went back to Push/Pull, which is what SketchUp's card says; the
        # projection toggle has no key there at all, so it takes Shift+P —
        # the same "the tool that yields keeps Shift+key" rule as the
        # Protractor and the centre arc.
        action_proj.setShortcut(QKeySequence("Shift+P"))
        action_proj.triggered.connect(self.viewport.toggle_projection)
        camera_menu.addAction(action_proj)

        # SketchUp's Two-Point Perspective: verticals stay vertical, as an
        # architectural drawing wants them (José Castro Basso, FADU–UDELAR).
        self._act_two_point = QAction(tr("Two-Point Perspective"), self)
        self._act_two_point.setCheckable(True)
        self._act_two_point.setToolTip(tr(
            "Perspective with vertical lines kept vertical"))
        self._act_two_point.triggered.connect(self.viewport.toggle_two_point)
        camera_menu.addAction(self._act_two_point)
        camera_menu.aboutToShow.connect(
            lambda: self._act_two_point.setChecked(
                self.viewport.camera.two_point
                and self.viewport.camera.perspective))

        # Styles (SketchUp): the model's display look — face mode, edges,
        # background. Scenes remember the style; the composer's live-look
        # frames inherit it.
        from core.style import BUILTIN_STYLES
        camera_menu.addSeparator()
        style_menu = camera_menu.addMenu(tr("Style"))
        self._style_group = QActionGroup(self)
        self._style_actions: dict[str, QAction] = {}
        for preset in BUILTIN_STYLES:
            act = QAction(tr(preset.name), self)
            act.setCheckable(True)
            self._style_group.addAction(act)
            act.triggered.connect(
                lambda _c=False, p=preset: self._apply_display_style(p))
            style_menu.addAction(act)
            self._style_actions[preset.name] = act
        style_menu.addSeparator()
        self._act_style_edges = QAction(tr("Edges"), self)
        self._act_style_edges.setCheckable(True)
        self._act_style_edges.toggled.connect(
            lambda on: self._set_style_field("edges", on))
        style_menu.addAction(self._act_style_edges)
        self._act_style_profiles = QAction(tr("Profiles"), self)
        self._act_style_profiles.setCheckable(True)
        self._act_style_profiles.toggled.connect(
            lambda on: self._set_style_field("profiles", on))
        style_menu.addAction(self._act_style_profiles)
        self._sync_style_menu()

        # How the model outside a group reads while you edit it (SketchUp's
        # Model Info ▸ Components). Hiding it is also the fastest on a heavy
        # import: what is not in the frame never reaches the GPU.
        rest_menu = camera_menu.addMenu(tr("Rest of model while editing"))
        self._rest_group = QActionGroup(self)
        self._rest_actions: dict[str, QAction] = {}
        for key, label in (("normal", tr("Show normally")),
                           ("fade", tr("Fade")),
                           ("hide", tr("Hide (fastest)"))):
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(self.viewport.edit_rest_mode == key)
            self._rest_group.addAction(act)
            act.triggered.connect(
                lambda _c=False, k=key: self.viewport.set_edit_rest_mode(k))
            rest_menu.addAction(act)
            self._rest_actions[key] = act

        # Sun shadows (core/sun.py) — the checkbox mirrors the tray panel.
        self._act_shadows = QAction(tr("Shadows"), self)
        self._act_shadows.setCheckable(True)
        self._act_shadows.toggled.connect(self._on_toggle_shadows)
        camera_menu.addAction(self._act_shadows)

        # SketchUp's View ▸ Section Planes / Cuts / Fill — the same actions
        # as the Sections toolbar buttons (created in _build_toolbar).
        camera_menu.addSeparator()
        camera_menu.addAction(self._act_show_splanes)
        camera_menu.addAction(self._act_show_scuts)
        camera_menu.addAction(self._act_section_fill)

        # SketchUp's View ▸ Hidden Objects / Hidden Geometry: what Hide put
        # away comes back as a see-through grid and can be selected again
        # (Marco, 2026-09-18, with the two SketchUp captures).
        camera_menu.addSeparator()
        self._act_hidden_objects = QAction(tr("Hidden Objects"), self)
        self._act_hidden_objects.setCheckable(True)
        self._act_hidden_objects.toggled.connect(
            lambda on: self._set_hidden_view("show_hidden_objects", on))
        camera_menu.addAction(self._act_hidden_objects)
        self._act_hidden_geometry = QAction(tr("Hidden Geometry"), self)
        self._act_hidden_geometry.setCheckable(True)
        self._act_hidden_geometry.toggled.connect(
            lambda on: self._set_hidden_view("show_hidden_geometry", on))
        camera_menu.addAction(self._act_hidden_geometry)

        camera_menu.addSeparator()
        for action in self._nav_actions.values():   # Orbit / Pan / Zoom / Zoom Window
            camera_menu.addAction(action)
        # SketchUp's Camera ▸ Position Camera / Walk / Look Around.
        camera_menu.addSeparator()
        for key in ("position_camera", "walk", "look_around", "first_person"):
            camera_menu.addAction(self._tool_actions[key])

        # Draw menu (SketchUp: the drawing tools, grouped by family)
        draw_menu = menubar.addMenu(tr("Draw"))
        draw_menu.addAction(self._tool_actions["line"])
        draw_menu.addAction(self._tool_actions["freehand"])
        arcs_menu = draw_menu.addMenu(tr("Arcs"))
        for key in ("arc", "arc3", "center_arc", "pie"):
            arcs_menu.addAction(self._tool_actions[key])
        shapes_menu = draw_menu.addMenu(tr("Shapes"))
        for key in ("rectangle", "rotated_rect", "circle", "polygon"):
            shapes_menu.addAction(self._tool_actions[key])
        draw_menu.addSeparator()
        draw_menu.addAction(self._tool_actions["geopath"])

        # Tools menu (SketchUp: select/modify/measure — drawing lives in Draw)
        tools_menu = menubar.addMenu(tr("Tools"))
        for keys in (("select", "eraser", "paint"),
                     ("move", "rotate", "scale", "flip"),
                     ("pushpull", "followme", "offset", "fillet"),
                     ("tape", "protractor"),
                     ("dimension", "text"),
                     ("section",)):
            for key in keys:
                tools_menu.addAction(self._tool_actions[key])
            tools_menu.addSeparator()
        # SketchUp: Tools ▸ Outer Shell, and Tools ▸ Solid Tools ▸ the rest.
        tools_menu.addAction(self._tool_actions["outer_shell"])
        solids_menu = QMenu(tr("Solid Tools"), tools_menu)
        for key in ("solid_intersect", "solid_union", "solid_subtract",
                    "solid_trim", "solid_split"):
            solids_menu.addAction(self._tool_actions[key])
        tools_menu.addMenu(solids_menu)
        self._solids_menu = solids_menu        # a QMenu dies with its locals
        tools_menu.addSeparator()
        action_3dtext = QAction(tool_icon("text3d"), tr("3D Text…"), self)
        action_3dtext.triggered.connect(self._on_insert_3d_text)
        tools_menu.addAction(action_3dtext)
        self._icon_actions.append((action_3dtext, "text3d"))
        tools_menu.addSeparator()
        action_profile = QAction(tr("Terrain profile of selection"), self)
        action_profile.triggered.connect(self._on_terrain_profile)
        tools_menu.addAction(action_profile)
        tools_menu.addSeparator()
        action_cancel = QAction(tr("Cancel current tool"), self)
        action_cancel.setShortcut(QKeySequence("Esc"))
        action_cancel.triggered.connect(self._cancel_tool)
        tools_menu.addAction(action_cancel)

        # Window menu (SketchUp: panels + app preferences)
        window_menu = menubar.addMenu(tr("Window"))

        toggle_tray = self.tray.toggleViewAction()
        toggle_tray.setText(tr("Properties panel"))
        window_menu.addAction(toggle_tray)

        # Every tray has its entry: a closed BIM tray had no way back
        # (Marco, 0.5.1 Flatpak: «no veo las pestañas de terreno y BIM»).
        toggle_bim = self.bim_tray.toggleViewAction()
        toggle_bim.setText(tr("BIM panel"))
        window_menu.addAction(toggle_bim)

        toggle_georef = self.georef_tray.toggleViewAction()
        toggle_georef.setText(tr("Terrain panel"))
        window_menu.addAction(toggle_georef)
        # Only the menu says a tray is unwanted: that choice is remembered
        # and every other tray opens at start-up (see _show_default_trays).
        for dock in self._sidebar_docks():
            dock.toggleViewAction().triggered.connect(
                lambda on, d=dock: self._remember_tray_choice(d, on))

        toggle_profile = self.profile_dock.toggleViewAction()
        toggle_profile.setText(tr("Terrain profile"))
        window_menu.addAction(toggle_profile)


        # AutoCAD's Ctrl+0 clean screen: nothing but the model, for
        # presenting. Added to the WINDOW too, so the shortcut keeps
        # working while the menu bar itself is hidden.
        window_menu.addSeparator()
        clean_action = QAction(tr("Clean screen"), self)
        clean_action.setShortcut(QKeySequence("Ctrl+0"))
        clean_action.setCheckable(True)
        clean_action.toggled.connect(self._route_window_toggle(
            "_act_clean_screen", self._toggle_clean_screen))
        self.addAction(clean_action)
        window_menu.addAction(clean_action)
        self._act_clean_screen = clean_action
        # LibreOffice's Ctrl+F5: the whole sidebar (the three trays) folds
        # away and comes back; the strip at the right edge stays.
        window_menu.addAction(self._act_sidebar)

        window_menu.addSeparator()
        prefs_action = QAction(tr("Preferences…"), self)
        prefs_action.triggered.connect(self._on_preferences)
        window_menu.addAction(prefs_action)
        self._build_language_menu(window_menu)

        # Extensions — third-party plugin tools (core.extensions engine).
        self._build_extensions_menu(menubar)

        help_menu = menubar.addMenu(tr("Help"))
        get_models_action = QAction(tr("Get more models and textures…"), self)
        get_models_action.triggered.connect(self._on_get_models)
        help_menu.addAction(get_models_action)
        # Only as an AppImage: put a launcher in the menu, or take it away.
        from core.appimage import appimage_path
        if appimage_path() is not None:
            add_act = QAction(tr("Add to the applications menu"), self)
            add_act.triggered.connect(self.add_appimage_to_menu)
            help_menu.addAction(add_act)
            rm_act = QAction(tr("Remove from the applications menu"), self)
            rm_act.triggered.connect(self.remove_appimage_from_menu)
            help_menu.addAction(rm_act)
            help_menu.addSeparator()
        about_action = QAction(tr("About IngeTrazo"), self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    # ---- Language -----------------------------------------------------------
    _LANGUAGE_NAMES = LANGUAGE_NAMES

    def _build_language_menu(self, parent_menu) -> None:
        lang_menu = parent_menu.addMenu(tr("Language"))
        group = QActionGroup(self)
        group.setExclusive(True)
        for code in available_languages():
            action = QAction(self._LANGUAGE_NAMES.get(code, code), self)
            action.setCheckable(True)
            action.setChecked(code == current_language())
            action.triggered.connect(lambda _checked, c=code: self._on_set_language(c))
            group.addAction(action)
            lang_menu.addAction(action)

    # ---- Sidebar strip (LibreOffice-style) ---------------------------------
    def _show_default_trays(self, st) -> None:
        """Properties, BIM and Terrain always open at start-up — a tray
        stays closed only when it was closed from the Window menu (Marco,
        24-09: «que siempre se muestren por defecto con opción de ocultarlas
        desde el menú Ventana»). A saved layout alone (a folded sidebar, a
        tray lost by the old fold) does not keep one away."""
        hidden = self._hidden_tray_names(st)
        docks = self._sidebar_docks()
        for d in docks:
            d.setVisible(d.objectName() not in hidden)
        if not self.tray.isHidden():
            self.tray.raise_()

    @staticmethod
    def _hidden_tray_names(st) -> set:
        raw = st.value("ui/hidden_trays", []) or []
        if isinstance(raw, str):
            raw = [raw]
        return {str(x) for x in raw}

    def _remember_tray_choice(self, dock, shown: bool) -> None:
        st = QSettings()
        hidden = self._hidden_tray_names(st)
        if shown:
            hidden.discard(dock.objectName())
        else:
            hidden.add(dock.objectName())
        st.setValue("ui/hidden_trays", sorted(hidden))

    def _sidebar_docks(self) -> list:
        return [d for d in (getattr(self, "tray", None),
                            getattr(self, "bim_tray", None),
                            getattr(self, "georef_tray", None),
                            *getattr(self, "_extension_docks", ()))
                if d is not None]

    def _build_sidebar_handle(self) -> None:
        """LibreOffice's sidebar handle: a slim button sitting ON the line
        where the sidebar is resized, half-way down, with a chevron — click
        folds the three trays away; the handle then rests at the window's
        right edge, chevron pointing back in, and click brings them back.
        Window ▸ Sidebar (Ctrl+F5) is the same toggle (Marco, 2026-09-14:
        «ponerlo justo en esa línea donde redimensiono la barra vertical,
        como lo hace LibreOffice»)."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QToolButton
        act = QAction(tr("Sidebar"), self)
        act.setCheckable(True)
        act.setChecked(True)
        act.setShortcut(QKeySequence("Ctrl+F5"))
        act.setToolTip(tr("Show or hide the sidebar (Ctrl+F5)"))
        act.toggled.connect(self._route_window_toggle(
            "_act_sidebar", self._set_sidebar_visible))
        self.addAction(act)
        self._act_sidebar = act

        btn = QToolButton(self)
        btn.setObjectName("sidebar_handle")
        btn.setFixedSize(14, 56)
        btn.setIconSize(QSize(12, 12))
        btn.setIcon(tool_icon("side_collapse"))
        btn.setToolTip(act.toolTip())
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.setStyleSheet(
            "QToolButton { background: palette(mid); border: none;"
            " border-radius: 4px; }"
            "QToolButton:hover { background: rgb(243, 115, 41); }")
        btn.clicked.connect(lambda: act.setChecked(not act.isChecked()))
        self._sidebar_handle = btn
        self._icon_actions.append((btn, "side_collapse"))
        self.viewport.installEventFilter(self)
        self._follow_sidebar_docks()
        self._place_sidebar_handle()

    def _follow_sidebar_docks(self) -> None:
        """Raising a tabbed tray (Terrain ↔ BIM) restacks the window's
        children above the handle, which then vanishes behind the dock
        (Marco, 2026-09-14) — every dock change re-places (and re-raises) it."""
        from PySide6.QtCore import QTimer
        bump = lambda *_: QTimer.singleShot(0, self._place_sidebar_handle)
        for d in self._sidebar_docks():
            d.visibilityChanged.connect(bump)
            d.dockLocationChanged.connect(bump)
            d.topLevelChanged.connect(bump)

    def _place_sidebar_handle(self) -> None:
        """On the resize line between the viewport and the trays, centred
        vertically; at the window's edge when the trays are folded."""
        btn = getattr(self, "_sidebar_handle", None)
        if btn is None:
            return
        from PySide6.QtCore import QPoint
        edge = self.viewport.mapTo(self, QPoint(self.viewport.width(), 0))
        x = edge.x() - btn.width() // 2
        x = max(0, min(x, self.width() - btn.width()))
        y = edge.y() + (self.viewport.height() - btn.height()) // 2
        btn.move(x, max(0, y))
        btn.raise_()
        btn.setVisible(not self._act_clean_screen.isChecked()
                       if hasattr(self, "_act_clean_screen") else True)

    def _sidebar_visible(self) -> bool:
        return any(d.isVisible() for d in self._sidebar_docks())

    def _set_sidebar_visible(self, on: bool) -> None:
        """Fold the trays away (remembering which were open) or bring
        them back; the chevron turns to point the way."""
        docks = self._sidebar_docks()
        if on:
            shown = getattr(self, "_sidebar_was", None) or docks[:1]
            for d in docks:
                d.setVisible(d in shown)
            top = getattr(self, "_sidebar_top", None)
            if top is not None and top in shown:
                top.raise_()
        else:
            # OPEN, not on screen: a tray tabbed behind another is not
            # visible, and unfolding left BIM and Terrain closed for good.
            self._sidebar_was = [d for d in docks
                                 if d.toggleViewAction().isChecked()]
            self._sidebar_top = next((d for d in docks if d.isVisible()
                                      and not d.visibleRegion().isEmpty()), None)
            for d in docks:
                d.hide()
        btn = getattr(self, "_sidebar_handle", None)
        if btn is not None:
            key = "side_collapse" if on else "side_expand"
            btn.setIcon(tool_icon(key))
            self._icon_actions = [(a, (key if a is btn else k))
                                  for a, k in self._icon_actions]
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._place_sidebar_handle)   # after the relayout

    def _toggle_clean_screen(self, on: bool) -> None:
        """AutoCAD's Ctrl+0: fold away every toolbar, dock and bar so only
        the model remains (presentations); Ctrl+0 again restores the
        workspace exactly as it was."""
        from PySide6.QtWidgets import QDockWidget
        if on:
            self._clean_screen_state = self.saveState()
            for tb in self.findChildren(QToolBar):
                tb.hide()
            for dock in self.findChildren(QDockWidget):
                dock.hide()
            self.menuBar().hide()
            self.statusBar().hide()
            self._clean_screen_exit_button().show()
            self._place_clean_screen_exit()
            if getattr(self, "_sidebar_handle", None) is not None:
                self._sidebar_handle.hide()
        else:
            btn = getattr(self, "_clean_exit_btn", None)
            if btn is not None:
                btn.hide()
            state = getattr(self, "_clean_screen_state", None)
            if state is not None:
                self.restoreState(state)
            self.menuBar().show()
            self.statusBar().show()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._place_sidebar_handle)

    def _clean_screen_exit_button(self):
        """A small «Exit clean screen» button floating at the viewport's
        top-right corner while everything else is hidden — the way out for
        whoever does not know Ctrl+0 (Marco, 2026-09-14)."""
        btn = getattr(self, "_clean_exit_btn", None)
        if btn is not None:
            return btn
        from PySide6.QtWidgets import QToolButton
        btn = QToolButton(self.viewport)
        btn.setObjectName("clean_screen_exit")
        btn.setText("✕  " + tr("Exit clean screen"))
        btn.setToolTip(tr("Back to the workspace (Ctrl+0)"))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setAutoRaise(True)
        btn.setStyleSheet(
            "QToolButton { background: rgba(30, 36, 44, 170); color: white;"
            " border: 1px solid rgba(255, 255, 255, 90); border-radius: 6px;"
            " padding: 4px 10px; font-weight: bold; }"
            "QToolButton:hover { background: rgba(243, 115, 41, 220); }")
        btn.clicked.connect(lambda: self._act_clean_screen.setChecked(False))
        btn.hide()
        self._clean_exit_btn = btn
        self.viewport.installEventFilter(self)
        return btn

    def _place_clean_screen_exit(self) -> None:
        btn = getattr(self, "_clean_exit_btn", None)
        if btn is None or not btn.isVisible():
            return
        btn.adjustSize()
        btn.move(self.viewport.width() - btn.width() - 12, 12)
        btn.raise_()

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        from PySide6.QtCore import QEvent
        if obj is getattr(self, "viewport", None) and event.type() in (
                QEvent.Resize, QEvent.Move, QEvent.Show):
            self._place_clean_screen_exit()
            self._place_sidebar_handle()
        return super().eventFilter(obj, event)

    def _on_preferences(self) -> None:
        """Window ▸ Preferences: the scattered QSettings in one dialog."""
        from views.preferences_dialog import PreferencesDialog
        PreferencesDialog(self).exec()

    def _on_set_language(self, code: str) -> None:
        """Persist the chosen UI language (applied on next start)."""
        if code == current_language():
            return
        QSettings().setValue("language", code)
        set_language(code)
        QMessageBox.information(
            self,
            tr("Language changed"),
            tr("Restart IngeTrazo to apply the new language."),
        )

    def _build_extensions_menu(self, menubar) -> None:
        """The Extensions menu: one entry per plugin tool discovered by
        :mod:`core.extensions`. The engine guarantees a broken plugin cannot
        break startup — it arrives here as an error entry, shown disabled
        with the exception in its tooltip so the author can fix it."""
        import logging
        from core.extensions import discover_plugins

        log = logging.getLogger("ingetrazo.plugins")
        ext_menu = menubar.addMenu(tr("Extensions"))
        plugins, errors = discover_plugins()

        # Shortcuts the app already claimed (toolbar tools, menus — all built
        # before this menu): first come, first served. A plugin asking for a
        # taken key gets its entry without the shortcut, instead of a Qt
        # ambiguity that silently disables the built-in key for both.
        taken = {a.shortcut().toString() for a in self.findChildren(QAction)
                 if not a.shortcut().isEmpty()}

        count = 0
        from views.extension_api import ExtensionApp
        for plug in list(plugins):
            if plug.setup is None:
                continue
            try:
                plug.setup(ExtensionApp(self, plug.stem))
            except Exception as exc:  # noqa: BLE001 — never break startup
                log.exception("plugin %r setup failed", plug.stem)
                from core.extensions import PluginError
                errors.append(PluginError(
                    plug.stem, plug.path, f"{type(exc).__name__}: {exc}"))
                plugins.remove(plug)
                continue
            if not plug.tools:
                count += 1                  # a panel-only extension counts
        for plug in plugins:
            for tool in plug.tools:
                key = f"plugin_{plug.stem}_{type(tool).__name__}"
                self._tools[key] = tool
                action = QAction(tr(tool.name), self)
                if tool.shortcut:
                    seq = QKeySequence(tool.shortcut).toString()
                    if seq and seq not in taken:
                        action.setShortcut(QKeySequence(tool.shortcut))
                        action.setToolTip(f"{tr(tool.name)}  ({tool.shortcut})")
                        taken.add(seq)
                    else:
                        log.warning("plugin %r wants shortcut %r, already "
                                    "taken; entry added without it",
                                    plug.stem, tool.shortcut)
                action.triggered.connect(
                    lambda _c, k=key: self._activate_plugin_tool(k))
                ext_menu.addAction(action)
                count += 1

        for err in errors:
            action = ext_menu.addAction(
                tr("\u26a0 {name} (load error)", name=err.stem))
            action.setEnabled(False)
            action.setToolTip(err.error)

        if count == 0 and not errors:
            ext_menu.addAction(tr("(no plugins found)")).setEnabled(False)

        self._add_example_extensions_menu(ext_menu)

        # The on-ramp for plugin authors: their folder and the dev guide.
        ext_menu.addSeparator()
        act = ext_menu.addAction(tr("Open plugins folder"))
        act.triggered.connect(self._on_open_plugins_folder)
        act = ext_menu.addAction(tr("Develop a plugin…"))
        act.triggered.connect(self._on_develop_plugin)

    @staticmethod
    def example_extensions() -> list:
        """``(path, title, blurb)`` of each example extension shipped with
        the app (``examples/extensions``) — installed by the user, never
        loaded on their own: what only some need stays out of the core."""
        import ast
        from core.paths import app_root
        folder = app_root() / "examples" / "extensions"
        out = []
        # A single ``x.py`` or a package ``x/__init__.py`` — a bigger
        # extension (CAM, PR #132) is a folder, and the loader takes both.
        entries = sorted(folder.iterdir()) if folder.is_dir() else []
        for path in entries:
            if path.suffix == ".py" and path.is_file():
                src = path
            elif path.is_dir() and (path / "__init__.py").is_file():
                src = path / "__init__.py"
            else:
                continue
            try:
                doc = ast.get_docstring(ast.parse(src.read_text("utf-8"))) or ""
            except (OSError, SyntaxError, ValueError):
                doc = ""
            first, _, rest = doc.partition("\n")
            title = first.split(" — ")[0].strip() or path.stem
            blurb = rest.strip().split("\n\n")[0].replace("\n", " ")
            out.append((path, title, blurb))
        return out

    def _add_example_extensions_menu(self, ext_menu) -> None:
        """Extensions ▸ Example extensions: each one ticked when installed;
        a click installs it into the user's plugins folder, or removes it.
        Takes effect at the next start, like any plugin."""
        examples = self.example_extensions()
        if not examples:
            return
        from PySide6.QtWidgets import QMenu
        from core.extensions import user_plugins_dir
        ext_menu.addSeparator()
        sub = QMenu(tr("Example extensions"), ext_menu)
        ext_menu.addMenu(sub)
        for path, title, blurb in examples:
            act = sub.addAction(title)
            act.setCheckable(True)
            act.setChecked((user_plugins_dir() / path.name).exists())
            act.setToolTip(blurb)
            act.setStatusTip(blurb)
            act.toggled.connect(
                lambda on, p=path, t=title: self._toggle_example_extension(
                    p, t, on))
        sub.setToolTipsVisible(True)

    def _toggle_example_extension(self, path, title: str, on: bool) -> None:
        import shutil
        from core.extensions import user_plugins_dir
        target = user_plugins_dir() / path.name
        try:
            if on:
                target.parent.mkdir(parents=True, exist_ok=True)
                if path.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(path, target, ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc"))
                else:
                    shutil.copyfile(path, target)
                msg = tr("«{name}» installed. Restart IngeTrazo to use it.",
                         name=title)
            elif target.is_dir():
                shutil.rmtree(target)
                msg = tr("«{name}» removed. Restart IngeTrazo to unload it.",
                         name=title)
            else:
                target.unlink(missing_ok=True)
                msg = tr("«{name}» removed. Restart IngeTrazo to unload it.",
                         name=title)
        except OSError as exc:
            QMessageBox.warning(self, tr("Example extensions"), str(exc))
            return
        QMessageBox.information(self, tr("Example extensions"), msg)

    PLUGIN_GUIDE_URL = ("https://github.com/ingelibre/ingetrazo"
                        "/blob/main/docs/plugins.md")

    def _on_open_plugins_folder(self) -> None:
        """Open (creating if needed) the per-user plugins directory — drop
        a .py here and its tools appear in Extensions on next start."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from core.extensions import user_plugins_dir
        folder = user_plugins_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_develop_plugin(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(self.PLUGIN_GUIDE_URL))

    def _activate_plugin_tool(self, key: str) -> None:
        """Run a plugin tool from the Extensions menu.

        Plugin tools are one-shot (they open a dialog and return): the
        viewport's active tool is left untouched, so the status bar keeps
        telling the truth about which drawing tool is current."""
        self._tools[key].on_activate(self.viewport)

    def _on_gl_ready(self, info: dict) -> None:
        """A viewport drawn on the CPU is the usual reason a Windows machine
        reports IngeTrazo as unusably slow; say so where the user looks."""
        if info.get("software"):
            self.statusBar().showMessage(tr(
                "IngeTrazo is drawing with the software renderer ({renderer}): "
                "the viewport will be slow. Update the graphics driver, or "
                "assign IngeTrazo to the high-performance GPU in Windows "
                "graphics settings.", renderer=info.get("renderer", "")), 30000)
        elif QCoreApplication.instance().property("gpu_pref") == "set":
            # First run on Windows: the preference was just written, and
            # Windows applies it to the next process, not this one.
            self.statusBar().showMessage(tr(
                "IngeTrazo asked Windows for the high-performance GPU; it "
                "applies the next time you open the program."), 20000)

    def _on_about(self) -> None:
        from core.glinfo import describe
        from views.about_dialog import AboutDialog
        gl_line = describe(getattr(self.viewport, "gl_info", {}))
        # The people outside the project whose work is IN it turn in a
        # carousel there; AUTHORS says what each one gave.
        AboutDialog(self, __version__, gl_line or "").exec()

    def _file_actions(self) -> list[QAction]:
        actions = []

        new_action = QAction(tr("New"), self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self._on_new)
        actions.append(new_action)

        # A second IngeTrazo beside this one: each window is its own
        # document, and Copy/Paste now crosses between them (issue #76).
        window_action = QAction(tr("New Window"), self)
        window_action.setShortcut(QKeySequence("Ctrl+Shift+N"))
        window_action.triggered.connect(self._on_new_window)
        actions.append(window_action)

        open_action = QAction(tr("Open…"), self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._on_open)
        actions.append(open_action)

        # The last documents, one click away (asked for since the 0.4.x
        # triage; SketchUp's File ▸ Open Recent). Filled when shown, so a
        # file deleted meanwhile just drops off the list.
        self._recent_menu = QMenu(tr("Open Recent"), self)
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        actions.append(self._recent_menu.menuAction())

        recover_action = QAction(tr("Recover a discarded auto-save…"), self)
        recover_action.setToolTip(tr(
            "Auto-saved copies retired when a session was closed without "
            "saving — the last ones are kept here for a second chance."))
        recover_action.triggered.connect(self._on_recover_discarded)
        actions.append(recover_action)

        save_action = QAction(tr("Save"), self)
        save_action.setShortcut(QKeySequence.Save)
        save_action.triggered.connect(self._on_save)
        actions.append(save_action)

        save_as_action = QAction(tr("Save As…"), self)
        save_as_action.setShortcut(QKeySequence.SaveAs)
        save_as_action.triggered.connect(self._on_save_as)
        actions.append(save_as_action)

        actions.append(self._separator())

        # One home for everything that comes in, one for everything that
        # goes out — the flat list had import/export items scattered.
        import_menu = QMenu(tr("Import"), self)
        for label, handler in (
            (tr("IngeTrazo document as component (.igz)…"),
             self._on_import_igz),
            (tr("SketchUp (.skp)…"), self._on_import_skp),
            (tr("COLLADA (.dae)…"), self._on_import_dae),
            (tr("glTF/GLB (.glb)…"), self._on_import_glb),
            (tr("Wavefront OBJ (.obj)…"), self._on_import_obj),
            (tr("Image (PNG / JPG)…"), self._on_import_image),
            (tr("Orthomosaic (GeoTIFF)…"), self._on_import_orthophoto),
            (tr("AutoCAD DWG (.dwg)…"), self._on_import_dwg),
            (tr("AutoCAD DXF (.dxf)…"), self._on_import_dxf),
            (tr("Georeference (KML / GeoJSON)…"), self._on_import_georef),
            (tr("Survey points CSV (UTM)…"), self._on_import_survey_points),
            (tr("Photogrammetric mesh (WebODM)…"), self._on_import_photomesh),
        ):
            act = QAction(label, self)
            act.triggered.connect(handler)
            import_menu.addAction(act)
        import_menu.addSeparator()
        clear_tex = QAction(tr("Clear imported texture cache…"), self)
        clear_tex.setToolTip(tr(
            "Delete the images extracted from imported .skp files."))
        clear_tex.triggered.connect(self._on_clear_texture_cache)
        import_menu.addAction(clear_tex)
        actions.append(import_menu)

        export_menu = QMenu(tr("Export"), self)
        for label, handler in (
            (tr("IFC (BIM)…"), self._on_export_ifc),
            (tr("glTF / GLB (3D, single file)…"), self._on_export_glb),
            (tr("COLLADA (.dae)…"), self._on_export_dae),
            (tr("STL (3D printing)…"), self._on_export_stl),
            (tr("Wavefront OBJ (.obj)…"), self._on_export_obj),
            (tr("SketchUp (.skp)…"), self._on_export_skp),
            (tr("Current view as DXF…"), self._on_export_view_dxf),
            (tr("Image (PNG / JPG)…"), self._on_export_image),
        ):
            act = QAction(label, self)
            act.triggered.connect(handler)
            export_menu.addAction(act)
        actions.append(export_menu)

        # Components moved to the Properties tray (SketchUp-style panel with
        # static thumbnails) — see views/tray.py::ComponentsPanel.

        actions.append(self._separator())

        composer_action = QAction(tr("Sheet composer…"), self)
        composer_action.setToolTip(tr(
            "Lay out the model on paper at exact scale and export a PDF plan."))
        composer_action.triggered.connect(self._on_open_composer)
        actions.append(composer_action)

        actions.append(self._separator())

        quit_action = QAction(tr("Quit"), self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        actions.append(quit_action)

        return actions

    def _separator(self) -> QAction:
        sep = QAction(self)
        sep.setSeparator(True)
        return sep

    def _build_statusbar(self) -> None:
        # The status bar carries the Model | Sheet 1 | … strip at its left,
        # on the same row as the measurements box (AutoCAD's Model / Layout
        # tabs): one click from the model to any sheet.
        from views.sheet_tabs import SheetStatusBar
        bar = SheetStatusBar(self, on_model=self._show_model,
                             on_sheet=self._show_strip_sheet,
                             on_new=self._show_new_sheet,
                             on_menu=self._strip_sheet_menu)
        self.setStatusBar(bar)
        self._sheet_tabs = bar.tabs
        # Ctrl+Tab: to the sheets and back (#91, @pacaeiro) — the last sheet
        # shown, as the strip's own tab; Ctrl+Shift+Tab too, with only two
        # places to go. A document without sheets gets its first one.
        from PySide6.QtGui import QShortcut
        for seq in ("Ctrl+Tab", "Ctrl+Shift+Tab"):
            QShortcut(QKeySequence(seq), self, activated=self._to_sheets)
        # ONE hint for the tool and its step (SketchUp's status bar) goes in
        # as the bar's BASE message — SheetStatusBar keeps the Model | Sheet
        # strip glued to the left and restores the base after a timed
        # message (flash_status). A widget of our own here landed LEFT of
        # the strip (Marco, 2026-09-15: «la ubicación de modelo y
        # composiciones siempre debe ser primero»). It replaced a strip of
        # every shortcut at once.
        self._tool_label = QLabel(tr("Tool: none"))
        bar.addPermanentWidget(self._tool_label)
        # Not shown any more: the tool's name leads the hint instead, and the
        # 250 px it held go to the hint (Marco, 23-09 — the icon of the
        # tool is highlighted anyway). Kept as the record other code reads.
        self._tool_label.hide()
        self._refresh_sheet_tabs()

        # Live UTM readout, the way a CAD shows coordinates. Local scene metres
        # are meaningless to anyone outside the file; easting/northing is what
        # goes on a plan, into a GPS, and into a report. Only shown once the
        # scene has a datum — there is no coordinate without one.
        self._coord_label = QLabel("")
        theme_style(self._coord_label, "color:{muted}; padding:0 8px;")
        bar.addPermanentWidget(self._coord_label)

        # SketchUp-style Measurements box (VCB), pinned bottom-right: a caption
        # ("Length" / "Dimensions" / "Distance") plus a boxed field showing the
        # live measurement, or what you're typing (highlighted while typing).
        self._vcb_buffer = ""
        self._vcb_live = ""
        self._vcb_name = QLabel("")
        theme_style(self._vcb_name, "color:{muted}; padding:0 4px;")
        self._vcb_value = QLabel("")
        self._vcb_value.setMinimumWidth(130)
        self._vcb_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._vcb_value.setStyleSheet(self._VCB_IDLE_STYLE)
        bar.addPermanentWidget(self._vcb_name)
        bar.addPermanentWidget(self._vcb_value)

        self.viewport.valueBufferChanged.connect(self._on_value_buffer)
        # The coordinate and measurement texts change on EVERY mouse move;
        # each setText dirties the status bar and Qt flushes the top-level
        # window's backing store (3072×1920 px at scale 2 on Marco's
        # laptop) — measured 2026-09-14 on the plaza: frames p90 190 ms with
        # the labels live, 57 ms with them frozen. They now settle at most
        # ~12 times a second, and only when the text actually changed.
        self._status_pending: dict = {}
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(self.STATUS_TEXT_MS)
        self._status_timer.timeout.connect(self._flush_status_texts)
        self.viewport.measurementChanged.connect(
            lambda text: self._queue_status_text("measurement", text))
        self.viewport.coordinateChanged.connect(
            lambda text: self._queue_status_text("coordinate", text))

    _VCB_IDLE_STYLE = (
        "color:#0F141B; background:#FFFFFF; border:1px solid #9aa3ad;"
        "border-radius:3px; padding:2px 8px;"
    )
    _VCB_ACTIVE_STYLE = (
        "color:#0F141B; background:#FFF3C4; border:1px solid #E0A800;"
        "border-radius:3px; padding:2px 8px;"
    )

    def _on_value_buffer(self, text: str) -> None:
        self._vcb_buffer = text
        self._refresh_vcb()

    #: How often the per-hover status texts may repaint (ms).
    STATUS_TEXT_MS = 80

    def _queue_status_text(self, which: str, text: str) -> None:
        self._status_pending[which] = text
        if not self._status_timer.isActive():
            self._status_timer.start()

    def _tool_key(self, tool) -> str | None:
        for key, t in self._tools.items():
            if t is tool:
                return key
        return None

    def _update_status_hint(self) -> None:
        """Refresh the one-line hint for the active tool and its step: the
        status bar's base message, under any timed one."""
        bar = self.statusBar()
        if bar is None:
            return
        from views.status_hints import hint_for
        vp = self.viewport
        tool = vp.active_tool
        nav = getattr(vp, "nav_mode", None)
        text = hint_for(self._tool_key(tool), tool, nav,
                        getattr(vp, "linear_inference_mode", None))
        # The tool's name leads its hint (it used to sit apart, on the right).
        if nav is not None:
            name = tr(nav.replace("_", " ").capitalize())
        elif tool is not None:
            name = tr(tool.name)
        else:
            name = ""
        if name and text:
            text = f"{name} — {text}"
        elif name:
            text = name
        if text != getattr(bar, "_base", None):
            if hasattr(bar, "_base"):
                # Keep a running timed message; only the base changes.
                bar._base = text
                if not bar._timer.isActive():
                    bar._msg.setText(text)
            else:
                bar.showMessage(text)

    @property
    def status_hint(self) -> str:
        bar = self.statusBar()
        return getattr(bar, "_base", None) or (bar.currentMessage() if bar else "")

    def _flush_status_texts(self) -> None:
        self._update_status_hint()
        pending, self._status_pending = self._status_pending, {}
        coord = pending.get("coordinate")
        if coord is not None and coord != self._coord_label.text():
            self._coord_label.setText(coord)
            # The compact readout above; the full one, zone included, on hover.
            self._coord_label.setToolTip(
                getattr(self.viewport, "_last_coordinate_full", "") or "")
        meas = pending.get("measurement")
        if meas is not None and meas != getattr(self, "_vcb_live", None):
            self._on_measurement(meas)

    def _on_measurement(self, text: str) -> None:
        self._vcb_live = text
        self._refresh_vcb()

    def _refresh_vcb(self) -> None:
        tool = self.viewport.active_tool
        # A tool may vary its caption with state (Circle: "Lados" before the
        # centre, "Radio" after); fall back to the static label.
        dynamic = getattr(tool, "vcb_caption", None) if tool is not None else None
        caption = (dynamic() if callable(dynamic)
                   else getattr(tool, "vcb_label", None)) if tool is not None \
            else None
        self._vcb_name.setVisible(caption is not None)
        self._vcb_value.setVisible(caption is not None)
        if caption is None:
            return
        self._vcb_name.setText(tr(caption))
        if self._vcb_buffer:
            self._vcb_value.setText(f"{self._vcb_buffer}")
            self._vcb_value.setStyleSheet(self._VCB_ACTIVE_STYLE)
        else:
            self._vcb_value.setText(self._vcb_live)
            self._vcb_value.setStyleSheet(self._VCB_IDLE_STYLE)

    # ---- Tool routing -------------------------------------------------------
    def _activate_tool(self, key: str) -> None:
        tool = self._tools[key]
        self.viewport.set_active_tool(tool)
        action = self._tool_actions.get(key)
        if action is not None:
            action.setChecked(True)
        self._tool_label.setText(tr("Tool: {name}", name=tr(tool.name)))
        self._refresh_vcb()
        self._update_status_hint()

    def _activate_nav(self, key: str) -> None:
        self.viewport.set_nav_mode(key)
        action = self._nav_actions.get(key)
        if action is not None:
            action.setChecked(True)
        self._tool_label.setText(
            tr("Nav: {name}", name=tr(key.capitalize())))
        self._refresh_vcb()
        self._update_status_hint()

    def _on_make_group(self) -> None:
        """SketchUp's Make Group (G) over the selection.

        Every path here ANSWERS. A refusal whispered into the status bar for
        five seconds, or an empty selection that returns in silence, reads to
        the user as "I pressed Create group and it does not create" — which
        is exactly how this was reported."""
        if self.viewport.scene.edit_group is not None:
            # Grouping INSIDE a group would have to land in that group's
            # children, not at the root where MakeGroupCommand puts it.
            self.viewport.flash_status(tr(
                "Leave the group first (Esc) — grouping inside a group is "
                "not wired up yet"), 4000)
            return
        sel = self.viewport.scene.selection
        faces = [f for f in sel if isinstance(f, Face)]
        edges = [e for e in sel if isinstance(e, Edge)]
        groups = [g for g in sel if isinstance(g, Group)]
        if len(groups) == 1 and not (faces or edges):
            # One group (or component) alone: wrapping it in a container of
            # itself is a Russian doll with nothing inside (@pacaeiro,
            # issue #35: «a group inside of a group that is equal to
            # itself… shouldn't be possible»). Grouping needs a second
            # thing — another group, or loose geometry.
            self.viewport.flash_status(tr(
                "That is already a group — select something else with it "
                "to group them together"), 4000)
            return
        if groups:
            # A group can hold groups now (2026-09-11): the container adopts
            # them and the loose part of the selection becomes its own mesh,
            # like SketchUp. What used to happen here was a dialog offering
            # to merge or explode, because opening a container baked it.
            from core.history import MakeNestedGroupCommand
            self.viewport.history.execute(
                MakeNestedGroupCommand(faces, edges, groups))
            self.viewport.flash_status(tr(
                "Grouped {n} group(s){extra} — double-click to go inside",
                n=len(groups),
                extra=(tr(" and the loose geometry") if (faces or edges)
                       else "")), 4000)
            self.viewport.update()
            return
        if not (faces or edges):
            self.viewport.flash_status(tr(
                "Select the geometry to group first"), 4000)
            return
        self.viewport.history.execute(MakeGroupCommand(faces, edges))
        self.viewport.update()

    def _on_make_component(self) -> None:
        """SketchUp's Make Component (G): the selection becomes a shared
        DEFINITION placed as an instance — every copy shares it."""
        if self.viewport.scene.edit_group is not None:
            self.viewport.flash_status(tr(
                "Leave the group first (Esc) — nested groups aren't "
                "supported yet"))
            return
        sel = self.viewport.scene.selection
        faces = [f for f in sel if isinstance(f, Face)]
        edges = [e for e in sel if isinstance(e, Edge)]
        groups = [g for g in sel if isinstance(g, Group)
                  and not getattr(g, "billboard", False)]
        count = sum(1 for g in self.viewport.scene.groups
                    if g.is_component()) + 1
        if len(groups) > 1 or (groups and (faces or edges)):
            # Several groups, or groups and loose geometry: ONE component
            # holding them, each still a group inside (Marco, 24-09, with
            # issue #90) — it used to make one component per group, or
            # refuse outright when loose geometry came along.
            from core.history import MakeComponentOfCommand
            name, ok = _prompts.get_text(
                self, tr("Make Component"), tr("Component name:"),
                text=tr("Component #{n}", n=count))
            if not ok:
                return
            self.viewport.history.execute(MakeComponentOfCommand(
                faces, edges, groups,
                name=name.strip() or tr("Component #{n}", n=count)))
            self.viewport.update()
            self.statusBar().showMessage(tr(
                "Component created — copies will share its definition"), 4000)
            return
        if groups:
            # One group converts in place — its mesh becomes the shared
            # definition, free (no geometry copied); a group of groups just
            # becomes what it holds a matrix for. The old answer was
            # "explode it first", which fed 230k faces through the loose
            # mesh for minutes (piscina report).
            g = groups[0]
            if g.is_component():
                self.viewport.flash_status(tr("It is a component already"))
                return
            from core.history import GroupToComponentCommand
            name, ok = _prompts.get_text(
                self, tr("Make Component"), tr("Component name:"),
                text=g.name or tr("Component"))
            if not ok:
                return
            self.viewport.history.execute(
                GroupToComponentCommand(g, name.strip() or None))
            self.viewport.update()
            self.statusBar().showMessage(tr(
                "Component created — copies will share its definition"), 4000)
            return
        if not faces and not edges:
            self.viewport.flash_status(
                tr("Select the geometry for the component first"))
            return
        name, ok = _prompts.get_text(
            self, tr("Make Component"), tr("Component name:"),
            text=tr("Component #{n}", n=count))
        if not ok:
            return
        self.viewport.history.execute(MakeGroupCommand(
            faces, edges, component=True,
            name=name.strip() or tr("Component #{n}", n=count)))
        self.viewport.update()
        self.statusBar().showMessage(tr(
            "Component created — copies will share its definition"), 4000)

    def _on_make_unique(self) -> None:
        from core.history import MakeUniqueCommand
        for g in [g for g in self.viewport.scene.selection
                  if isinstance(g, Group) and g.is_component()]:
            self.viewport.history.execute(MakeUniqueCommand(g))
        self.viewport.update()

    def _on_merge_groups(self) -> None:
        from core.history import MergeGroupsCommand
        groups = [e for e in self.viewport.scene.selection
                  if isinstance(e, Group)]
        if len(groups) < 2:
            return
        self.viewport.end_group_edit()
        self.viewport.history.execute(MergeGroupsCommand(groups))
        self.viewport.update()
        self.statusBar().showMessage(
            tr("{n} groups merged into one", n=len(groups)), 3000)

    def _on_change_axes(self, group) -> None:
        """Right-click ▸ Change Axes: three clicks give the group or
        component new local axes (tools/change_axes.py)."""
        tool = self._tools["change_axes"]
        tool.target = group
        self._activate_tool("change_axes")
        self.viewport.flash_status(tr("Click the new origin"), 4000)

    def _fill_intersect_menu(self, menu) -> None:
        from core.intersect import WITH_CONTEXT, WITH_MODEL, WITH_SELECTION
        for mode, label in ((WITH_MODEL, tr("With Model")),
                            (WITH_SELECTION, tr("With Selection")),
                            (WITH_CONTEXT, tr("With Context"))):
            menu.addAction(label, lambda m=mode: self._on_intersect_faces(m))

    def _on_intersect_faces(self, mode: str) -> None:
        """SketchUp's Intersect Faces: edges wherever the selection's faces
        cross the others (core/intersect.py), added to the context being
        edited — they split its faces there — in one undo step."""
        from core.edits import build_add_edges
        from core.intersect import segments_for
        scene = self.viewport.scene
        if not scene.selection:
            self.viewport.flash_status(tr("Select faces or groups first"))
            return
        segs = segments_for(scene, mode)
        if not segs:
            self.viewport.flash_status(tr("No faces cross the selection"))
            return
        self.viewport.history.execute(
            build_add_edges(scene, segs, detect_faces=True))
        self.viewport.flash_status(
            tr("{n} intersection edges added", n=len(segs)), 3000)

    def _on_split_into_pieces(self) -> None:
        """Regroup the selected group's contents by physical piece — the
        solids that do not touch (see :mod:`core.pieces`). The group stays
        one object; Explode afterwards gives each piece on its own."""
        from PySide6.QtWidgets import QApplication
        from core.history import SplitIntoPiecesCommand
        from core.pieces import split_into_pieces
        scene = self.viewport.scene
        if scene.edit_group is not None:
            self.viewport.flash_status(tr(
                "Leave the group first (Esc) to split it into pieces"))
            return
        groups = [g for g in scene.selection if isinstance(g, Group)
                  and not getattr(g, "billboard", False)]
        if len(groups) != 1:
            self.viewport.flash_status(tr(
                "Select one group or component to split into pieces"))
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            pieces = split_into_pieces(groups[0])
        finally:
            QApplication.restoreOverrideCursor()
        if not pieces:
            self.viewport.flash_status(tr(
                "Nothing to split: it is already in its pieces"))
            return
        self.viewport.history.execute(
            SplitIntoPiecesCommand(groups[0], pieces))
        self.viewport.flash_status(tr(
            "Split into {n} pieces — Explode Group sets them free",
            n=len(pieces)), 5000)
        self.viewport.update()

    def _on_explode_group(self) -> None:
        if self.viewport.scene.edit_group is not None:
            self.viewport.flash_status(tr(
                "Leave the group first (Esc) — nested groups aren't "
                "supported yet"))
            return
        groups = [g for g in self.viewport.scene.selection if isinstance(g, Group)]
        for g in groups:
            self.viewport.history.execute(ExplodeGroupCommand(g))
        if groups:
            self.viewport.update()

    def _on_convert_geopath(self) -> None:
        """Bake selected georef paths into real mesh geometry (Track G bridge).

        The trace crosses from the georef subsystem into the modelling engine
        *on demand*: each segment becomes a welded edge (a closed path auto-faces,
        so a traced footprint is ready to push/pull into a building), and the
        GeoPath is consumed. One undoable step.
        """
        from georef.geopath import GeoPath
        from core.edits import build_add_edges
        from core.history import CompoundCommand, DeleteGeoPathsCommand

        scene = self.viewport.scene
        paths = [p for p in scene.selection if isinstance(p, GeoPath)]
        if not paths:
            self.statusBar().showMessage(
                tr("Select a path to convert to geometry."), 3000)
            return
        cmds = []
        for path in paths:
            segs = [(a, b) for a, b in path.segments()]
            if segs:
                cmds.append(build_add_edges(scene, segs, detect_faces=True))
        cmds.append(DeleteGeoPathsCommand(paths))
        cmd = cmds[0] if len(cmds) == 1 else CompoundCommand(cmds)
        self.viewport.history.execute(cmd)
        self.viewport.update()

    # ---- Sections (SketchUp section planes) ---------------------------------
    def _set_section_visibility(self, attr: str, on: bool) -> None:
        setattr(self.viewport.scene, attr, bool(on))
        self.viewport.update()

    def _sync_section_menu(self) -> None:
        scene = self.viewport.scene
        for act, value in (
                (self._act_show_splanes,
                 getattr(scene, "show_section_planes", True)),
                (self._act_show_scuts,
                 getattr(scene, "show_section_cuts", True)),
                (getattr(self, "_act_hidden_objects", None),
                 getattr(scene, "show_hidden_objects", False)),
                (getattr(self, "_act_hidden_geometry", None),
                 getattr(scene, "show_hidden_geometry", False))):
            if act is None:
                continue
            act.blockSignals(True)
            act.setChecked(value)
            act.blockSignals(False)

    def _set_hidden_view(self, attr: str, on: bool) -> None:
        """View ▸ Hidden Objects / Geometry: a scene flag (it travels in the
        document and in scenes), a version bump so the pick index learns
        what became selectable, and a repaint."""
        scene = self.viewport.scene
        if bool(getattr(scene, attr, False)) == bool(on):
            return
        setattr(scene, attr, bool(on))
        if not on:
            # What the view no longer shows cannot stay selected: the ghost
            # group's orange outline outlived the switch (Marco,
            # 2026-09-21, issue #53).
            for ent in list(scene.selection):
                if scene.entity_hidden(ent) or getattr(ent, "hidden", False):
                    scene.selection.discard(ent)
        scene.version += 1
        self.viewport.update()

    def prompt_section_name(self, plane) -> None:
        """SketchUp's post-placement prompt: name + symbol (cancel keeps
        the defaults; the placement itself is already committed). «Don't
        ask again» keeps the defaults from then on — many users never name
        a section (issue #62, @pacaeiro); Preferences ▸ General turns the
        prompt back on."""
        if str(QSettings().value("section/ask_name", "1")) == "0":
            return
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QFormLayout, QLineEdit)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Name Section Plane"))
        form = QFormLayout(dlg)
        name_edit = QLineEdit(plane.name)
        sym_edit = QLineEdit(plane.symbol)
        sym_edit.setMaxLength(3)
        form.addRow(tr("Name"), name_edit)
        form.addRow(tr("Symbol"), sym_edit)
        no_more = QCheckBox(tr("Don't ask again — keep the default name "
                               "and symbol (Preferences ▸ General turns "
                               "this back on)"))
        form.addRow("", no_more)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() == QDialog.Accepted:
            plane.name = name_edit.text().strip() or plane.name
            plane.symbol = sym_edit.text().strip() or plane.symbol
            if no_more.isChecked():
                QSettings().setValue("section/ask_name", "0")
            self.viewport.update()

    def _selected_section_planes(self) -> list:
        from core.section import SectionPlane
        return [p for p in self.viewport.scene.selection
                if isinstance(p, SectionPlane)]

    def _on_reverse_section(self) -> None:
        from core.history import ReverseSectionPlaneCommand
        for plane in self._selected_section_planes():
            self.viewport.history.execute(ReverseSectionPlaneCommand(plane))
        self.viewport.update()

    def _on_toggle_active_section(self) -> None:
        from core.history import SetActiveSectionCommand
        planes = self._selected_section_planes()
        if not planes:
            return
        plane = planes[0]
        self.viewport.history.execute(
            SetActiveSectionCommand(None if plane.active else plane))
        self.viewport.update()

    def _on_align_view_to_section(self) -> None:
        """SketchUp's Align View: look straight at the cut face."""
        import math as _math
        planes = self._selected_section_planes()
        plane = planes[0] if planes else self.viewport.scene.active_section()
        if plane is None:
            return
        cam = self.viewport.camera
        n = plane.normal
        cam.target = QVector3D(plane.point)
        cam.pitch = _math.asin(max(-1.0, min(1.0, n.z())))
        if abs(n.x()) > 1e-9 or abs(n.y()) > 1e-9:
            cam.yaw = _math.atan2(n.y(), n.x())
        self.viewport.update()

    # ---- Display styles (SketchUp Styles) -----------------------------------
    def _apply_display_style(self, preset) -> None:
        """Activate a built-in style (a COPY — presets stay pristine)."""
        self.viewport.scene.display_style = preset.copy()
        self._sync_style_menu()
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Style: {name}", name=tr(preset.name)), 2000)

    def _set_style_field(self, name: str, value: bool) -> None:
        style = getattr(self.viewport.scene, "display_style", None)
        if style is None or getattr(style, name) == bool(value):
            return
        setattr(style, name, bool(value))
        self.viewport.update()

    def _sync_style_menu(self) -> None:
        """Reflect the scene's active style in the menu (loads, scene recall)."""
        style = getattr(self.viewport.scene, "display_style", None)
        if style is None:
            return
        for name, act in self._style_actions.items():
            act.setChecked(name == style.name)
        for act, value in ((self._act_style_edges, style.edges),
                           (self._act_style_profiles, style.profiles),
                           (getattr(self, "_act_section_fill", None),
                            getattr(style, "section_fill", True))):
            if act is None:      # menu still under construction
                continue
            act.blockSignals(True)
            act.setChecked(value)
            act.blockSignals(False)
        # The Styles/Shadows docks mirror the same state (guarded: the menu
        # builds before the docks on startup). Loads and scene recalls land
        # here too.
        sh = getattr(self.viewport.scene, "shadows", None)
        act = getattr(self, "_act_shadows", None)
        if act is not None and sh is not None:
            act.blockSignals(True)
            act.setChecked(sh.enabled)
            act.blockSignals(False)
        panel = getattr(self, "styles_panel", None)
        if panel is not None:
            panel.refresh()
        panel = getattr(self, "shadows_panel", None)
        if panel is not None:
            panel.refresh()

    def _on_delete_guides(self) -> None:
        """Remove every construction guide (SketchUp's Edit ▸ Delete Guides)."""
        from core.history import DeleteGuidesCommand
        guides = list(self.viewport.scene.guides)
        if guides:
            self.viewport.history.execute(DeleteGuidesCommand(guides))
            self.viewport.update()

    def _on_toggle_path_closed(self) -> None:
        from georef.geopath import GeoPath
        from core.history import ToggleGeoPathClosedCommand
        paths = [p for p in self.viewport.scene.selection if isinstance(p, GeoPath)]
        if paths:
            self.viewport.history.execute(ToggleGeoPathClosedCommand(paths))
            self.viewport.update()

    def _on_delete_selection(self) -> None:
        """Delete the current selection (any entity type), as one undoable step —
        the same logic the Select tool's Delete key runs, reachable from the
        context menu regardless of the active tool."""
        from core.mesh import Edge, Face
        from core.dimension import Dimension
        from core.guide import Guide
        from core.textlabel import TextLabel
        from georef.geopath import GeoPath
        from core.history import (
            CompoundCommand, DeleteDimensionsCommand, DeleteGeoPathsCommand,
            DeleteGroupCommand, DeleteGuidesCommand,
            DeleteImagePlanesCommand, DeleteTextLabelsCommand,
            EraseSelectionCommand,
        )
        from core.image_plane import ImagePlane
        sel = self.viewport.scene.selection
        if not sel:
            return
        edges = [e for e in sel if isinstance(e, Edge)]
        faces = [f for f in sel if isinstance(f, Face)]
        groups = [g for g in sel if isinstance(g, Group)]
        dims = [d for d in sel if isinstance(d, Dimension)]
        labels = [t for t in sel if isinstance(t, TextLabel)]
        paths = [p for p in sel if isinstance(p, GeoPath)]
        guides = [g for g in sel if isinstance(g, Guide)]
        from core.section import SectionPlane
        splanes = [p for p in sel if isinstance(p, SectionPlane)]
        cmds = []
        if edges or faces:
            cmds.append(EraseSelectionCommand(edges, faces))
        cmds.extend(DeleteGroupCommand(g) for g in groups)
        if guides:
            cmds.append(DeleteGuidesCommand(guides))
        images = [im for im in sel if isinstance(im, ImagePlane)]
        if images:
            cmds.append(DeleteImagePlanesCommand(images))
        if splanes:
            from core.history import DeleteSectionPlanesCommand
            cmds.append(DeleteSectionPlanesCommand(splanes))
        if dims:
            cmds.append(DeleteDimensionsCommand(dims))
        if labels:
            cmds.append(DeleteTextLabelsCommand(labels))
        if paths:
            cmds.append(DeleteGeoPathsCommand(paths))
        if cmds:
            self.viewport.history.execute(
                cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
            self.viewport.update()

    def _on_toggle_eyedropper(self, on: bool) -> None:
        """Arm (or cancel) a one-shot material sample. Arming picks the Paint
        tool too, so the click that follows the sample paints with what was
        just picked up — the SketchUp round trip in two clicks."""
        PaintTool.sample_armed = bool(on)
        if on:
            self._activate_tool("paint")
            self.viewport.flash_status(
                tr("Click a face to sample its material"))
        self.viewport._apply_tool_cursor()

    def release_eyedropper(self) -> None:
        """Called back by the tool once it has sampled: the button pops out
        on its own, so the state you see is the state you are in."""
        PaintTool.sample_armed = False      # the sample is done either way
        act = getattr(self, "_act_eyedropper", None)
        if act is not None and act.isChecked():
            act.blockSignals(True)
            act.setChecked(False)
            act.blockSignals(False)
        self.viewport._apply_tool_cursor()

    def show_viewport_context_menu(self, global_pos, locked_image=None) -> None:
        """SketchUp-style right-click menu, tailored to what's selected.
        ``locked_image``: a locked reference image under the cursor that the
        click did not select (geometry sat on top of it) — it gets its own
        Unlock / Delete entries, or it could never be reached again."""
        from core.mesh import Edge, Face
        from core.dimension import Dimension
        from georef.geopath import GeoPath

        sel = self.viewport.scene.selection
        from core.section import SectionPlane
        has_geopath = any(isinstance(e, GeoPath) for e in sel)
        has_group = any(isinstance(e, Group) for e in sel)
        has_mesh = any(isinstance(e, (Edge, Face)) for e in sel)
        # a single group alone has nothing to be grouped WITH (issue #35)
        lone_group = (len(sel) == 1 and has_group)
        sec_planes = [e for e in sel if isinstance(e, SectionPlane)]
        menu = QMenu(self)

        if locked_image is not None and locked_image not in sel:
            name = getattr(locked_image, "name", "") or tr("image")
            menu.addAction(tr("Unlock image “{name}”", name=name),
                           lambda im=locked_image: self._unlock_image(im))
            menu.addAction(tr("Delete image “{name}”", name=name),
                           lambda im=locked_image: self._delete_image(im))
            menu.addSeparator()

        if sec_planes:
            # SketchUp's section-plane context menu.
            menu.addAction(tr("Reverse"), self._on_reverse_section)
            act_active = menu.addAction(tr("Active Cut"),
                                        self._on_toggle_active_section)
            act_active.setCheckable(True)
            act_active.setChecked(sec_planes[0].active)
            menu.addAction(tr("Align View"), self._on_align_view_to_section)
            # Rafael, 50:45: «no sé cómo cambiarle el 1 por AA o BB». The
            # prompt only ever appeared the moment a plane was placed.
            menu.addAction(tr("Name and symbol…"),
                           lambda p=sec_planes[0]: self.prompt_section_name(p))
            menu.addSeparator()

        from core.image_plane import ImagePlane
        images = [e for e in sel if isinstance(e, ImagePlane)]
        if images:
            menu.addAction(tr("Image size…"), self._on_image_size)
            menu.addAction(tr("Image opacity…"), self._on_image_opacity)
            act_lock = menu.addAction(tr("Lock"), self._on_toggle_image_lock)
            act_lock.setCheckable(True)
            act_lock.setChecked(bool(images[0].locked))
            menu.addSeparator()

        if has_geopath:
            menu.addAction(tr("Terrain profile"), self._on_terrain_profile)
            closed_paths = [e for e in sel
                            if isinstance(e, GeoPath) and len(e.points) >= 3]
            if closed_paths:
                surf = menu.addMenu(tr("Terrain surface"))
                surf.addAction(tr("Flat (single slope)"),
                               lambda: self._on_set_surface("flat"))
                surf.addAction(tr("Draped (follow relief)"),
                               lambda: self._on_set_surface("draped"))
                surf.addAction(tr("None (line only)"),
                               lambda: self._on_set_surface(None))
            menu.addAction(tr("Convert Path to Geometry"), self._on_convert_geopath)
            menu.addAction(tr("Open / Close path"), self._on_toggle_path_closed)
            menu.addSeparator()
        if (has_mesh or has_group) and not lone_group:
            # Groups too, since 2026-09-11: a group can hold groups, so the
            # entry has to be there when the selection is nothing but groups
            # — which is exactly when you want it («seleccioné cuatro grupos
            # y solo me sale crear componente y unir grupos», Marco). Not
            # for ONE group on its own (issue #35).
            menu.addAction(tr("Make Group"), self._on_make_group)
        if has_mesh:
            menu.addAction(tr("Make Component…"), self._on_make_component)
        if any(isinstance(e, Face) for e in sel):
            # SketchUp puts Reverse Faces in the face's own right-click menu,
            # which is where anyone looks for it. It lived only in the Edit
            # menu and Marco could not find it (2026-09-10).
            menu.addAction(tr("Reverse Faces"), self._on_reverse_faces)
            menu.addAction(tr("Orient Faces"), self._on_orient_faces)
            face = self._single_textured_face()
            if face is not None:
                # SketchUp's Texture submenu, on a face with an image.
                texm = menu.addMenu(tr("Texture"))
                texm.addAction(tr("Position"), self._on_texture_position)
                texm.addAction(tr("Reset Position"), self._on_texture_reset)
        loose_edges = [e for e in sel if isinstance(e, Edge)]
        if loose_edges and all(e in self.viewport.scene.mesh.edges
                               for e in loose_edges):
            # SketchUp's Divide: a line or an arc into N equal pieces
            # (issue #63, @pacaeiro: «It's a needed command»).
            menu.addAction(tr("Divide…"), self._on_divide)
        if self._hideable(sel):
            menu.addAction(tr("Hide"), self._on_hide)
        if any(self.viewport.scene.entity_hidden(e)
               or (isinstance(e, Edge) and getattr(e, "hidden", False))
               for e in sel):
            menu.addAction(tr("Unhide"), self._on_unhide_selected)
        self._add_layer_submenu(menu, sel)
        self._add_select_submenu(menu, sel)
        if has_group:
            groups = [e for e in sel if isinstance(e, Group)]
            if len(groups) == 1:
                # SketchUp's Edit Group / Edit Component: the double-click
                # by another road. (No parameters on the slot:
                # ``triggered`` would hand its bool to one.)
                one = groups[0]
                menu.addAction(tr("Edit Group"),
                               lambda: self.viewport.begin_group_edit(one))
            text = self._selected_text3d()
            if text is not None:
                from core.text3d import text_is_pristine
                if text_is_pristine(text):
                    menu.addAction(tr("Edit 3D Text…"),
                                   lambda: self._on_edit_3d_text(text))
                else:
                    # A letter touched by hand would be thrown away by a
                    # regeneration, so the text is plain geometry now:
                    # the entry stays, greyed, saying why.
                    off = menu.addAction(
                        tr("Edit 3D Text… (letters edited by hand)"))
                    off.setEnabled(False)
            if (any(isinstance(e, Group) and not e.is_component()
                    and not getattr(e, "billboard", False) for e in sel)
                    or sum(1 for e in sel if isinstance(e, Group)) >= 2):
                # Convert a classic group into a component IN PLACE (free —
                # no explode detour): the door the piscina hedge needed.
                menu.addAction(tr("Make Component…"), self._on_make_component)
            menu.addAction(tr("Explode Group"), self._on_explode_group)
            if sum(1 for e in sel if isinstance(e, Group)
                   and not getattr(e, "billboard", False)) == 1:
                menu.addAction(tr("Split into Pieces"),
                               self._on_split_into_pieces)
            if sum(1 for e in sel if isinstance(e, Group)) >= 2:
                # The fix-my-grouping path: fuse the selected groups into
                # one WITHOUT routing their geometry through the loose mesh
                # (explode + regroup chokes on leafy imports).
                menu.addAction(tr("Merge Groups"), self._on_merge_groups)
            if any(isinstance(e, Group) and e.is_component() for e in sel):
                menu.addAction(tr("Make Unique"), self._on_make_unique)
            if len(groups) == 1 and len(sel) == 1:
                menu.addAction(tr("Change Axes"),
                               lambda g=groups[0]: self._on_change_axes(g))
            # SketchUp offers the Solid Tools on a selection of solids.
            from core.solids import is_solid
            solid = [e for e in sel if isinstance(e, Group) and is_solid(e)]
            if len(solid) >= 2 and len(solid) == len(groups):
                menu.addAction(tool_icon("outer_shell"), tr("Outer Shell"),
                               lambda: self._activate_tool("outer_shell"))
                sm = menu.addMenu(tr("Solid Tools"))
                keys = ["solid_intersect", "solid_union"]
                if len(solid) == 2:
                    keys.append("solid_split")
                for key in keys:
                    sm.addAction(tool_icon(key), tr(self._tools[key].name),
                                 lambda k=key: self._activate_tool(k))
        if any(isinstance(e, Face) for e in sel) or has_group:
            self._fill_intersect_menu(menu.addMenu(tr("Intersect Faces")))
        if has_mesh or has_group:
            menu.addAction(tr("Cut"), lambda: self.viewport.cut_selection())
            menu.addAction(tr("Copy"), lambda: self.viewport.copy_selection())
        if sel:
            menu.addAction(tr("Delete"), self._on_delete_selection)
            act_clear = menu.addAction(tr("Clear selection"),
                                       self.viewport.scene.clear_selection)
            act_clear.triggered.connect(self.viewport.update)
            menu.addSeparator()

        from formats import clip as clip_transfer
        if getattr(self.viewport, "clipboard", None) or clip_transfer.available():
            menu.addAction(tr("Paste"), self._on_paste)
        menu.addAction(tr("Zoom Extents"), self._on_zoom_extents)
        menu.addSeparator()
        undo = menu.addAction(tr("Undo"), self._on_undo)
        undo.setEnabled(bool(self.viewport.history.undo_stack))
        redo = menu.addAction(tr("Redo"), self._on_redo)
        redo.setEnabled(bool(self.viewport.history.redo_stack))

        menu.exec(global_pos)

    def _single_textured_face(self):
        """``(face, side)``: the one selected face with an image texture on
        the side the right-click saw — SketchUp's Texture menu acts on the
        side you click; when only the other side carries an image, that
        one (Marco painted the underside of a slab from above, 2026-09-15).
        ``None`` otherwise."""
        from core.mesh import Face
        from tools.paint import clicked_back_side
        from tools.texture_position import TexturePositionTool
        faces = [e for e in self.viewport.scene.selection if isinstance(e, Face)]
        if len(faces) != 1:
            return None
        face = faces[0]
        px = getattr(self.viewport, "_context_pixel", None)
        clicked = "front"
        if px is not None and clicked_back_side(self.viewport, face, None, px[0], px[1]):
            clicked = "back"
        other = "back" if clicked == "front" else "front"
        for side in (clicked, other):
            if TexturePositionTool.side_texture(face, side) is not None:
                return face, side
        return None

    def _on_texture_position(self) -> None:
        """Texture ▸ Position: the pins on the tile under the right-click."""
        hit = self._single_textured_face()
        if hit is None:
            return
        face, side = hit
        tool = self._tools["texture_position"]
        at = None
        px = getattr(self.viewport, "_context_pixel", None)
        if px is not None:
            from core.snap import face_plane_world
            origin, direction = self.viewport._pixel_to_ray(px[0], px[1])
            if origin is not None:
                p0, n = face_plane_world(face, None)
                at = self.viewport._ray_plane(origin, direction, p0, n)
        self._activate_tool("texture_position")
        if not tool.begin(self.viewport, face, at, side=side):
            self._activate_tool("select")

    def _on_texture_reset(self) -> None:
        """Texture ▸ Reset Position: back to the default planar projection
        (no per-face map, no rotation) on the clicked side."""
        hit = self._single_textured_face()
        if hit is None:
            return
        face, side = hit
        from tools.texture_position import TexturePositionTool
        tex = TexturePositionTool.side_texture(face, side) or {}
        if "uvw" not in tex and "rot" not in tex:
            return
        flat = {k: v for k, v in tex.items() if k not in ("uvw", "rot")}
        self.viewport.history.execute(
            TexturePositionTool.side_command(face, side, flat))
        self.viewport.update()

    def _add_select_submenu(self, menu, sel) -> None:
        """Right-click ▸ Select, SketchUp's: grow the selection by what it
        touches or what it shares (issue #106, @pacaeiro). Each entry acts
        in the current editing context only, like Select All."""
        from core.select_ops import (all_connected, bounding_edges,
                                     same_layer, same_material)
        has_mesh = any(isinstance(e, (Edge, Face)) for e in sel)
        has_face = any(isinstance(e, Face) for e in sel)
        has_group = any(isinstance(e, Group) for e in sel)
        if not (has_mesh or has_group):
            return
        scene = self.viewport.scene
        from PySide6.QtWidgets import QMenu
        sub = QMenu(tr("Select"), menu)
        menu.addMenu(sub)

        def grow(fn):
            def run(_checked=False):
                found = fn(list(scene.selection))
                scene.select(found)
                self.viewport.notify_scene_changed()
                self.viewport.update()
                self.statusBar().showMessage(
                    tr("{n} entities selected", n=len(scene.selection)), 2500)
            return run

        if has_mesh:
            sub.addAction(tr("All Connected")).triggered.connect(
                grow(all_connected))
        if has_face:
            sub.addAction(tr("Bounding Edges")).triggered.connect(
                grow(bounding_edges))
        if has_face or any(getattr(e, "material", None) for e in sel
                           if isinstance(e, Group)):
            sub.addAction(tr("All with Same Material")).triggered.connect(
                grow(lambda s: same_material(scene, s)))
        sub.addAction(tr("All on Same Layer")).triggered.connect(
            grow(lambda s: same_layer(scene, s)))

    def _add_layer_submenu(self, menu, sel) -> None:
        """Right-click ▸ Layer ▸ the document's layers, the selection's own
        one ticked, plus «New layer…». Not SketchUp's (its road is Entity
        Info), but it is where Rafael looked — «botón derecho… no lo veo
        tampoco» (2026-09-16, 39:30) — and it costs nothing to be there."""
        from core.dimension import Dimension
        from core.layers import layer_of
        from core.textlabel import TextLabel
        targets = [e for e in sel
                   if isinstance(e, (Face, Edge, Group, Dimension, TextLabel))]
        if not targets:
            return
        current = {layer_of(e) for e in targets}
        # Parented explicitly: built in a helper, a submenu returned by
        # ``addMenu(str)`` can be collected with this frame's locals before
        # the menu ever opens.
        from PySide6.QtWidgets import QMenu
        sub = QMenu(tr("Layer"), menu)
        menu.addMenu(sub)
        for ly in self.viewport.scene.layers:
            act = sub.addAction(ly.name)
            act.setCheckable(True)
            act.setChecked(len(current) == 1 and ly.name in current)
            act.triggered.connect(
                lambda _c=False, name=ly.name: self._assign_layer(name))
        sub.addSeparator()
        sub.addAction(tr("New layer…"), self._assign_new_layer)

    def _assign_layer(self, name: str) -> None:
        """Move the selection's taggable entities onto ``name`` (created if
        new), undoable."""
        from core.dimension import Dimension
        from core.history import AssignLayerCommand
        from core.layers import layer_of
        from core.textlabel import TextLabel
        targets = [e for e in self.viewport.scene.selection
                   if isinstance(e, (Face, Edge, Group, Dimension, TextLabel))
                   and layer_of(e) != name]
        if not targets:
            return
        self.viewport.history.execute(AssignLayerCommand(targets, name))
        self.viewport.update()
        self.statusBar().showMessage(
            tr("{n} entities moved to '{layer}'", n=len(targets), layer=name),
            2500)

    def _assign_new_layer(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        scene = self.viewport.scene
        base = tr("Layer")
        n = 1
        while scene.layer(f"{base} {n}") is not None:
            n += 1
        name, ok = _prompts.get_text(
            self, tr("New layer"), tr("Layer name:"), text=f"{base} {n}")
        name = (name or "").strip()
        if ok and name:
            self._assign_layer(name)

    def _hideable(self, entities) -> list:
        """The objects, faces and edges in ``entities`` that Hide acts on
        (the ones not hidden already): a group picked inside an open
        container is the child itself; one picked at the top level is the
        top-level object."""
        from core.history import _is_hidden
        return [e for e in entities
                if isinstance(e, (Edge, Face, Group)) and not _is_hidden(e)]

    def _on_hide(self) -> None:
        """SketchUp's Edit ▸ Hide: the selected objects (groups,
        components), faces and edges stop drawing, picking and exporting —
        they are still in the document and come back with Unhide, with
        View ▸ Hidden Objects / Geometry, or with a scene that remembers
        them visible."""
        from core.history import HideCommand
        targets = self._hideable(self.viewport.scene.selection)
        if not targets:
            self.statusBar().showMessage(
                tr("Select an object, faces or edges first."), 3000)
            return
        self.viewport.history.execute(HideCommand(targets, hidden=True))
        self.viewport.update()
        n_obj = sum(1 for e in targets if isinstance(e, Group))
        n_face = sum(1 for e in targets if isinstance(e, Face))
        n_edge = len(targets) - n_obj - n_face
        self.statusBar().showMessage(
            tr("Hid {objects} object(s), {faces} face(s) and {edges} "
               "edge(s) — Edit ▸ Unhide brings them back",
               objects=n_obj, faces=n_face, edges=n_edge), 4000)

    def _on_unhide_selected(self) -> None:
        """SketchUp's Edit ▸ Unhide ▸ Selected — reachable once View ▸
        Hidden Objects / Geometry lets hidden things be selected."""
        from core.history import HideCommand, _is_hidden
        targets = [e for e in self.viewport.scene.selection
                   if isinstance(e, (Edge, Face, Group)) and _is_hidden(e)]
        if not targets:
            self.statusBar().showMessage(
                tr("Nothing hidden in the selection — turn on Camera ▸ "
                   "Hidden Objects / Geometry to select hidden things."), 4000)
            return
        self.viewport.history.execute(HideCommand(targets, hidden=False))
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Unhid {n} entities.", n=len(targets)), 3000)

    def _on_unhide_last(self) -> None:
        """SketchUp's Edit ▸ Unhide ▸ Last: the most recent Hide whose
        entities are still hidden comes back, as its own undoable step."""
        from core.history import HideCommand
        for cmd in reversed(self.viewport.history.undo_stack):
            if isinstance(cmd, HideCommand) and cmd.hides:
                still = [e for e in cmd.entities if getattr(e, "hidden", False)]
                if still:
                    self.viewport.history.execute(HideCommand(still, hidden=False))
                    self.viewport.update()
                    self.statusBar().showMessage(
                        tr("Unhid {n} entities.", n=len(still)), 3000)
                    return
        self.statusBar().showMessage(tr("Nothing to unhide."), 3000)

    def _hidden_everywhere(self) -> list:
        """Every hidden object in the document (nested ones too) plus the
        hidden faces and edges of the mesh being edited — what Unhide ▸ All
        restores.
        Objects everywhere, because a hidden child inside a closed container
        can only be reached by opening it, and the point of Unhide All is
        not to have to hunt."""
        from core.purge import iter_groups
        scene = self.viewport.scene
        out = [g for g in iter_groups(scene.groups) if g.hidden]
        out += [f for f in scene.mesh.faces if f.attrs.get("hidden")]
        out += [e for e in scene.mesh.edges if getattr(e, "hidden", False)]
        return out

    def _on_unhide_all(self) -> None:
        """SketchUp's Edit ▸ Unhide ▸ All."""
        from core.history import HideCommand
        targets = self._hidden_everywhere()
        if not targets:
            self.statusBar().showMessage(tr("Nothing is hidden."), 3000)
            return
        self.viewport.history.execute(HideCommand(targets, hidden=False))
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Unhid {n} entities.", n=len(targets)), 3000)

    # Older spellings, kept for callers that grew up with them.
    _on_hide_edges = _on_hide
    _on_unhide_all_edges = _on_unhide_all

    def _on_toggle_shadows(self, on: bool) -> None:
        """Camera ▸ Shadows: flip the scene's sun on/off (the tray panel
        holds the date/time/darkness detail)."""
        sh = getattr(self.viewport.scene, "shadows", None)
        if sh is None or sh.enabled == bool(on):
            return
        sh.enabled = bool(on)
        self.viewport.scene.version += 1
        panel = getattr(self, "shadows_panel", None)
        if panel is not None:
            panel.refresh()
        self.viewport.update()

    def _on_divide(self) -> None:
        """Divide the selected edges / curves into N equal pieces (#63)."""
        from PySide6.QtWidgets import QInputDialog
        from core.edits import divide_edges
        from core.history import SnapshotMutation
        scene = self.viewport.scene
        edges = [e for e in scene.selection if isinstance(e, Edge)
                 and e in scene.mesh.edges]
        if not edges:
            return
        n, ok = QInputDialog.getInt(
            self, tr("Divide"), tr("Number of segments:"), 2, 2, 500, 1)
        if not ok:
            return
        made = []
        self.viewport.history.execute(SnapshotMutation(
            lambda sc: made.append(divide_edges(sc.mesh, edges, n))))
        scene.selection.clear()
        scene.version += 1
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Divided into {n} segments", n=n), 3000)

    def _on_reverse_faces(self) -> None:
        """SketchUp's Reverse Faces: flip the winding (and thus the front/back
        sides) of the selected faces."""
        from core.history import FlipFacesCommand
        from core.mesh import Face as MeshFace
        faces = [e for e in self.viewport.scene.selection
                 if isinstance(e, MeshFace)]
        if not faces:
            self.statusBar().showMessage(
                tr("Select one or more faces first."), 3000)
            return
        self.viewport.history.execute(FlipFacesCommand(faces))
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Reversed {n} face(s).", n=len(faces)), 3000)

    def _on_orient_faces(self) -> None:
        """SketchUp's Orient Faces (issue #77): every face connected to the
        chosen one turns to wind like it — its front side is the one the
        rest take."""
        from core.history import FlipFacesCommand
        from core.mesh import Face as MeshFace
        from core.orient_faces import faces_to_flip
        faces = [e for e in self.viewport.scene.selection
                 if isinstance(e, MeshFace)]
        if len(faces) != 1:
            self.statusBar().showMessage(
                tr("Select the one face the others should match."), 3000)
            return
        flip = faces_to_flip(faces[0])
        if flip:
            self.viewport.history.execute(FlipFacesCommand(flip))
            self.viewport.update()
        self.statusBar().showMessage(
            tr("Oriented {n} face(s) like the selected one.", n=len(flip))
            if flip else tr("The connected faces already match."), 3000)

    def _on_heal_overlaps(self) -> None:
        cmd = HealOverlapsCommand()
        self.viewport.history.execute(cmd)
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Healed {n} overlapping face(s).", n=cmd.healed) if cmd.healed
            else tr("No overlapping faces found."), 3000)

    def _on_rebuild_planar(self) -> None:
        # With faces selected, rebuild just THEIR plane — the per-plane
        # rebuild every stroke already runs — so a 3D model keeps the tool
        # (issue #73, @pacaeiro). Nothing selected: the whole flat drawing,
        # as before.
        from core.mesh import Face as MeshFace
        picked = [e for e in self.viewport.scene.selection
                  if isinstance(e, MeshFace)]
        if picked:
            plane = self._common_plane(picked)
            if plane is None:
                self.statusBar().showMessage(tr(
                    "The selected faces must lie on one plane."), 3000)
                return
            from core.history import RebuildPlaneFacesCommand
            cmd = RebuildPlaneFacesCommand(*plane)
            self.viewport.history.execute(cmd)
            self.viewport.update()
            self.statusBar().showMessage(tr(
                "Rebuilt {n} face(s) on the selected plane.", n=cmd.rebuilt),
                3000)
            return
        cmd = RebuildPlanarFacesCommand()
        self.viewport.history.execute(cmd)
        self.viewport.update()
        if not cmd.flat:
            msg = tr("Rebuild Faces only works on a flat (single-plane) drawing.")
        else:
            msg = tr("Rebuilt {n} face(s) from the edge graph.", n=cmd.rebuilt)
        self.statusBar().showMessage(msg, 3000)

    @staticmethod
    def _common_plane(faces):
        """(origin, unit normal) of the plane every face lies on, or None."""
        from PySide6.QtGui import QVector3D
        n = faces[0].normal()
        length = n.length()
        if length < 1e-9:
            return None
        n = n / length
        o = QVector3D(faces[0].loop[0].position)
        tol = 1e-4                  # RebuildPlaneFacesCommand's own
        for f in faces:
            for loop in [f.loop, *f.hole_loops]:
                for v in loop:
                    if abs(QVector3D.dotProduct(v.position - o, n)) > tol:
                        return None
        return o, n

    def _on_paste(self) -> None:
        # A copy made in ANOTHER IngeTrazo window wins over this window's
        # older one, as a system clipboard does (issue #76).
        from formats import clip as clip_transfer
        try:
            other = clip_transfer.foreign()
        except Exception:  # noqa: BLE001 - a bad clipboard must not break Paste
            other = None
        if other is not None:
            old = self.viewport.clipboard
            drop = getattr(self.viewport, "_drop_clip_protos", None)
            if old and callable(drop):
                drop(old)
            self.viewport.clipboard = other
        if self.viewport.clipboard is None:
            return
        self.viewport.set_active_tool(PasteTool())
        for action in self._tool_actions.values():
            action.setChecked(False)
        self._tool_label.setText(tr("Tool: {name}", name=tr("Paste")))
        self._refresh_vcb()

    def _cancel_tool(self) -> None:
        """Esc, escalating like the viewport: release a sticky constraint
        (axis lock / reference) first, then cancel an in-progress action;
        with nothing in progress, clear the selection."""
        # One cascade, the viewport's — this action's shortcut fires before
        # the viewport ever sees the key, and its own copy lacked the
        # «step out of the group» stop.
        self.viewport.escape()

    # ---- View navigation ----------------------------------------------------
    def _on_zoom_extents(self) -> None:
        bounds = self.viewport.scene.bounds()
        # Face-me figures count too, as in SketchUp's Zoom Extents:
        # ``Scene.bounds()`` leaves them out (they draw per frame), so a new
        # document — the scale figure alone — framed nothing, and Zoom
        # Extents did nothing after zooming far away (Marco, 23-09).
        figs = self._figure_bounds()
        if figs is not None:
            lo, hi = figs
            if bounds[0] is not None:
                from PySide6.QtGui import QVector3D
                lo = QVector3D(min(lo.x(), bounds[0].x()), min(lo.y(), bounds[0].y()),
                               min(lo.z(), bounds[0].z()))
                hi = QVector3D(max(hi.x(), bounds[1].x()), max(hi.y(), bounds[1].y()),
                               max(hi.z(), bounds[1].z()))
            bounds = (lo, hi)
        if bounds[0] is None:
            # ``Scene.bounds()`` covers editable geometry only. A document
            # holding just a survey (the normal state right after importing
            # one) would otherwise make Zoom Extents do nothing at all.
            survey = getattr(self.viewport.scene, "photo_mesh", None)
            if survey is None or not getattr(survey, "visible", False):
                return
            bounds = survey.bounds()
            if bounds[0] is None:
                return
        self.viewport.camera.fit_box(bounds[0], bounds[1])
        self.viewport.update()

    def _figure_bounds(self):
        """World box of the visible face-me figures, or None."""
        from PySide6.QtGui import QVector3D
        from core.group import placement_points
        scene = self.viewport.scene
        lo = hi = None
        for g in scene.groups:
            if not getattr(g, "billboard", False) or not scene.entity_visible(g):
                continue
            pts = placement_points(g)
            if not len(pts):
                continue
            a, b = pts.min(axis=0), pts.max(axis=0)
            lo = a if lo is None else [min(x, y) for x, y in zip(lo, a)]
            hi = b if hi is None else [max(x, y) for x, y in zip(hi, b)]
        if lo is None:
            return None
        return QVector3D(*map(float, lo)), QVector3D(*map(float, hi))

    def _ensure_composer(self):
        """The composer window, created but not shown — the sheet strip's
        menu manages sheets through it without opening it."""
        if getattr(self, "_composer", None) is None:
            from views.composer import ComposerWindow
            self._composer = ComposerWindow(self)
        return self._composer

    def _sheet_tab_menu(self, index: int, global_pos) -> None:
        self._ensure_composer().sheet_tab_menu(index, global_pos, self)
        self._refresh_sheet_tabs()

    def _on_open_composer(self) -> None:
        """Open (or raise) the sheet composer — see docs/composer-plan.md."""
        self._ensure_composer()
        self._composer.show()
        self._composer.raise_()
        self._composer.activateWindow()

    # ---- Model / sheet tabs (the strip at the bottom) -----------------------
    def _refresh_sheet_tabs(self) -> None:
        """This window shows the model, so its strip always marks «Model».
        Beside it, ONE sheet: the last one opened — the model window only
        goes model ↔ sheet, and all the sheets are tabs in the composer
        (Marco, 23-09: «en el modelo solo alternar entre el modelo y la
        lámina… cuando regrese a lámina, que regrese a la lámina 2»). A
        document without sheets offers «+» instead."""
        tabs = getattr(self, "_sheet_tabs", None)
        if tabs is None:
            return
        comps = getattr(self.viewport.scene, "compositions", None) or []
        if not comps:
            self._strip_sheets = []
            tabs.set_show_new(True)
            tabs.refresh([], None)
            return
        comp = getattr(getattr(self, "_composer", None), "comp", None)
        if comp is not None and comp in comps:
            last = comps.index(comp)
        else:
            last = min(max(getattr(self, "_last_sheet", 0), 0), len(comps) - 1)
        self._last_sheet = last
        self._strip_sheets = [last]
        tabs.set_show_new(False)
        tabs.refresh([comps[last].name], None)

    def _to_sheets(self) -> None:
        comps = getattr(self.viewport.scene, "compositions", None) or []
        if not comps:
            self._show_new_sheet()
            return
        last = min(max(getattr(self, "_last_sheet", 0), 0), len(comps) - 1)
        self._show_sheet(last)

    def _show_strip_sheet(self, k: int) -> None:
        """A sheet tab of THIS strip (it shows only the last sheet)."""
        sheets = getattr(self, "_strip_sheets", None) or []
        self._show_sheet(sheets[k] if 0 <= k < len(sheets) else k)

    def _strip_sheet_menu(self, k: int, pos) -> None:
        sheets = getattr(self, "_strip_sheets", None) or []
        self._sheet_tab_menu(sheets[k] if 0 <= k < len(sheets) else k, pos)

    def _show_model(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._refresh_sheet_tabs()

    def _show_sheet(self, index: int) -> None:
        """A sheet tab: the composer opens on that sheet. This window keeps
        showing the model, so its own strip snaps back to «Model»."""
        self._last_sheet = index
        self._on_open_composer()
        self._composer.show_sheet(index)
        self._refresh_sheet_tabs()

    def _show_new_sheet(self) -> None:
        """The «+» tab: the composer on a NEW sheet. A document without
        sheets gets its first one just by opening the composer."""
        comps = getattr(self.viewport.scene, "compositions", None) or []
        had = len(comps)
        self._on_open_composer()
        if len(self.viewport.scene.compositions) == had:
            self._composer._on_comp_add()
        self._composer.show_sheet(len(self.viewport.scene.compositions) - 1)
        self._refresh_sheet_tabs()

    def _on_standard_view(self, key: str) -> None:
        self.viewport.camera.set_view(key)
        self.viewport.update()

    def _on_terrain_profile(self) -> None:
        """Show the profile dock and profile the current selection (Track G)."""
        self.profile_dock.show()
        self.profile_dock.raise_()
        self.profile_dock.compute_from_selection()

    def on_viewport_hover(self, screen_x: float, screen_y: float) -> None:
        """Plan→profile link: mark the station of the route point under the
        cursor in the open profile (Track G)."""
        if self.profile_dock.isVisible():
            self.profile_dock.indicate_at_screen(screen_x, screen_y)

    # ---- Terrain-surface fill (Track G) -------------------------------------
    def _surface_dem(self, datum):
        """Shared DEM sampler for surface fills, rebuilt when the datum changes."""
        if getattr(self, "_surf_sampler", None) is not None \
                and self._surf_datum is datum:
            return self._surf_sampler
        from georef.dem import DEMSampler
        self._surf_sampler = DEMSampler(datum, parent=self)
        self._surf_datum = datum
        self._surf_sampler.changed.connect(self._rebuild_surfaces)
        self._surf_sampler.changed.connect(self._build_terrain)
        return self._surf_sampler

    def _on_set_surface(self, mode) -> None:
        from georef.geopath import GeoPath
        from core.history import SetGeoPathSurfaceCommand
        paths = [p for p in self.viewport.scene.selection
                 if isinstance(p, GeoPath) and len(p.points) >= 3]
        if not paths:
            return
        self.viewport.history.execute(SetGeoPathSurfaceCommand(paths, mode))
        self._rebuild_surfaces()

    def _rebuild_surfaces(self) -> None:
        """(Re)compute the 3D triangles of every surfaced path from the DEM."""
        from georef.surface import build_surface
        scene = self.viewport.scene
        datum = getattr(scene, "georef", None)
        surfaced = [p for p in scene.geo_paths if getattr(p, "surface", None)]
        if datum is None:
            for p in surfaced:
                p._surface_tris = None
            self.viewport.update()
            return
        sampler = self._surface_dem(datum)
        area = None
        for p in surfaced:
            xs = [pt.x() for pt in p.points]
            ys = [pt.y() for pt in p.points]
            lo = self._local_to_ll(datum, min(xs), min(ys))
            hi = self._local_to_ll(datum, max(xs), max(ys))
            sampler.ensure_area(min(lo[0], hi[0]), min(lo[1], hi[1]),
                                max(lo[0], hi[0]), max(lo[1], hi[1]))
            p._surface_tris = build_surface(p, sampler, datum)
        self.viewport.update()

    @staticmethod
    def _local_to_ll(datum, x, y):
        from PySide6.QtGui import QVector3D
        lat, lon, _ = datum.local_to_geodetic(QVector3D(x, y, 0.0))
        return lat, lon

    def _on_surfaces_scene_changed(self) -> None:
        """Re-drape surfaced paths when their nodes move (version bump)."""
        if any(getattr(p, "surface", None) for p in self.viewport.scene.geo_paths):
            self._rebuild_surfaces()

    # ---- 3D terrain (Track G, G2 full) --------------------------------------
    def set_terrain_enabled(self, on: bool) -> None:
        self._terrain_on = on
        if on:
            terrain = getattr(self.viewport.scene, "terrain", None)
            if terrain is not None and not getattr(terrain, "visible", True):
                terrain.visible = True      # hidden by a scene: just show it
                self.viewport.update()
                return
            self._build_terrain()
        else:
            self.viewport.scene.terrain = None
            self.viewport.upload_terrain(None)
            self.viewport.update()

    @staticmethod
    def _capture_bbox(layer):
        """Local-metre bounding box ``(minx, miny, maxx, maxy)`` of the capture
        patches — the area the 3D terrain should cover."""
        patches = getattr(layer, "patches", None) or [(0, 0, layer.radius_m,
                                                        layer.radius_m)]
        minx = min(cx - hw for cx, cy, hw, hh in patches)
        maxx = max(cx + hw for cx, cy, hw, hh in patches)
        miny = min(cy - hh for cx, cy, hw, hh in patches)
        maxy = max(cy + hh for cx, cy, hw, hh in patches)
        return minx, miny, maxx, maxy

    def _build_terrain(self) -> None:
        """(Re)build the 3D terrain from the DEM + base-map tiles (async-ready)."""
        if not getattr(self, "_terrain_on", False):
            return
        from georef.terrain import build_mosaic, build_terrain
        from georef.surface import ground_reference
        scene = self.viewport.scene
        datum = getattr(scene, "georef", None)
        layer = getattr(scene, "tile_layer", None)
        if datum is None or layer is None:
            return
        sampler = self._surface_dem(datum)
        zoom = layer.zoom
        # The terrain covers the captured area (the drawn patches' bounding box),
        # not a fixed square — so the 3D matches what you captured.
        bbox = self._capture_bbox(layer)
        minx, miny, maxx, maxy = bbox
        lo = self._local_to_ll(datum, minx, miny)
        hi = self._local_to_ll(datum, maxx, maxy)
        sampler.ensure_area(min(lo[0], hi[0]), min(lo[1], hi[1]),
                            max(lo[0], hi[0]), max(lo[1], hi[1]))
        self.viewport.prefetch_tiles(layer.source, layer.flat_tiles(datum), zoom)
        # When a survey has already fixed the scene's vertical zero, the DEM
        # terrain must use the SAME zero or the two grounds render tens of
        # metres apart. (They still differ by the geoid/ellipsoid separation —
        # that gap is real, not a bug, and is why elevations are labelled with
        # where they came from.)
        ground = float(datum.alt) if datum.alt else ground_reference(sampler, datum)
        if ground is None:
            return                         # DEM not ready — retry on changed
        terrain = build_terrain(datum, sampler, ground, bbox, zoom=zoom)
        if terrain is None:
            return                         # DEM grid not fully loaded yet
        first = scene.terrain is None
        terrain.texture_image = build_mosaic(terrain, layer.images)
        # An async rebuild keeps the visibility a scene may have set.
        terrain.visible = True if first else bool(
            getattr(scene.terrain, "visible", True))
        scene.terrain = terrain
        self.viewport.upload_terrain(terrain)
        # Frame the terrain only the first time it appears (not on async rebuilds).
        if first:
            mn, mx = terrain.bounds()
            if mn is not None:
                self.viewport.camera.set_view("iso")
                self.viewport.camera.fit_to(mn, mx)
        self.viewport.update()

    def _on_select_all(self) -> None:
        """Select every entity (Ctrl+A) — edges (soft included), faces, groups
        and dimensions. The safe way to rotate/move/scale a WHOLE model: a
        window box-select that misses one protruding piece leaves it behind
        and the transform warps the boundary (the sigue.igz report)."""
        sel = self.viewport.scene.selection
        sel.clear()
        sel.update(self.viewport.scene.edges)
        sel.update(self.viewport.scene.faces)
        ctx = self.viewport.scene.edit_group
        # Inside a group, "everything" is what the group holds: its loose
        # geometry (above) and its children — never the model around it.
        sel.update(self.viewport.scene.groups if ctx is None
                   else (getattr(ctx, "children", None) or []))
        sel.update(getattr(self.viewport.scene, "dimensions", []))
        # Bump the version and say so: the GL colour caches are keyed on it
        # and Entity Info listens for it, so a selection made behind
        # Scene.select()'s back left the status bar counting entities the
        # viewport drew unselected and the tray called "nothing selected"
        # (issue #38). Everything else goes through Scene.select(); this
        # one builds the set by hand because "all" is four sources.
        self.viewport.scene.version += 1
        self.viewport.notify_scene_changed()
        self.statusBar().showMessage(
            tr("Selected everything ({n} entities)", n=len(sel)), 2500)

    def _on_invert_selection(self) -> None:
        """Select what is not selected, drop what is (Ctrl+Shift+I) — see
        ``Scene.invert_selection`` for what counts."""
        n = self.viewport.scene.invert_selection()
        self.viewport.notify_scene_changed()
        self.statusBar().showMessage(
            tr("Selection inverted ({n} entities)", n=n), 2500)

    # ---- Undo / redo --------------------------------------------------------
    def _on_undo(self) -> None:
        if self.viewport.history.undo():
            self.viewport.notify_scene_changed()

    def _on_redo(self) -> None:
        if self.viewport.history.redo():
            self.viewport.notify_scene_changed()

    # ---- File handling ------------------------------------------------------
    # ---- The document's camera (issue #60) ---------------------------------
    _CAMERA_FIELDS = ("distance", "yaw", "pitch", "fov_deg", "perspective",
                      "two_point")

    def _camera_dict(self) -> dict:
        """The live camera as the document keeps it (SketchUp saves the
        camera in the file; @pacaeiro, issue #60)."""
        cam = self.viewport.camera
        t = cam.target
        out = {"target": [float(t.x()), float(t.y()), float(t.z())]}
        for k in self._CAMERA_FIELDS:
            out[k] = getattr(cam, k)
        return out

    def _apply_camera_home(self) -> None:
        """Look at what the document's author was looking at; a document
        from before the camera was saved keeps the view as it is."""
        home = getattr(self.viewport.scene, "camera_home", None)
        if not isinstance(home, dict):
            return
        cam = self.viewport.camera
        t = home.get("target")
        if isinstance(t, (list, tuple)) and len(t) == 3:
            from PySide6.QtGui import QVector3D
            cam.target = QVector3D(*[float(v) for v in t])
        for k in self._CAMERA_FIELDS:
            if k in home:
                try:
                    setattr(cam, k, type(getattr(cam, k))(home[k]))
                except (TypeError, ValueError):
                    pass
        self.viewport.update()

    def _reset_camera_home(self) -> None:
        """A new drawing opens on the default view (iso, 20 m out), not on
        wherever the previous one was left (issue #60)."""
        from core.camera import OrbitCamera
        fresh = OrbitCamera()
        cam = self.viewport.camera
        cam.target = fresh.target
        for k in self._CAMERA_FIELDS:
            setattr(cam, k, getattr(fresh, k))
        self.viewport.update()

    @staticmethod
    def _new_window_command() -> list[str]:
        """How to start another IngeTrazo from this one. Each package needs
        its own way: the AppImage's mount and the Flatpak sandbox both go
        away with the process that owns them, so the new window must get
        its own rather than run from ours."""
        import os
        import sys
        from core.paths import app_root, is_frozen
        flag = "--new-window"        # skip the single-instance handover
        if os.environ.get("APPIMAGE"):
            return [os.environ["APPIMAGE"], flag]
        if os.environ.get("FLATPAK_ID"):
            return ["flatpak-spawn", "ingetrazo", flag]
        if is_frozen():
            return [sys.executable, flag]
        return [sys.executable, str(app_root() / "main.py"), flag]

    def _on_new_window(self) -> None:
        from PySide6.QtCore import QProcess
        cmd = self._new_window_command()
        if not QProcess.startDetached(cmd[0], cmd[1:]):
            QMessageBox.warning(self, tr("New Window"),
                                tr("Could not start another IngeTrazo window."))

    def _on_new(self) -> None:
        self.viewport.end_group_edit()
        if not self._confirm_discard(tr("Discard current drawing?")):
            return
        # The discarded drawing's recovery slot dies with it.
        from core import autosave
        autosave.clear(self._current_path)
        self._autosaved_version = None
        scene = self.viewport.scene
        scene.clear()
        scene.version += 1
        self.viewport.history.clear()
        self._reset_camera_home()
        # Document boundary: the old drawing's textures go back to the driver.
        self.viewport.reset_texture_cache()
        self._current_path = None
        self._import_name = None
        self._apply_new_document_units()
        self._insert_scale_figure()
        self.viewport.notify_scene_changed()
        self._sync_style_menu()
        self._sync_section_menu()
        self._update_title()
        self.settle_heap()

    def _apply_new_document_units(self) -> None:
        """A new, empty document starts in the units chosen for new documents
        in Preferences (#121). Not a change to the document: no version bump,
        so it does not ask to be saved."""
        from core import units as _units
        _units.apply_units(self.viewport.scene, _units.new_document_units())

    def _on_recover_discarded(self) -> None:
        """Open one of the retired auto-save copies as a NEW, unsaved
        document: Save then asks where to put it, never over the file the
        copy came from."""
        from core import autosave
        folder = autosave.discarded_dir()
        if not any(folder.glob("*.igz")):
            QMessageBox.information(
                self, tr("Recover a discarded auto-save…"),
                tr("No discarded auto-saved copies yet."))
            return
        chosen, _ = file_dialogs.getOpenFileName(
            self, tr("Recover a discarded auto-save…"), str(folder),
            tr("IngeTrazo auto-saves (*.igz)"))
        if not chosen:
            return
        if not self._confirm_discard(tr("Open another drawing?")):
            return
        if not self.open_path(Path(chosen)):
            return
        self._current_path = None                 # a recovered, unsaved copy
        self._saved_version = -1
        self._update_title()
        self.statusBar().showMessage(tr(
            "Recovered copy loaded — use Save As to keep it."), 6000)

    # ---- Recent files -------------------------------------------------------
    _RECENT_MAX = 10

    @staticmethod
    def _recent_paths() -> list:
        raw = QSettings().value("recent_files", []) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(x) for x in raw if str(x).strip()]

    def _remember_recent(self, path) -> None:
        """Put ``path`` at the top of File ▸ Open Recent (native documents
        only: an import is not a document you reopen)."""
        if path is None or Path(path).suffix.lower() != ".igz":
            return
        key = str(Path(path).resolve())
        recent = [x for x in self._recent_paths() if x != key]
        recent.insert(0, key)
        QSettings().setValue("recent_files", recent[: self._RECENT_MAX])

    def _fill_recent_menu(self) -> None:
        menu = self._recent_menu
        menu.clear()
        alive = [x for x in self._recent_paths() if Path(x).exists()]
        if not alive:
            none = menu.addAction(tr("(no recent documents)"))
            none.setEnabled(False)
            return
        for i, entry in enumerate(alive, 1):
            p = Path(entry)
            act = menu.addAction(f"&{i}  {p.name}  —  {p.parent}")
            act.setToolTip(str(p))
            act.triggered.connect(lambda _c=False, q=p: self._open_recent(q))
        menu.addSeparator()
        clear = menu.addAction(tr("Clear list"))
        clear.triggered.connect(
            lambda: QSettings().setValue("recent_files", []))

    def _open_recent(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, tr("Open Recent"),
                                tr("{name} is no longer there.", name=path.name))
            return
        self.viewport.end_group_edit()
        if not self._confirm_discard(
                tr("Discard current drawing and open another?")):
            return
        self.open_path(path)

    def _on_open(self) -> None:
        self.viewport.end_group_edit()
        if not self._confirm_discard(
                tr("Discard current drawing and open another?")):
            return
        path_str, _ = file_dialogs.getOpenFileName(
            self,
            tr("Open IngeTrazo document"),
            "",
            tr(IGZ_FILE_FILTER),
        )
        if not path_str:
            return
        self.open_path(Path(path_str))

    def open_path(self, path: Path) -> bool:
        """Open a document at ``path`` (File dialog, CLI argument, or the OS
        file association's double-click all land here).

        ``.igz`` is our native format; ``.dae``/``.skp`` are the interchange
        formats we also register in the desktop entry, so double-clicking one
        imports it rather than failing to parse it as an IngeTrazo document."""
        suffix = path.suffix.lower()
        if suffix == ".dae":
            self._import_dae_path(path)
            return True
        if suffix == ".skp":
            return self.import_skp_path(path)
        if suffix == ".dxf":
            return self._import_dxf_path(path)
        if suffix == ".dwg":
            return self._import_dwg_path(path)
        # An existing recovery slot for this document means a session that
        # never got to save it (the invariant in core/autosave.py) — offer
        # the auto-saved copy before loading the file itself.
        from core import autosave
        recovered = False
        slot = autosave.pending(path)
        if slot is not None:
            answer = QMessageBox.question(
                self, tr("Recovered drawing"),
                tr("A session with '{name}' ended without saving (auto-saved "
                   "copy found). Recover it instead of the file on disk?",
                   name=path.name),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            recovered = answer == QMessageBox.Yes
            if not recovered:
                autosave.clear(path)
        # A bar while it loads (issue #59, @pacaeiro): a big document took
        # seconds with nothing on screen, «feeling of freeze». Small ones
        # never show it (the dialog waits 400 ms before appearing).
        dlg, cb = self._import_progress(tr("Opening {name}…", name=path.name))
        try:
            igz_format.load_into(self.viewport.scene,
                                 slot if recovered else path, progress=cb)
        except Exception as exc:  # noqa: BLE001 - surface any IO/parse error to the user
            dlg.close()
            QMessageBox.critical(self, tr("Open failed"), str(exc))
            return False
        dlg.close()
        self.viewport.history.clear()
        self.viewport.reset_texture_cache()
        self._apply_camera_home()
        self._current_path = path
        self._remember_recent(path)
        self._import_name = None
        self._autosaved_version = None
        # A recovered drawing is NOT the file on disk yet: keep it dirty so
        # the title shows * and Ctrl+S makes it real (the slot stays until
        # that clean save).
        self._saved_version = (-1 if recovered
                               else self.viewport.scene.version)
        self._sync_style_menu()      # the document may carry its own style
        self._sync_section_menu()
        # A stored survey (Track G, G6) arrives as plain arrays + images; the
        # GL upload only happens here, where there's a context.
        survey = getattr(self.viewport.scene, "photo_mesh", None)
        if survey is not None:
            self.viewport.upload_photo_mesh(survey, getattr(survey, "images", None))
            # Frame it. The default camera sits ~20 m out (sized for the scale
            # figure) and a survey is hundreds of metres across, so without this
            # the whole thing falls outside the far plane and the document opens
            # looking empty — with the mesh loaded and invisible.
            mn, mx = survey.bounds()
            if mn is not None:
                self.viewport.camera.set_view("iso")
                self.viewport.camera.fit_to(mn, mx)
        else:
            self.viewport.release_photo_textures()
        # Mirror the document's base map and survey into the tray, and refetch
        # the tiles for the capture the document carries — otherwise the panel
        # shows stale defaults over a scene that has its own.
        self.georef_tray.base_map.sync_from_document()
        self.georef_tray.base_map.sync_photo_mesh()
        self.viewport.notify_scene_changed()
        self._update_title()
        self.settle_heap()
        return True

    #: Young-generation threshold: how many net allocations between
    #: collector passes. Python's default (2000) made the incremental
    #: collector (3.14) walk slices of the plaza's 1.3 M objects on almost
    #: every hover — 203 passes and an 80 ms pause per 120 mouse moves;
    #: at 50 000 the same run did 6 passes of ~0 ms. Measured 2026-09-14
    #: against ``gc.freeze`` too, which cut the pauses but made every
    #: allocation-heavy path slower (the cold pick index 23 → 41 ms).
    GC_THRESHOLD0 = 50_000

    def settle_heap(self) -> None:
        """After a document loads: one clean collection over its static
        object graph, and the young-generation threshold that keeps the
        collector out of the way while drawing (see ``GC_THRESHOLD0``)."""
        import gc
        gc.unfreeze()                 # (in case an older session froze it)
        gc.set_threshold(self.GC_THRESHOLD0, 10, 0)
        gc.collect()

    def _on_save(self) -> None:
        self.viewport.end_group_edit()
        if self._current_path is None:
            self._on_save_as()
            return
        self._do_save(self._current_path)

    def _on_save_as(self) -> None:
        self.viewport.end_group_edit()
        default_name = (
            self._current_path.name if self._current_path is not None else "untitled.igz"
        )
        path_str, _ = file_dialogs.getSaveFileName(
            self,
            tr("Save IngeTrazo document"),
            default_name,
            tr(IGZ_FILE_FILTER),
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".igz":
            path = path.with_suffix(".igz")
        self._do_save(path)

    def _do_save(self, path: Path) -> None:
        # Backup BEFORE writing (Preferences ▸ General): the previous good
        # version survives even a save that dies mid-write — which a syncing
        # drive has actually produced (pCloud truncation).
        if str(QSettings().value("general/backup", "1")) != "0" \
                and path.is_file():
            import shutil
            try:
                shutil.copy2(path, path.with_name(path.name + ".bak"))
            except OSError:
                self.statusBar().showMessage(
                    tr("Could not write the backup copy."), 4000)
        try:
            self.viewport.scene.camera_home = self._camera_dict()
            stats = igz_format.save_scene(self.viewport.scene, path) or {}
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Save failed"), str(exc))
            return
        # A clean save ends the recovery window for this document — and for
        # the untitled slot when this save gave the document its first name.
        from core import autosave
        autosave.clear(path)
        if self._current_path is None:
            autosave.clear(None)
        # Textures travel inside the document — say so, and say it loudly when
        # an image could not be read (that face's texture will NOT travel).
        embedded = int(stats.get("embedded", 0))
        missing = int(stats.get("missing", 0))
        if missing:
            QMessageBox.warning(
                self, tr("Saved with missing textures"),
                tr("{n} texture image(s) could not be read, so they were not "
                   "packed into the document — those faces will lose their "
                   "texture on another computer.", n=missing))
        elif embedded:
            self.statusBar().showMessage(
                tr("Saved — {n} texture(s) packed into the document.",
                   n=embedded), 4000)
        self._current_path = path
        self._remember_recent(path)
        self._saved_version = self.viewport.scene.version
        self._update_title()

    def _insert_scale_figure(self) -> None:
        """Place the scale figure in a fresh document, SketchUp-style: OFF
        to the left of the origin, so the origin stays visible as the
        drawing reference (user request — SketchUp does the same). 1.75 m
        tall. A plain group — select and Delete removes it. Added outside
        the undo history and without dirtying the document."""
        # SketchUp's placement, measured by the user: 60-70 cm to the left
        # and 60 cm forward (toward the viewer) of the origin.
        from PySide6.QtGui import QVector3D
        at = QVector3D(-0.65, -0.60, 0.0)
        # The engineer since 26-09 (Marco: «el personaje Sumari no me gusta
        # mucho, ¿ponemos el del ingeniero?»); Sumari stays in the library.
        group = self._make_billboard_person("ingeniero.png", height=1.75,
                                            name=tr("Engineer"), position=at)
        if group is None:
            group = self._make_billboard_person(position=at)
        if group is None:
            return
        scene = self.viewport.scene
        scene.groups.append(group)
        scene.version += 1
        self._saved_version = scene.version

    def _make_billboard_person(self, image: str = "person_billboard.png",
                               height: float = 1.75,
                               name: str | None = None, position=None):
        """A face-me scale figure (arch-viz cutout)."""
        from PySide6.QtGui import QImage
        from core.group import make_billboard_group
        from core.paths import app_root
        path = app_root() / "resources" / "components" / image
        if not path.exists():
            return None
        img = QImage(str(path))
        if img.isNull() or img.height() == 0:
            return None
        return make_billboard_group(str(path), height, name or tr("Person"),
                                    img.width() / img.height(),
                                    position=position)

    def _on_insert_person_2d(self, image: str = "person_billboard.png",
                             height: float = 1.75,
                             name: str | None = None) -> None:
        self.viewport.end_group_edit()
        group = self._make_billboard_person(image, height, name)
        if group is None:
            QMessageBox.warning(self, tr("Insert component"),
                                tr("Component file missing: {p}", p=image))
            return
        self._start_place(group)

    def _on_insert_faceme_image(self) -> None:
        """Insert the user's own transparent PNG as a face-me billboard —
        a cutout person, a tree photo — scaled to a chosen real height."""
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QInputDialog
        from core.group import make_billboard_group
        self.viewport.end_group_edit()
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Face-me image"), "",
            tr("Images (*.png *.webp);;All files (*)"))
        if not path_str:
            return
        img = QImage(path_str)
        if img.isNull() or img.height() == 0:
            QMessageBox.warning(self, tr("Face-me image"),
                                tr("Could not read the image."))
            return
        if not img.hasAlphaChannel():
            QMessageBox.information(
                self, tr("Face-me image"),
                tr("The image has no transparency — it will show as a "
                   "solid rectangle. A PNG with transparent background "
                   "works best."))
        height, ok = QInputDialog.getDouble(
            self, tr("Face-me image"), tr("Real height (m):"),
            1.75, 0.05, 500.0, 2)
        if not ok:
            return
        group = make_billboard_group(
            path_str, height, Path(path_str).stem,
            img.width() / img.height())
        self._start_place(group)

    def _on_insert_component(self, key: str, name: str | None = None) -> None:
        """Insert a bundled starter component as a Group at the origin,
        selected and ready to Move into place. Components are ``.igz``
        (models kept for offline use, textures packed in), ``.glb`` (the
        Sketchfab CC-BY set) or ``.obj``."""
        from core.group import Group
        from core.scene import Scene as _Scene
        self.viewport.end_group_edit()
        from core.paths import app_root
        base = app_root() / "resources" / "components"
        temp = _Scene()
        igz_path = base / f"{key}.igz"
        glb_path = base / f"{key}.glb"
        obj_path = base / f"{key}.obj"
        if igz_path.exists():
            # Our own format: one group, its images inside the file — so a
            # bundled component needs no network and no sidecar textures.
            from formats import igz as _igz
            _igz.load_into(temp, igz_path)
            if not temp.groups:
                QMessageBox.warning(
                    self, tr("Insert component"),
                    tr("Component file missing: {p}", p=str(igz_path)))
                return
            mesh = temp.groups[0].mesh
        elif glb_path.exists():
            from formats.glb import load_glb
            load_glb(temp, glb_path)
            mesh = temp.groups[0].mesh
            name = name or temp.groups[0].name
        elif obj_path.exists():
            from formats import obj as _obj
            _obj.load_obj(temp, obj_path)
            parts = _obj_parts(temp)
            if parts is not None:
                parts.name = name or tr(key.capitalize())
                self._start_place(parts)
                return
            mesh = temp.mesh
            if not mesh.faces and temp.groups:
                # Big OBJs land as a reference group (formats/obj.py), not
                # in the loose mesh — take that mesh or we'd insert nothing.
                mesh = temp.groups[0].mesh
            # Low-poly components read as REAL models when facet seams are
            # soft (SketchUp import smoothing).
            from formats.fuse import soften_smooth_edges
            soften_smooth_edges(mesh, cos_threshold=0.55)
        else:
            QMessageBox.warning(
                self, tr("Insert component"),
                tr("Component file missing: {p}", p=str(glb_path)))
            return
        group = Group(mesh, name=name or tr(key.capitalize()))
        self._start_place(group)

    def insert_library_component(self, entry: dict) -> None:
        """Download a model from the online library and hand it to the
        placement tool, at its real size.

        Nothing is guessed — not the unit, not the vertical, not even the
        model's own turn: the catalogue declares all three, and
        :func:`core.library.model_matrix` reproduces them. That is the
        difference with the generic importer, which has only the file and
        so has to ask (see ``_obj_unit``). The facet seams are softened
        like the bundled starters, so a low-poly piece reads as a real one.
        """
        from core import library
        from core.group import Group
        from core.scene import Scene as _Scene
        from formats import obj as _obj
        from formats.fuse import soften_smooth_edges

        obj = library.model_file(entry)
        if obj is None:
            QMessageBox.warning(
                self, tr("Component library"),
                tr("Could not download “{name}”. Check your connection.",
                   name=entry.get("nombre", "")))
            return
        self.viewport.end_group_edit()
        temp = _Scene()
        try:
            _obj.load_obj(temp, obj,
                           matrix=library.model_matrix(entry, obj))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Component library"), str(exc))
            return
        parts = _obj_parts(temp)
        if parts is not None:
            # A model written as parts keeps them: one component to place,
            # its pieces inside (see formats.obj._pieces_group).
            parts.name = entry.get("nombre", "") or parts.name
            self._start_place(parts)
            return
        mesh = temp.mesh
        if not mesh.faces and temp.groups:
            mesh = temp.groups[0].mesh       # a big OBJ lands as a group
        if not mesh.faces:
            QMessageBox.warning(
                self, tr("Component library"),
                tr("“{name}” has no geometry.", name=entry.get("nombre", "")))
            return
        soften_smooth_edges(mesh, cos_threshold=0.55)
        self._start_place(Group(mesh, name=entry.get("nombre", "")))

    def _on_open_library(self) -> None:
        from views.library_dialog import LibraryDialog
        LibraryDialog(self).exec()

    def _text3d_dialog(self, params=None):
        """SketchUp's 3D Text dialog (text, font, bold, italic, height,
        thickness) → the parameters dict, or ``None`` when cancelled or
        blank. ``params`` pre-fills it (editing an existing text).

        Height and thickness read in METRES, the model's unit everywhere
        else (Marco, 2026-09-20: «debería ser la unidad en metros»), with
        no low ceiling: Rafael typed «20» for the extrusion and a 10 m cap
        refused it (2026-09-16, f000845) — the cap was the fault, not the
        unit. Three decimals, so 0.05 m reads as such."""
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QDoubleSpinBox, QFontComboBox,
                                       QFormLayout, QLineEdit)
        from PySide6.QtGui import QFont
        from core.text3d import text_params
        params = params or {}
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("3D Text"))
        form = QFormLayout(dlg)
        text_edit = QLineEdit(params.get("text") or tr("IngeTrazo"))
        text_edit.selectAll()
        form.addRow(tr("Text:"), text_edit)
        font_box = QFontComboBox()
        if params.get("font"):
            font_box.setCurrentFont(QFont(params["font"]))
        form.addRow(tr("Font:"), font_box)
        bold_check = QCheckBox()
        bold_check.setChecked(bool(params.get("bold", True)))
        form.addRow(tr("Bold:"), bold_check)
        italic_check = QCheckBox()
        italic_check.setChecked(bool(params.get("italic", False)))
        form.addRow(tr("Italic:"), italic_check)
        height_spin = QDoubleSpinBox()
        height_spin.setRange(0.001, 1000.0)
        height_spin.setDecimals(3)
        height_spin.setSingleStep(0.05)
        height_spin.setValue(float(params.get("height", 0.25)))
        height_spin.setSuffix(" m")
        form.addRow(tr("Height:"), height_spin)
        depth_spin = QDoubleSpinBox()
        depth_spin.setRange(0.0, 1000.0)
        depth_spin.setDecimals(3)
        depth_spin.setSingleStep(0.01)
        depth_spin.setValue(float(params.get("thickness", 0.05)))
        depth_spin.setSuffix(" m")
        depth_spin.setToolTip(tr("0 leaves flat faces (no extrusion)"))
        form.addRow(tr("Extruded:"), depth_spin)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.Accepted:
            return None
        text = text_edit.text().strip()
        if not text:
            return None
        return text_params(
            text, font_box.currentFont().family(), bold_check.isChecked(),
            italic_check.isChecked(), height_spin.value(),
            depth_spin.value())

    def _on_insert_3d_text(self) -> None:
        """SketchUp's 3D Text: the dialog generates REAL extruded geometry —
        a container group with ONE GROUP PER LETTER, editable later from
        the right-click menu — handed to the placement tool so it settles
        on the ground (or onto a wall) like any component."""
        from core.text3d import make_text_group
        params = self._text3d_dialog()
        if params is None:
            return
        self.viewport.end_group_edit()
        group = make_text_group(params)
        if group is None:
            QMessageBox.warning(self, tr("3D Text"),
                                tr("Could not build geometry for that text."))
            return
        self._start_place(group, align_to_face=True)

    def _selected_text3d(self):
        """The one selected 3D-text container (a letter picked inside the
        open container counts, through its owner), else ``None``."""
        from core.group import Group
        sel = [e for e in self.viewport.scene.selection if isinstance(e, Group)]
        if len(sel) != 1:
            return None
        g = sel[0]
        if getattr(g, "text3d", None):
            return g
        ctx = self.viewport.scene.edit_group
        if ctx is not None and getattr(ctx, "text3d", None):
            kids = ctx.children or ()
            if g in kids or getattr(g, "owner", None) in kids:
                return ctx
        return None

    def _on_edit_3d_text(self, group=None) -> None:
        """Reopen the 3D Text dialog on an existing text and lay the letters
        out again in place — the right-click's «Edit 3D Text…» (Rafael,
        2026-09-16: «SketchUp tampoco»; double-click keeps SketchUp's
        meaning and enters the group). Letters pushed or painted by hand
        are regenerated."""
        from core.history import EditText3DCommand
        from core.text3d import make_text_group, text_is_pristine
        group = group if group is not None else self._selected_text3d()
        if group is None or not getattr(group, "text3d", None):
            return
        if not text_is_pristine(group):
            self.viewport.flash_status(tr(
                "This text's letters were edited by hand, so it can no "
                "longer be regenerated as text."), 5000)
            return
        from core.text3d import TEXT_KEYS
        params = self._text3d_dialog(group.text3d)
        if params is None or params == {k: group.text3d.get(k) for k in TEXT_KEYS}:
            return
        if make_text_group(params) is None:
            QMessageBox.warning(self, tr("3D Text"),
                                tr("Could not build geometry for that text."))
            return
        if self.viewport.scene.edit_group is group:
            self.viewport.end_group_edit()
        self.viewport.history.execute(EditText3DCommand(group, params))
        self.viewport.scene.select([group])
        self.viewport.update()

    def _start_place(self, group, align_to_face: bool = False,
                     anchor=None) -> None:
        """Hand a freshly built component to the placement tool: it follows
        the cursor (settling on the ground plane by default) and a click
        drops it — instead of dumping it at the origin. ``align_to_face``
        (3D text) re-orients the group onto the face under the cursor;
        ``anchor`` is the point the cursor holds (default: base centre)."""
        from tools.place_group import PlaceGroupTool
        self.viewport.set_active_tool(PlaceGroupTool(
            group, align_to_face=align_to_face, anchor=anchor))
        for action in self._tool_actions.values():
            action.setChecked(False)
        self._tool_label.setText(
            tr("Tool: {name}", name=tr("Place component")))
        self._refresh_vcb()
        self.viewport.flash_status(
            tr("Click to place the component (Esc cancels)"), 4000)
        self.viewport.update()

    def _on_get_models(self) -> None:
        QMessageBox.information(
            self, tr("Get more models and textures"),
            tr("Free sources that open directly in IngeTrazo:") + "<br><br>"
            "<b>3D Warehouse</b> — "
            "<a href='https://3dwarehouse.sketchup.com'>"
            "3dwarehouse.sketchup.com</a><br>"
            + tr("Download as COLLADA (.dae) — or the .skp itself — and use "
                 "File → Import.")
            + "<br><br>"
            "<b>Poly Haven</b> — <a href='https://polyhaven.com'>"
            "polyhaven.com</a> " + tr("(CC0: models OBJ and PBR textures)")
            + "<br><b>ambientCG</b> — <a href='https://ambientcg.com'>"
            "ambientcg.com</a> " + tr("(CC0 textures — drop the PNG into "
                                      "resources/textures)")
            + "<br><b>Sketchfab</b> — <a href='https://sketchfab.com'>"
            "sketchfab.com</a> " + tr("(filter by CC licence, download OBJ)"))


    def _import_progress(self, title):
        """A modal progress dialog + the callback the loaders call at
        milestones (big imports take ~20 s; SketchUp shows a bar here too)."""
        from PySide6.QtWidgets import QApplication, QProgressDialog
        # Closed is not deleted: each open or import left its dialog behind
        # as a child of the window for the whole session (the release check,
        # 25-09). The previous one is surely done by the time a new one is
        # asked for, so it goes now — never more than one alive.
        old = getattr(self, "_progress_dlg", None)
        if old is not None:
            try:
                old.deleteLater()
            except RuntimeError:
                pass
        dlg = QProgressDialog(title, "", 0, 100, self)
        self._progress_dlg = dlg
        dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.setAutoClose(False)

        def cb(frac, text):
            dlg.setValue(int(frac * 100))
            dlg.setLabelText(tr(text))
            QApplication.processEvents()

        return dlg, cb

    def _parse_skp_threaded(self, skp, cb):
        """Parse ``skp`` off the UI thread, keeping the event loop responsive.

        Returns ``(payload, exc)`` — ``payload`` is the parsed geometry (or
        ``None``), ``exc`` is a ``NeedsConverter`` (fall back to skp2dae), any
        other exception (real failure), or ``None``. The parse touches no
        ``Scene`` so it is safe off-thread; ``apply_payload`` runs on the UI
        thread in the caller. A local ``QEventLoop`` blocks here until the
        worker finishes, so the method stays synchronous while the window and
        its progress dialog keep painting."""
        from PySide6.QtCore import QThread, QObject, QEventLoop, Signal, Qt

        from formats import skp as skp_format

        class _Worker(QObject):
            progressed = Signal(float, str)
            finished = Signal(object, object)   # (payload, exc)

            def run(self):
                try:
                    payload = skp_format.parse_skp(
                        skp, progress=lambda f, t: self.progressed.emit(f, t))
                    self.finished.emit(payload, None)
                except Exception as exc:  # noqa: BLE001 — reported to caller
                    self.finished.emit(None, exc)

        thread = QThread(self)
        worker = _Worker()
        worker.moveToThread(thread)
        result = {}
        loop = QEventLoop()

        # The receivers MUST be bound methods of a QObject living in the UI
        # thread: a queued connection to a bare lambda/function has no
        # receiver object, so Qt runs it in the EMITTER (worker) thread —
        # the progress callback then touches the dialog and pumps events
        # off-thread, which deadlocks before the window ever paints (the
        # ".skp double-click never opens the app" freeze).
        class _Relay(QObject):
            def on_progress(self, f, t):
                cb(f, t)

            def on_finished(self, payload, exc):
                result["payload"] = payload
                result["exc"] = exc
                loop.quit()

        relay = _Relay(self)
        worker.progressed.connect(relay.on_progress, Qt.QueuedConnection)
        worker.finished.connect(relay.on_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()
        loop.exec()
        thread.quit()
        thread.wait()
        worker.deleteLater()
        relay.deleteLater()
        return result.get("payload"), result.get("exc")

    def _prepare_import_display(self, cmd, cb) -> None:
        """Pre-build the render/pick caches of freshly imported groups while
        the progress dialog is still up — otherwise the first orbit after a
        big import freezes ~5 s building them."""
        for g in getattr(cmd, "added_groups", []):
            cb(0.97, "Preparing display…")
            try:
                self.viewport._group_chunk(g)
            except Exception:  # noqa: BLE001 — display cache only; never fatal
                pass
        cb(1.0, "Done")

    def _on_import_dae(self) -> None:
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import DAE"), "",
            tr("COLLADA (*.dae);;All files (*)"))
        if not path_str:
            return
        self._import_dae_path(Path(path_str))

    def _on_import_glb(self) -> None:
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import glTF/GLB"), "",
            tr("glTF binary (*.glb *.gltf);;All files (*)"))
        if not path_str:
            return
        self._import_glb_path(Path(path_str))

    def _import_glb_path(self, path: Path) -> None:
        from formats import glb as glb_format
        dlg, cb = self._import_progress(tr("Importing {name}…", name=path.name))
        cmd = SnapshotImport(
            lambda scene: glb_format.load_glb(scene, path, progress=cb))
        try:
            self.viewport.history.execute(cmd)
        except Exception as exc:  # noqa: BLE001
            dlg.close()
            QMessageBox.critical(self, tr("Import glTF/GLB failed"), str(exc))
            return
        self._prepare_import_display(cmd, cb)
        dlg.close()
        self.viewport.update()
        self._import_name = path.name
        self._update_title()
        self.statusBar().showMessage(tr("Imported {name}", name=path.name), 3000)

    def _import_dae_path(self, path: Path) -> None:
        dlg, cb = self._import_progress(tr("Importing {name}…", name=path.name))
        cmd = SnapshotImport(
            lambda scene: dae_format.load_dae(scene, path, progress=cb))
        try:
            self.viewport.history.execute(cmd)
        except Exception as exc:  # noqa: BLE001
            dlg.close()
            QMessageBox.critical(self, tr("Import DAE failed"), str(exc))
            return
        self._prepare_import_display(cmd, cb)
        dlg.close()
        self.viewport.update()
        self._import_name = path.name
        self._update_title()
        self.statusBar().showMessage(tr("Imported {name}", name=path.name), 3000)

    # ---- SKP via the skp2dae satellite converter -----------------------------
    @staticmethod
    def _find_skp_converter():
        """Locate the external skp2dae converter and return the command list
        to invoke it, or ``None``. Search order: ``SKP2DAE_EXE`` env var,
        ``~/.local/share/skp2dae/skp2dae.exe``, then ``skp2dae`` on PATH.
        The converter is a SEPARATE program (it loads Trimble's proprietary
        SketchUpAPI.dll, which can never ship inside GPL IngeTrazo); on
        Linux a ``.exe`` runs through Wine."""
        import os
        import shutil
        import sys as _sys
        candidates = []
        env = os.environ.get("SKP2DAE_EXE")
        if env:
            candidates.append(Path(env))
        candidates.append(
            Path.home() / ".local" / "share" / "skp2dae" / "skp2dae.exe")
        which = shutil.which("skp2dae")
        if which:
            candidates.append(Path(which))
        for cand in candidates:
            if not cand.exists():
                continue
            if cand.suffix.lower() == ".exe" and _sys.platform != "win32":
                wine = shutil.which("wine")
                if wine:
                    return [wine, str(cand)]
                continue
            return [str(cand)]
        return None

    def import_skp_path(self, skp: Path) -> bool:
        """Import ``skp``. Prefers a pure-Python parser backend (offline, no
        Wine/DLL — see ``formats/skp.py``); falls back to the external skp2dae
        converter for versions no pure backend can read yet (its .dae and
        texture folder land NEXT TO the .skp, so texture paths stay valid for
        the session and for saved documents)."""
        from formats import skp as skp_format
        if skp_format.can_handle(skp):
            # Heavy parse OUTSIDE the undo history: decide pure-vs-converter
            # before touching the scene, so a failed/empty parse never leaves a
            # half-applied edit. NeedsConverter → fall through to skp2dae.
            dlg, cb = self._import_progress(
                tr("Importing {name}…", name=skp.name))
            # The parse is heavy (seconds on a big model) and pure-Python, so
            # running it on the UI thread starves the event loop and the OS
            # paints a "not responding" ghost window. It touches no Scene, so
            # run it in a worker thread while a LOCAL event loop keeps the UI
            # (and the progress bar) alive; only apply_payload stays on the UI
            # thread below.
            payload, exc = self._parse_skp_threaded(skp, cb)
            if isinstance(exc, skp_format.NeedsConverter):
                payload = None
                self.statusBar().showMessage(tr(
                    "Pure importer unavailable for this file — using the "
                    "external converter (slower)."), 8000)
            elif exc is not None:
                dlg.close()
                QMessageBox.critical(self, tr("Import SKP failed"), str(exc))
                return False
            if payload is not None:
                cmd = SnapshotImport(
                    lambda scene: skp_format.apply_payload(scene, payload))
                try:
                    self.viewport.history.execute(cmd)
                except Exception as exc:  # noqa: BLE001
                    dlg.close()
                    QMessageBox.critical(self, tr("Import SKP failed"), str(exc))
                    return False
                self._prepare_import_display(cmd, cb)
                dlg.close()
                self.viewport.update()
                self._import_name = skp.name
                self._update_title()
                if payload.get("empty"):
                    # A template or blank file (#103): say so, or an empty
                    # viewport reads as a failed import.
                    self.statusBar().showMessage(tr(
                        "{name} has no geometry — nothing to import.",
                        name=skp.name), 8000)
                else:
                    self.statusBar().showMessage(
                        tr("Imported {name}", name=skp.name), 3000)
                return True
            dlg.close()   # no pure backend could read it → converter below

        # ---- Fallback: the external skp2dae converter (Trimble DLL via Wine) --
        command = self._find_skp_converter()
        if command is None:
            answer = QMessageBox.question(
                self, tr("Import SKP"),
                tr("Opening .skp needs the skp2dae converter (a separate "
                   "program IngeTrazo launches).\n\n"
                   "Install it automatically? This downloads:\n"
                   "• skp2dae.exe from the IngeTrazo releases (free "
                   "software, MIT), and\n"
                   "• the official SketchUp library (SketchUpAPI.dll) from "
                   "the public release of Blender's 'SketchUp Importer' "
                   "add-on (a third-party project).\n\n"
                   "Everything lands in ~/.local/share/skp2dae/."),
                QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes:
                return False
            if not self._install_skp_converter():
                return False
            command = self._find_skp_converter()
            if command is None:
                return False
        import shutil
        import subprocess
        import tempfile
        import unicodedata
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QApplication

        # Wine re-encodes argv to the Windows ANSI codepage, so an accented
        # path ("Imágenes", "ñandú.skp") reaches the converter — and the
        # SDK's UTF-8 file API — mangled. Sidestep it: convert through a
        # temporary ASCII path and move the results next to the original.
        # The texture folder keeps the .dae's stem (its internal refs are
        # relative to that name), so accented stems come back sanitized.
        ascii_stem = unicodedata.normalize("NFKD", skp.stem)
        ascii_stem = ascii_stem.encode("ascii", "ignore").decode() or "modelo"
        needs_tmp = any(ord(c) > 127 for c in str(skp))
        tmpdir: Path | None = None
        if needs_tmp:
            tmpdir = Path(tempfile.mkdtemp(prefix="skp2dae-"))
            work_skp = tmpdir / (ascii_stem + ".skp")
            shutil.copy(skp, work_skp)
        else:
            work_skp = skp
        work_dae = work_skp.with_suffix(".dae")

        self.statusBar().showMessage(
            tr("Converting {name}… (skp2dae)", name=skp.name))
        QApplication.setOverrideCursor(_Qt.WaitCursor)
        try:
            result = subprocess.run(
                command + [str(work_skp), str(work_dae)],
                capture_output=True, timeout=600)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Import SKP failed"), str(exc))
            return False
        QApplication.restoreOverrideCursor()
        # The converter (under Wine) may emit codepage bytes — never assume
        # UTF-8 when surfacing its output.
        detail = (result.stderr or result.stdout or b"").decode(
            "utf-8", errors="replace").strip()[-800:]
        if result.returncode != 0 or not work_dae.exists():
            QMessageBox.critical(
                self, tr("Import SKP failed"),
                detail or tr("The converter produced no output."))
            return False
        dae = work_dae
        if tmpdir is not None:
            dae = skp.parent / work_dae.name
            shutil.move(str(work_dae), dae)
            tex_dir = tmpdir / ascii_stem
            if tex_dir.is_dir():
                target = skp.parent / ascii_stem
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(tex_dir), target)
            shutil.rmtree(tmpdir, ignore_errors=True)
        self._import_dae_path(dae)
        self._import_name = skp.name
        self._update_title()
        return True

    # URL del exe limpio (solo codigo MIT: bindea la DLL en runtime, no
    # contiene nada de Trimble) — se publica como asset de los releases.
    _SKP2DAE_EXE_URL = ("https://github.com/ingelibre/ingetrazo/releases/"
                        "latest/download/skp2dae.exe")
    #: Repo público del add-on de Blender cuyo release trae SketchUpAPI.dll.
    _SKP_ADDON_REPO = "RedHaloStudio/Sketchup_Importer"

    @staticmethod
    def _download_bytes(url: str, timeout: int = 120) -> bytes:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "IngeTrazo"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    @staticmethod
    def _extract_skp_dlls(zip_bytes: bytes, dest: Path) -> list[str]:
        """Pull the SketchUp runtime DLLs out of the add-on zip into ``dest``.
        Returns the names extracted (empty when none found)."""
        import io
        import zipfile
        wanted = ("SketchUpAPI.dll", "SketchUpCommonPreferences.dll")
        got = []
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for entry in zf.namelist():
                base = entry.rsplit("/", 1)[-1]
                if base in wanted and base not in got:
                    (dest / base).write_bytes(zf.read(entry))
                    got.append(base)
        return got

    def _install_skp_converter(self) -> bool:
        """One-click install of the skp2dae converter for non-technical
        users: the MIT exe comes from OUR releases; the proprietary SketchUp
        DLL is fetched by the USER'S machine from the Blender add-on's own
        public release (never hosted or redistributed by us)."""
        import json as _json
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QApplication
        dest = Path.home() / ".local" / "share" / "skp2dae"
        dest.mkdir(parents=True, exist_ok=True)
        QApplication.setOverrideCursor(_Qt.WaitCursor)
        try:
            self.statusBar().showMessage(tr("Downloading skp2dae…"))
            QApplication.processEvents()
            (dest / "skp2dae.exe").write_bytes(
                self._download_bytes(self._SKP2DAE_EXE_URL))

            self.statusBar().showMessage(
                tr("Downloading the SketchUp library (Blender add-on)…"))
            QApplication.processEvents()
            api = (f"https://api.github.com/repos/{self._SKP_ADDON_REPO}"
                   "/releases/latest")
            release = _json.loads(self._download_bytes(api).decode("utf-8"))
            asset_url = next(
                a["browser_download_url"] for a in release.get("assets", [])
                if a["name"].lower().endswith(".zip"))
            got = self._extract_skp_dlls(
                self._download_bytes(asset_url, timeout=300), dest)
            if "SketchUpAPI.dll" not in got:
                raise RuntimeError(
                    tr("The add-on zip did not contain SketchUpAPI.dll"))
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Import SKP"),
                                 tr("Automatic install failed: {err}",
                                    err=str(exc)))
            return False
        QApplication.restoreOverrideCursor()
        import shutil as _shutil
        import sys as _sys
        if _sys.platform != "win32" and _shutil.which("wine") is None:
            QMessageBox.information(
                self, tr("Import SKP"),
                tr("Converter installed, but Wine is missing. Install it "
                   "with your package manager (e.g. sudo apt install wine) "
                   "and try again."))
            return False
        self.statusBar().showMessage(tr("skp2dae converter installed"), 4000)
        return True

    def _on_import_skp(self) -> None:
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import SKP"), "",
            tr("SketchUp (*.skp);;All files (*)"))
        if not path_str:
            return
        self.import_skp_path(Path(path_str))

    def _on_clear_texture_cache(self) -> None:
        """Empty the app's texture cache (images extracted from .skp imports
        and unpacked from .igz containers). Saved .igz documents carry their
        own copy and re-extract on open; .skp-imported faces lose their texture
        until the file is imported again — hence the confirmation."""
        from core.texture import (clear_texture_cache, texture_cache_root,
                                  texture_cache_stats)
        count, size = texture_cache_stats()
        if not count:
            QMessageBox.information(
                self, tr("Texture cache"),
                tr("The texture cache is already empty.\n\n{path}",
                   path=str(texture_cache_root())))
            return
        answer = QMessageBox.question(
            self, tr("Clear texture cache"),
            tr("Delete {count} image(s) ({mb:.1f} MB) from:\n{path}\n\n"
               "Saved .igz documents carry their own copy and rebuild it when "
               "opened. Faces textured by a .skp import that was never saved "
               "lose their texture until you import the .skp again.",
               count=count, mb=size / (1024 * 1024),
               path=str(texture_cache_root())),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = clear_texture_cache()
        self.statusBar().showMessage(
            tr("Texture cache cleared ({count} files).", count=removed), 4000)

    def _obj_unit(self, path) -> "float | None":
        """The metres-per-unit factor for an OBJ, asked once per import.

        The format records no unit at all, so the file cannot say and the
        importer must not guess in silence: Sweet Home 3D's furniture is in
        centimetres and comes in a hundred times too big, while our own
        exports are metres and must round-trip untouched.

        Asked, but with the answer already filled in. Where the model's own
        size rules metres out — 200 units across is not a 200 m chair — that
        reading is preselected; where it is genuinely ambiguous the last
        choice is, so importing a folder of one library is one confirmation
        and then muscle memory. Cancel means cancel the import.
        """
        from PySide6.QtWidgets import QInputDialog
        from formats.obj import OBJ_UNITS, suggest_unit

        keys = ["m", "cm", "mm", "in", "ft"]
        labels = [tr("Metres"), tr("Centimetres"), tr("Millimetres"),
                  tr("Inches"), tr("Feet")]
        guess = suggest_unit(path)
        if guess == "m":
            guess = str(QSettings().value("import/obj_unit", "m") or "m")
        idx = keys.index(guess) if guess in keys else 0
        label, ok = QInputDialog.getItem(
            self, tr("Import OBJ"),
            tr("An OBJ file does not record its unit. What is this model in?"),
            labels, idx, False)
        if not ok:
            return None
        key = keys[labels.index(label)]
        QSettings().setValue("import/obj_unit", key)
        return OBJ_UNITS[key]

    def _on_import_igz(self) -> None:
        """Bring another IngeTrazo document in as ONE component, placed
        with a click — SketchUp's Import of a .skp. Furniture drawn in its
        own file (a pergola, an arch, a lamp post) lands in the plaza with
        its groups, materials and layers intact (see :mod:`core.insert`)."""
        from core.insert import import_document_as_component
        from core.scene import Scene as _Scene
        from formats import igz as _igz
        start = (str(self._current_path.parent)
                 if self._current_path is not None else "")
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import IngeTrazo document"), start, IGZ_FILE_FILTER)
        if not path_str:
            return
        path = Path(path_str)
        if (self._current_path is not None
                and path.resolve() == self._current_path.resolve()):
            QMessageBox.warning(
                self, tr("Import IngeTrazo document"),
                tr("That is the document you are editing."))
            return
        self.viewport.end_group_edit()
        temp = _Scene()
        try:
            _igz.load_into(temp, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, tr("Import IngeTrazo document failed"), str(exc))
            return
        comp = import_document_as_component(self.viewport.scene, temp,
                                            path.stem)
        if comp is None:
            QMessageBox.warning(
                self, tr("Import IngeTrazo document"),
                tr("“{name}” has no geometry.", name=path.name))
            return
        # The file's origin is the handle (SketchUp's component axes): the
        # arch's footings, drawn below z=0, go below grade in the plaza too.
        from PySide6.QtGui import QVector3D
        self._start_place(comp, anchor=QVector3D(0.0, 0.0, 0.0))

    def _on_import_obj(self) -> None:
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import OBJ"), "", tr("Wavefront OBJ (*.obj);;All files (*)"))
        if not path_str:
            return
        path = Path(path_str)
        scale = self._obj_unit(path)
        if scale is None:
            return
        dlg, cb = self._import_progress(tr("Importing {name}…", name=path.name))
        cmd = SnapshotImport(
            lambda scene: obj_format.load_obj(scene, path, progress=cb,
                                              scale=scale))
        try:
            self.viewport.history.execute(cmd)
        except Exception as exc:  # noqa: BLE001
            dlg.close()
            QMessageBox.critical(self, tr("Import OBJ failed"), str(exc))
            return
        self._prepare_import_display(cmd, cb)
        dlg.close()
        self.viewport.update()
        self._import_name = path.name
        self._update_title()
        self.statusBar().showMessage(tr("Imported {name}", name=path.name), 3000)

    def _on_import_image(self) -> None:
        """Import a picture to trace over (SketchUp's ``Import ▸ image``).

        The file is copied into the texture cache straight away, so the model
        never depends on where the user happened to leave the original — the
        same content-addressed store the .skp importer fills, which also means
        importing the same scan twice costs one copy.
        """
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import image"), "",
            tr("Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;"
               "All files (*)"))
        if not path_str:
            return
        path = Path(path_str)
        from core.image_plane import image_aspect
        aspect, pw, ph = image_aspect(path)
        if pw <= 0 or ph <= 0:
            QMessageBox.critical(
                self, tr("Import image failed"),
                tr("{name} is not an image this build can read.",
                   name=path.name))
            return
        from core.texture import cache_image
        try:
            cached = cache_image(path.read_bytes(), path.name, "imported")
        except OSError as exc:
            QMessageBox.critical(self, tr("Import image failed"), str(exc))
            return

        from tools.image import ImageTool
        tool = ImageTool()
        tool.load(str(cached), aspect, label=path.stem)
        self.viewport.set_active_tool(tool)
        for action in self._tool_actions.values():
            action.setChecked(False)
        self._tool_label.setText(tr("Tool: {name}", name=tr("Image")))
        self._refresh_vcb()
        self.viewport.flash_status(
            tr("Click a corner and drag to size the image, or type a width "
               "and press Enter (Esc cancels)"), 6000)
        self.viewport.update()

    def _on_image_size(self) -> None:
        """Resize a placed reference image to a real-world width.

        This is the step that makes a scan usable: you place it roughly, then
        measure one thing on it you already know — a wall, a scale bar — and
        type that. Proportions are kept by default, and the image grows from
        its origin corner so what you already traced stays put relative to it.
        """
        from PySide6.QtWidgets import QInputDialog
        from core.image_plane import ImagePlane
        from core.history import TransformImagePlaneCommand
        sel = [e for e in self.viewport.scene.selection
               if isinstance(e, ImagePlane)]
        if not sel:
            return
        image = sel[0]
        width, ok = QInputDialog.getDouble(
            self, tr("Image size"), tr("Width (m):"),
            image.width(), 0.0001, 1_000_000.0, 4)
        if not ok or width <= 0.0:
            return
        u, v = image.scaled(width, keep_aspect=True)
        self.viewport.history.execute(
            TransformImagePlaneCommand(image, u=u, v=v))
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Image resized to {size}", size=fmt_pair(u.length(), v.length())), 4000)

    def _on_image_opacity(self) -> None:
        """Fade a reference image so the model and its lines read over it
        (the same control the base map has)."""
        from PySide6.QtWidgets import QInputDialog
        from core.image_plane import ImagePlane
        from core.history import SetImagePlaneOpacityCommand
        sel = [e for e in self.viewport.scene.selection
               if isinstance(e, ImagePlane)]
        if not sel:
            return
        image = sel[0]
        pct, ok = QInputDialog.getInt(
            self, tr("Image opacity"), tr("Opacity (%):"),
            int(round(100 * float(getattr(image, "opacity", 1.0)))), 5, 100, 5)
        if not ok:
            return
        self.viewport.history.execute(
            SetImagePlaneOpacityCommand(image, pct / 100.0))
        self.viewport.update()

    def _on_import_orthophoto(self) -> None:
        """Import a GeoTIFF orthomosaic (a WebODM ``odm_orthophoto.tif``, a
        QGIS export) as a georeferenced reference image: the file's own
        pixel → UTM transform places it on the scene's datum at its true
        size and orientation, so the model is traced over the real ground.
        Display-only, like every reference image (invariant #4); locked on
        arrival so a stray drag never moves the survey."""
        from georef.datum import SceneDatum
        from georef.geotiff import (GeoTiffError, describe, read_info,
                                    read_rgba, rgba_to_qimage,
                                    unsupported_reason)

        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import orthomosaic"), "",
            tr("GeoTIFF (*.tif *.tiff);;All files (*)"))
        if not path_str:
            return
        path = Path(path_str)
        try:
            info = read_info(path)
        except (GeoTiffError, OSError) as exc:
            QMessageBox.critical(self, tr("Import orthomosaic"), str(exc))
            return
        if not info.georeferenced:
            QMessageBox.warning(
                self, tr("Import orthomosaic"),
                tr("{name} carries no georeference (no map transform or an "
                   "unknown coordinate system). Import it with "
                   "File ▸ Import ▸ Image and size it by hand.",
                   name=path.name))
            return
        reason = unsupported_reason(info)
        if reason:
            QMessageBox.critical(
                self, tr("Import orthomosaic"),
                tr("{name}: {reason} is not supported by this reader.",
                   name=path.name, reason=reason))
            return

        scene = self.viewport.scene
        corners = info.corners_geodetic()
        datum = getattr(scene, "georef", None)
        datum_existed = datum is not None
        if datum is None:
            # The picture knows where it is — anchor the scene on its centre
            # rather than asking for coordinates the user would look up.
            lat = sum(c[0] for c in corners) / 4.0
            lon = sum(c[1] for c in corners) / 4.0
            datum = SceneDatum(lat, lon)
            scene.georef = datum

        dlg, cb = self._import_progress(tr("Importing {name}…", name=path.name))
        max_px = 8192
        try:
            max_px = max(1024, min(8192, int(self.viewport.max_texture_size())))
        except Exception:  # noqa: BLE001 — no GL context yet: keep the default
            pass
        try:
            rgba, factor = read_rgba(
                info, max_px=max_px,
                progress=lambda fr: (cb(fr * 0.9, "Decoding the orthomosaic…")
                                     or True))
        except (GeoTiffError, OSError, MemoryError) as exc:
            dlg.close()
            QMessageBox.critical(self, tr("Import orthomosaic"), str(exc))
            return
        cb(0.92, "Storing the picture…")
        image = rgba_to_qimage(rgba)
        del rgba
        from PySide6.QtCore import QBuffer, QByteArray
        from core.texture import cache_image
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QBuffer.WriteOnly)
        ext = "webp"
        if not image.save(buf, "WEBP", 92):        # no WebP plugin: PNG
            buf.close()
            data = QByteArray()
            buf = QBuffer(data)
            buf.open(QBuffer.WriteOnly)
            image.save(buf, "PNG")
            ext = "png"
        buf.close()
        try:
            cached = cache_image(bytes(data), f"{path.stem}.{ext}", "imported")
        except OSError as exc:
            dlg.close()
            QMessageBox.critical(self, tr("Import orthomosaic"), str(exc))
            return
        dlg.close()

        # Place it: the plane's origin is the picture's bottom-left, u its
        # width, v its height — the corners come in that order, already
        # turned by the datum's north angle. On the datum plane (Z = 0),
        # like the base map.
        from core.image_plane import ImagePlane
        from core.history import AddImagePlaneCommand
        bl, br, _tr, tl = [datum.geodetic_to_local(lat, lon)
                           for lat, lon in corners]
        u, v = br - bl, tl - bl
        aspect = v.length() / u.length() if u.length() > 1e-9 else 1.0
        plane = ImagePlane(str(cached), bl, u, v, aspect=aspect,
                           name=path.stem, locked=True)
        self.viewport.history.execute(AddImagePlaneCommand(plane))
        if not datum_existed:
            lo, hi = QVector3D(bl), QVector3D(bl)
            for c in plane.corners():
                lo = QVector3D(min(lo.x(), c.x()), min(lo.y(), c.y()), 0.0)
                hi = QVector3D(max(hi.x(), c.x()), max(hi.y(), c.y()), 0.0)
            self.georef_tray.base_map.setup_for_bounds(datum, lo, hi)
            self.viewport.camera.set_view("top")
            self.viewport.camera.fit_to(lo, hi)
        self.georef_tray.on_scene_changed()
        self.viewport.update()
        w_m, h_m = u.length(), v.length()
        self.statusBar().showMessage(
            tr("Imported {name} — {w:.0f} × {h:.0f} m, {info}{reduced}",
               name=path.name, w=w_m, h=h_m, info=describe(info),
               reduced=(tr(", reduced {k}×", k=factor) if factor > 1 else "")),
            8000)

    def _unlock_image(self, image) -> None:
        """Unlock one reference image (from the right-click over it) and
        select it, so the next click can move, resize or delete it."""
        image.locked = False
        scene = self.viewport.scene
        scene.select([image])
        scene.version += 1
        self.viewport.update()
        self.statusBar().showMessage(
            tr("Image unlocked: {name}", name=image.name), 3000)

    def _delete_image(self, image) -> None:
        """Delete one reference image (from the right-click over it)."""
        from core.history import DeleteImagePlanesCommand
        self.viewport.history.execute(DeleteImagePlanesCommand([image]))
        self.viewport.scene.selection.discard(image)
        self.viewport.update()

    def add_appimage_to_menu(self) -> None:
        """Write the launcher + icon for the running AppImage."""
        from core.appimage import appimage_path, integrate
        img = appimage_path()
        if img is None:
            return
        try:
            f = integrate(img)
        except OSError as exc:
            QMessageBox.warning(self, tr("Add to the applications menu"),
                                str(exc))
            return
        self.statusBar().showMessage(
            tr("Launcher added: {path}", path=str(f)), 6000)

    def remove_appimage_from_menu(self) -> None:
        from core.appimage import remove
        remove()
        self.statusBar().showMessage(
            tr("Launcher removed from the applications menu"), 5000)

    def _on_toggle_image_lock(self) -> None:
        """Lock an image so clicks fall through to what you are drawing on top
        of it — the usual state once a scan is aligned."""
        from core.image_plane import ImagePlane
        for image in [e for e in self.viewport.scene.selection
                      if isinstance(e, ImagePlane)]:
            image.locked = not image.locked
        self.viewport.scene.version += 1
        self.viewport.update()

    def activate_select_tool(self) -> None:
        """Back to Select — what the Image tool calls once a picture is
        placed, so the next click doesn't stamp a second copy."""
        self._activate_tool("select")

    def _on_import_dwg(self) -> None:
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import DWG"), "",
            tr("AutoCAD DWG (*.dwg);;All files (*)"))
        if path_str:
            self._import_dwg_path(Path(path_str))

    def _import_dwg_path(self, path: Path) -> bool:
        """Import a DWG through the LibreDWG satellite (D3): convert to a
        temporary DXF, feed the DXF pipeline, discard the temp. The user
        never sees the intermediate — IngeCAD's dwg_bridge pattern."""
        from formats.dwg_bridge import (DwgBridgeError, discard_temp_dxf,
                                        dwg_to_dxf, have_dwg_support)

        if not have_dwg_support():
            QMessageBox.critical(
                self, tr("Import DWG failed"),
                tr("The LibreDWG converter (dwg2dxf) is not available in "
                   "this installation."))
            return False
        dlg, cb = self._import_progress(tr("Importing {name}…",
                                           name=path.name))
        cb(0.02, tr("Converting DWG…"))
        try:
            dxf = dwg_to_dxf(path)
        except DwgBridgeError as exc:
            dlg.close()
            QMessageBox.critical(self, tr("Import DWG failed"), str(exc))
            return False
        dlg.close()
        try:
            ok = self._import_dxf_path(dxf, label=path)
        finally:
            discard_temp_dxf(dxf)
        return ok

    def _on_import_dxf(self) -> None:
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import DXF"), "",
            tr("AutoCAD DXF (*.dxf);;All files (*)"))
        if path_str:
            self._import_dxf_path(Path(path_str))

    def _import_dxf_path(self, path: Path, label: "Path | None" = None) -> bool:
        """Import a DXF: 2D CAD linework as tagged layer groups (D1). The
        unit comes from the header; a unitless file is asked about, the OBJ
        importer's rule — never guess in silence. ``label`` is the file the
        USER opened when ``path`` is an intermediate (the DWG bridge)."""
        shown = label or path
        from formats.dxf_in import (load_dxf, open_document,
                                    suggest_unit_scale)

        # ALWAYS confirmed, suggestion preselected (the OBJ importer's
        # doctrine: asked, but with the answer already filled in). The
        # suggestion measures the drawing itself, because CAD headers lie —
        # this session's test plan declares millimetres while drawn in
        # metres. Parsed once; the same document feeds the load.
        try:
            doc = open_document(path)
        except Exception as exc:  # noqa: BLE001 — unreadable file
            QMessageBox.critical(self, tr("Import DXF failed"), str(exc))
            return False
        suggested, _code = suggest_unit_scale(doc)
        scale = self._dxf_unit(shown, suggested)
        if scale is None:
            return False
        dlg, cb = self._import_progress(tr("Importing {name}…",
                                           name=shown.name))
        stats: dict = {}
        cmd = SnapshotImport(
            lambda scene: stats.update(
                load_dxf(scene, path, progress=cb, scale=scale, doc=doc,
                         name=shown.stem)))
        try:
            self.viewport.history.execute(cmd)
        except Exception as exc:  # noqa: BLE001 — surface parse errors
            dlg.close()
            QMessageBox.critical(self, tr("Import DXF failed"), str(exc))
            return False
        self._prepare_import_display(cmd, cb)
        dlg.close()
        # A plan drawn kilometres from the origin (or huge next to the 20 m
        # default camera) reads as "nothing imported" without this.
        self._on_zoom_extents()
        self.viewport.update()
        self._import_name = shown.name
        self._update_title()
        msg = tr("Imported {name}: {edges} edges in {groups} tagged groups",
                 name=shown.name, edges=stats.get("edges", 0),
                 groups=stats.get("groups", 0))
        offset = stats.get("offset")
        if offset:
            msg += "  ·  " + tr(
                "moved near the origin (survey coordinates); offset "
                "{x:,.0f}, {y:,.0f} m", x=offset[0], y=offset[1])
        self.statusBar().showMessage(msg, 8000)
        return True

    def _dxf_unit(self, path, header_scale=None) -> "float | None":
        """Confirm the drawing's unit. The header's declaration (when there
        is one) arrives preselected; without one, the last answer does —
        importing a batch from one office is Enter, Enter, Enter."""
        from PySide6.QtWidgets import QInputDialog

        keys = ["mm", "cm", "m", "in", "ft"]
        factors = {"mm": 0.001, "cm": 0.01, "m": 1.0,
                   "in": 0.0254, "ft": 0.3048}
        labels = [tr("Millimetres"), tr("Centimetres"), tr("Metres"),
                  tr("Inches"), tr("Feet")]
        by_scale = {v: k for k, v in factors.items()}
        last = (by_scale.get(header_scale)
                or str(QSettings().value("import/dxf_unit", "mm") or "mm"))
        idx = keys.index(last) if last in keys else 0
        label, ok = QInputDialog.getItem(
            self, tr("Import DXF"),
            tr("What unit is this drawing in? (CAD headers often lie)"),
            labels, idx, False)
        if not ok:
            return None
        key = keys[labels.index(label)]
        QSettings().setValue("import/dxf_unit", key)
        return factors[key]

    def _on_import_photomesh(self) -> None:
        """Import a WebODM/ODM photogrammetric survey as georeferenced reference
        geometry (Track G, G6) — the drone flight you then trace on top of.

        Display-only: it goes to ``scene.photo_mesh``, never through the
        topology engine (invariant #4).
        """
        from georef.datum import SceneDatum, utm_inverse
        from georef.photomesh import find_anchor, load_odm_obj

        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import photogrammetric mesh"), "",
            tr("ODM textured model (*.obj);;All files (*)"))
        if not path_str:
            return
        path = Path(path_str)

        scene = self.viewport.scene
        anchor = find_anchor(path)
        datum = getattr(scene, "georef", None)
        datum_existed = datum is not None
        if datum is None:
            # The survey knows where it is — anchor the scene on it rather than
            # making the user type coordinates they'd have to look up.
            if anchor is None:
                QMessageBox.warning(
                    self, tr("Import photogrammetric mesh"),
                    tr("This model is not georeferenced and the scene has no "
                       "datum yet. Set a location in the Terrain tray first, or "
                       "pick an ODM export that includes "
                       "odm_georeferencing_model_geo.txt."))
                return
            lat, lon = utm_inverse(anchor.east, anchor.north,
                                   anchor.zone, anchor.northern)
            datum = SceneDatum(lat, lon)
            scene.georef = datum

        # Load with ODM's own heights untouched (ground_ref=0). The scene's
        # vertical zero is decided below, from the survey alone — never from the
        # DEM, which is a different vertical datum and would also make the
        # result depend on whether tiles had downloaded yet.
        dlg, cb = self._import_progress(tr("Importing {name}…", name=path.name))
        mesh, images, exc = self._load_photomesh_threaded(path, datum, 0.0, cb)
        if exc is not None:
            dlg.close()
            QMessageBox.critical(self, tr("Import failed"), str(exc))
            return
        if mesh is None or mesh.triangle_count == 0:
            dlg.close()
            self.statusBar().showMessage(
                tr("No triangles found in the model."), 4000)
            return

        # ---- The vertical zero ------------------------------------------
        # The scene works in local metres, so the survey's ~1750 m of altitude
        # has to come off. What matters is that the amount taken off is
        # RECORDED: datum.alt is the absolute elevation of local Z=0, so every
        # elevation can be reported as a real altitude instead of a number
        # floating above an unknown reference.
        from georef.photomesh import vertical_origin
        if datum_existed and datum.alt:
            # An established scene already has a vertical zero; a second survey
            # joins it rather than redefining it, or the two would not line up.
            origin = float(datum.alt)
        else:
            origin = vertical_origin(mesh)
            if origin is None:
                origin = 0.0
            datum.alt = origin

        if origin:
            mesh.vertices[:, 2] -= origin
            mesh.invalidate_index()     # the geometry moved under the index

        mesh.visible = True
        # Its own layer, so switching the survey off to look at what you drew
        # doesn't take your model with it.
        from core.layers import SURVEY_LAYER, Layer
        if scene.layer(SURVEY_LAYER) is None:
            scene.layers.append(Layer(SURVEY_LAYER))
        mesh.layer = SURVEY_LAYER
        # Keep the downscaled atlases on the mesh so saving the document does
        # not depend on the ODM export still being where it was imported from.
        mesh.images = images or {}
        scene.photo_mesh = mesh
        self.viewport.upload_photo_mesh(mesh, mesh.images)
        self.georef_tray.base_map.sync_photo_mesh()

        # Point the base map at the flown ground. Survey and imagery already
        # share the datum, so they line up by construction — but the tile layer
        # only fetches the area it was told to capture, and by default that's a
        # square at the origin. Without this the imagery is simply absent under
        # the survey, which looks exactly like "it doesn't line up".
        mn, mx = mesh.bounds()
        if mn is not None:
            self.georef_tray.base_map.setup_for_bounds(datum, mn, mx)
        self.georef_tray.raise_()
        dlg.close()
        if mn is not None:
            self.viewport.camera.set_view("iso")
            self.viewport.camera.fit_to(mn, mx)
        self.viewport.update()
        missing = mesh.missing_textures
        if missing:
            self.statusBar().showMessage(
                tr("Imported {name} — {n} texture(s) not found").format(
                    name=path.name, n=len(missing)), 6000)
        else:
            self.statusBar().showMessage(
                tr("Imported {name} — {t} triangles").format(
                    name=path.name, t=f"{mesh.triangle_count:,}"), 4000)

    def _on_photo_progress(self, fraction: float, text: str) -> None:
        """Progress from the import worker, delivered on the UI thread."""
        callback = getattr(self, "_photo_progress", None)
        if callback is not None:
            callback(fraction, text)

    def _load_photomesh_threaded(self, path, datum, ground, cb):
        """Parse the OBJ and decode its atlases off the UI thread.

        Both halves are slow enough to freeze the window — the real survey this
        was built against is 40 MB of OBJ plus 455 MB of PNG, and one atlas
        alone takes ~9 s to decode the first time. Neither touches ``Scene``,
        so both are safe off-thread; the GL upload stays with the caller.
        """
        from PySide6.QtCore import QEventLoop, QObject, QThread, Qt, Signal

        from georef.photomesh import load_atlas, load_odm_obj, plan_texture_sizes

        gl_max = self.viewport.max_texture_size()

        class _Worker(QObject):
            progressed = Signal(float, str)
            finished = Signal(object, object, object)   # (mesh, images, exc)

            def run(self):
                try:
                    self.progressed.emit(0.05, "Reading mesh…")
                    mesh = load_odm_obj(path, datum, ground_ref=ground)

                    from PySide6.QtGui import QImageReader
                    sizes, index_of = [], []
                    for i, material in enumerate(mesh.materials):
                        if material.texture is None or not material.texture.is_file():
                            continue
                        reader = QImageReader(str(material.texture))
                        size = reader.size()
                        if not size.isValid():
                            continue
                        sizes.append((size.width(), size.height()))
                        index_of.append(i)

                    targets = plan_texture_sizes(sizes, gl_max)
                    images = {}
                    for n, (i, target) in enumerate(zip(index_of, targets)):
                        self.progressed.emit(
                            0.15 + 0.85 * n / max(1, len(index_of)),
                            "Loading textures…")
                        image = load_atlas(mesh.materials[i].texture, target)
                        if not image.isNull():
                            images[i] = image
                    self.finished.emit(mesh, images, None)
                except Exception as exc:  # noqa: BLE001 — reported to caller
                    self.finished.emit(None, None, exc)

        thread = QThread(self)
        worker = _Worker()
        worker.moveToThread(thread)
        result = {}

        # A BOUND METHOD, not a lambda. A queued connection to a bare lambda has
        # no receiver QObject to marshal into, so Qt ends up running it on the
        # *worker* thread and the progress dialog's timer gets stopped
        # cross-thread ("Timers cannot be stopped from another thread"). Bound
        # to ``self``, delivery lands on the UI thread where the dialog lives.
        self._photo_progress = cb
        worker.progressed.connect(self._on_photo_progress, Qt.QueuedConnection)

        loop = QEventLoop()

        def _done(mesh, images, exc):
            result.update(mesh=mesh, images=images, exc=exc)
            loop.quit()

        worker.finished.connect(_done, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()
        loop.exec()
        thread.quit()
        thread.wait()
        worker.deleteLater()
        return result.get("mesh"), result.get("images"), result.get("exc")

    def _on_import_georef(self) -> None:
        """Import a KML/KMZ/GeoJSON alignment as georeferenced GeoPath traces —
        located via the datum, ready to profile / measure (Track G)."""
        from georef.geoimport import load_features
        from georef.datum import SceneDatum
        from georef.geopath import GeoPath
        from core.history import AddGeoPathCommand, CompoundCommand

        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Import georef"), "",
            tr("Georef (*.kml *.kmz *.geojson *.json);;All files (*)"))
        if not path_str:
            return
        try:
            feats = load_features(Path(path_str))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Import failed"), str(exc))
            return
        feats = [f for f in feats if len(f.points) >= 2]
        if not feats:
            self.statusBar().showMessage(
                tr("No lines or polygons found in the file."), 4000)
            return

        scene = self.viewport.scene
        datum = getattr(scene, "georef", None)
        if datum is None:      # anchor the scene at the imported data's centre
            pts = [p for f in feats for p in f.points]
            datum = SceneDatum(sum(p[0] for p in pts) / len(pts),
                               sum(p[1] for p in pts) / len(pts))
            scene.georef = datum

        cmds = []
        for f in feats:
            local = [datum.geodetic_to_local(la, lo) for la, lo in f.points]
            cmds.append(AddGeoPathCommand(GeoPath(local, closed=f.closed,
                                                  name=f.name)))
        self.viewport.history.execute(
            cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))

        # Sync the base-map panel + set a reference capture around the import.
        self.georef_tray.base_map.setup_for_import(datum, scene.geo_paths)
        self.georef_tray.raise_()
        # Frame the imported traces (top view).
        self._frame_geo_paths(scene.geo_paths)
        self.statusBar().showMessage(
            tr("Imported {n} feature(s) from {name}").format(
                n=len(feats), name=Path(path_str).name), 4000)

    def _frame_geo_paths(self, paths) -> None:
        from PySide6.QtGui import QVector3D
        pts = [p for gp in paths for p in gp.points]
        if not pts:
            return
        mn = QVector3D(min(p.x() for p in pts), min(p.y() for p in pts), 0.0)
        mx = QVector3D(max(p.x() for p in pts), max(p.y() for p in pts), 0.0)
        self.viewport.camera.set_view("top")
        self.viewport.camera.fit_to(mn, mx)
        self.viewport.update()

    def _on_export_ifc(self) -> None:
        self.viewport.end_group_edit()
        from core.bim import collect_objects
        if not collect_objects(self.viewport.scene):
            QMessageBox.information(
                self, tr("Export IFC"),
                tr("Nothing to export: tag geometry in the BIM panel first "
                   "(only tagged objects go to IFC)."))
            return
        path_str, _ = file_dialogs.getSaveFileName(
            self, tr("Export IFC"), "model.ifc",
            tr("IFC4 (*.ifc);;All files (*)"))
        if not path_str:
            return
        try:
            count = ifc_format.save_ifc(self.viewport.scene, path_str)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, tr("Export IFC failed"), str(exc))
            return
        self.statusBar().showMessage(
            tr("{n} IFC elements exported to {path}",
               n=count, path=path_str), 5000)

    def _on_export_stl(self) -> None:
        self._export("STL", "stl", tr("STL mesh (*.stl)"), stl_format.save_stl)

    def _on_export_obj(self) -> None:
        self._export("OBJ", "obj", tr("Wavefront OBJ (*.obj)"), obj_format.save_obj)

    def _on_export_skp(self) -> None:
        """Native SketchUp export — opens directly in SketchUp 2017+."""
        self._export("SketchUp", "skp", tr("SketchUp (*.skp)"),
                     skp_out_format.save_skp)

    def _on_export_glb(self) -> None:
        """Single-file 3D export (geometry + materials + textures embedded).
        Best format for 'send it so a colleague can view it' — no texture folder
        to lose, opens in Blender / web viewers / Windows 3D Viewer."""
        self._export("GLB", "glb", tr("glTF binary (*.glb)"), gltf_format.save_glb)

    def _on_export_dae(self) -> None:
        """COLLADA export — the 'open it back in SketchUp' bridge. Copies the
        texture images beside the .dae (send both, or use GLB)."""
        self._export("COLLADA", "dae", tr("COLLADA (*.dae)"), dae_format.save_dae)

    def _on_import_survey_points(self) -> None:
        """File-menu twin of the Terrain panel's survey-CSV import, so every
        way into the model lives under File ▸ Import."""
        self.georef_tray.survey._on_import()
        self.georef_tray.raise_()

    def _on_export_view_dxf(self) -> None:
        """The view on screen as a 2D line drawing for CAD, hidden lines
        removed (José Castro Basso, FADU–UDELAR). Parallel: true size in
        metres, edges / profiles / section cut on their own layers, as the
        composer's «Export view as DXF». Perspective (two-point included):
        what the window shows, true size at the depth of the orbit
        target."""
        path, _ = file_dialogs.getSaveFileName(
            self, tr("Export current view as DXF"), "vista.dxf",
            "DXF (*.dxf)")
        if not path:
            return
        from core.hlr import (KIND_CUT, KIND_PROFILE, hlr_drawing,
                              hlr_perspective)
        from formats.dxf_out import save_dxf_layers
        vp = self.viewport
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            geometry = vp.hlr_geometry()
            if vp.camera.perspective:
                groups = [("VISTA", hlr_perspective(vp.scene, vp.camera,
                                                    geometry=geometry))]
            else:
                d = hlr_drawing(vp.scene, vp.camera, geometry=geometry)
                k = d.kinds
                groups = [("VISTA", d.segs[(k != KIND_CUT)
                                           & (k != KIND_PROFILE)]),
                          ("VISTA-PERFIL", d.segs[k == KIND_PROFILE]),
                          ("VISTA-CORTE", d.segs[k == KIND_CUT])]
            n = save_dxf_layers(path, groups)
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Export DXF failed"), str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            tr("Exported {n} lines to {name}", n=n, name=path), 5000)

    def _on_export_image(self) -> None:
        """Hi-res 2D export of the current view (SketchUp's 'Export 2D
        Graphic'): pick a file and a pixel width; height follows the
        viewport's aspect so the image matches exactly what you framed."""
        from PySide6.QtWidgets import QInputDialog
        base = (self._current_path.stem if self._current_path is not None
                else "untitled")
        path_str, _ = file_dialogs.getSaveFileName(
            self, tr("Export Image"), f"{base}.png",
            tr("PNG image (*.png);;JPEG image (*.jpg)"))
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            path = path.with_suffix(".png")
        width, ok = QInputDialog.getInt(
            self, tr("Export Image"), tr("Width in pixels:"),
            3840, 640, 16384, 320)
        if not ok:
            return
        image = self.viewport.render_image(width)
        if image is None or image.isNull() or not image.save(str(path)):
            QMessageBox.critical(self, tr("Export Image failed"),
                                 tr("Could not render or save the image."))
            return
        self.statusBar().showMessage(
            tr("Exported image {w}×{h} → {name}",
               w=image.width(), h=image.height(), name=path.name), 4000)

    def _export(self, label: str, suffix: str, file_filter, writer) -> None:
        base = (self._current_path.stem if self._current_path is not None
                else "untitled")
        path_str, _ = file_dialogs.getSaveFileName(
            self, tr("Export {label}", label=label), f"{base}.{suffix}", file_filter)
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != f".{suffix}":
            path = path.with_suffix(f".{suffix}")
        try:
            writer(self.viewport.scene, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, tr("Export {label} failed", label=label), str(exc))
            return
        self.statusBar().showMessage(
            tr("Exported {label} → {name}", label=label, name=path.name), 3000)

    def _confirm_discard(self, prompt: str) -> bool:
        """Return True if it's safe to discard the current drawing."""
        if not self._is_dirty():
            return True
        # Built by hand rather than with QMessageBox.question: on macOS
        # that is a NATIVE alert, which draws «Don't Save» as a red
        # destructive button — and under the dark scheme main.py forces,
        # red text on a black button, barely readable. Qt's own dialog
        # wears the app's palette, like every other window here.
        box = QMessageBox(
            QMessageBox.Question, tr("Unsaved changes"),
            tr("{prompt}\n\nUnsaved changes will be lost.", prompt=prompt),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            self)
        box.setOption(QMessageBox.Option.DontUseNativeDialog, True)
        box.setDefaultButton(QMessageBox.Save)
        answer = box.exec()
        if answer == QMessageBox.Save:
            self._on_save()
            return not self._is_dirty()
        return answer == QMessageBox.Discard

    def _is_dirty(self) -> bool:
        return self.viewport.scene.version != self._saved_version

    def _on_scene_version_changed(self, _version: int) -> None:
        self._update_title()

    def _update_title(self) -> None:
        if self._current_path is not None:
            name = self._current_path.name
        elif self._import_name:
            name = self._import_name
        else:
            name = tr("Untitled")
        marker = " *" if self._is_dirty() else ""
        self.setWindowTitle(f"IngeTrazo — {name}{marker}")
        self._refresh_sheet_tabs()      # a new / opened document: its sheets

    # ---- Window lifecycle ---------------------------------------------------
    def closeEvent(self, event) -> None:
        if not self._confirm_discard(tr("Quit IngeTrazo?")):
            event.ignore()
            return
        # A clean goodbye: whatever the user decided (save or discard), this
        # session's recovery slot no longer speaks for anyone.
        from core import autosave
        autosave.clear(self._current_path)
        # The window arrangement (toolbars, docks, size) IS a preference.
        # Closing mid-presentation must remember the WORKSPACE, not the
        # clean screen's everything-hidden state.
        act = getattr(self, "_act_clean_screen", None)
        clean_state = getattr(self, "_clean_screen_state", None)
        st = QSettings()
        st.setValue("ui/window_state",
                    clean_state if (act is not None and act.isChecked()
                                    and clean_state is not None)
                    else self.saveState())
        st.setValue("ui/window_geometry", self.saveGeometry())
        # Free every GL texture while a GL context still exists — the survey
        # atlases (hundreds of MB), the tile and terrain textures, and the
        # general texture cache (faces, reference images). Letting Qt tear
        # them down leaks each with a "Texture has not been destroyed"
        # warning; the context's aboutToBeDestroyed hook alone fires too late
        # on app exit, when the Python side is already coming apart.
        try:
            self.viewport.release_gl_textures()
        except Exception:  # noqa: BLE001 — never block quitting on cleanup
            pass
        super().closeEvent(event)
