# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The **Layers** toolbar: layer work without opening the Layers tab.

- the layer drop-down. With something selected in the model it shows
  that selection's layer, and picking a layer MOVES the selection onto it
  (one undo step). With nothing selected it is the layer you work on: it
  shows the active layer, and picking one makes it active — new groups,
  components, dimensions and texts go to it. Each row shows the layer's
  eye, padlock, isolate mark and colour; the eye, the padlock and the
  isolate mark can be clicked right there, the list staying open. Isolate
  shows that layer alone (the default layer stays on: it holds the insides
  of every object); clicked again on the isolated layer, every layer comes
  back;
- on the layer of what is SELECTED, one click each: make it active,
  isolate it, hide it, lock it. The drop-down serves the layer you know by
  name; these serve the object you see and whose layer you do not know —
  an imported drawing with a hundred layers, someone else's model;
- move the selection onto the active layer (one undo step), show every
  layer, and go back to the previous layer state.

Everything goes through the Layers panel (views.layers_panel), so the
panel, the toolbar and the right-click menus never disagree.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QStyle,
                               QStyledItemDelegate, QToolBar)

from core import layers as L
from core.i18n import tr

#: Where the eye, the padlock, the isolate mark and the swatch sit in a
#: drop-down row, from its left edge (px) — the delegate paints there and the
#: click test reads the same numbers.
_EYE_X, _LOCK_X, _ISO_X, _SWATCH_X, _TEXT_X = 4, 24, 44, 64, 86
_GLYPH = 16
#: Item data roles.
_NAME = Qt.UserRole
_SEPARATE = Qt.UserRole + 1


def _ink() -> QColor:
    return QApplication.palette().text().color()


# ---- Icons -------------------------------------------------------------------

def toolbar_icon(key: str) -> QIcon:
    """The Layers toolbar's icons: drawn with the other tool icons
    (views.icons, keys ``layers_*``), in the same ink and accent."""
    from views.icons import tool_icon
    return tool_icon(f"layers_{key}")


def isolate_icon(on: bool) -> QIcon:
    """A row's isolate mark: a target, filled on the layer shown alone."""
    ink = _ink()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if on:
        p.setPen(QPen(ink, 1.3))
        p.drawEllipse(QRectF(2, 2, 14, 14))
        # Solid in the ink, not the accent: it must read on the list's
        # highlighted row too, which is the accent.
        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        p.drawEllipse(QRectF(5, 5, 8, 8))
    else:
        faint = QColor(ink)
        faint.setAlpha(110)
        p.setPen(QPen(faint, 1.2))
        p.drawEllipse(QRectF(2, 2, 14, 14))
        p.drawEllipse(QRectF(6.5, 6.5, 5, 5))
    p.end()
    return QIcon(pm)


# ---- The drop-down -----------------------------------------------------------

class _LayerDelegate(QStyledItemDelegate):
    """A drop-down row: eye, padlock, isolate mark, colour swatch, then the
    name — the active layer's in bold."""

    def __init__(self, combo) -> None:
        super().__init__(combo)
        self._combo = combo

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(max(size.width(), _TEXT_X + 140), max(size.height(), 22))

    def paint(self, painter, option, index) -> None:
        from views.outliner import node_icon
        from views.layers_panel import layer_swatch
        style = option.widget.style() if option.widget else QApplication.style()
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, option, painter,
                            option.widget)
        name = index.data(_NAME)
        scene = self._combo.scene()
        ly = scene.layer(name) if (scene is not None and name) else None
        r = option.rect
        cy = r.top() + (r.height() - _GLYPH) // 2
        if ly is not None:
            node_icon("eye" if ly.visible else "eye_off").paint(
                painter, QRect(r.left() + _EYE_X, cy, _GLYPH, _GLYPH))
            node_icon("lock" if ly.locked else "lock_open").paint(
                painter, QRect(r.left() + _LOCK_X, cy, _GLYPH, _GLYPH))
            if ly.name != L.DEFAULT_LAYER:          # always on: nothing to do
                isolate_icon(L.is_isolated(scene, ly.name)).paint(
                    painter, QRect(r.left() + _ISO_X, cy, _GLYPH, _GLYPH))
            layer_swatch(ly).paint(
                painter, QRect(r.left() + _SWATCH_X, cy, _GLYPH, _GLYPH))
        font = option.font
        if ly is not None and L.active_layer(scene) == ly.name:
            font.setBold(True)
        painter.save()
        painter.setFont(font)
        selected = option.state & QStyle.State_Selected
        painter.setPen(option.palette.highlightedText().color() if selected
                       else option.palette.text().color())
        painter.drawText(r.adjusted(_TEXT_X, 0, -16, 0),
                         Qt.AlignVCenter | Qt.AlignLeft, str(name or ""))
        if name in getattr(self._combo, "selection_layers", ()):
            # What is selected sits on this layer.
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(option.palette.highlightedText().color()
                             if selected else
                             QApplication.palette().highlight().color())
            painter.drawEllipse(QRectF(r.right() - 12, r.center().y() - 3.5,
                                       7, 7))
        painter.restore()


class LayerCombo(QComboBox):
    """The layer drop-down of the Layers toolbar. See the module doc."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._filling = False
        self.setObjectName("layers_toolbar_combo")
        self.setMinimumContentsLength(14)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setIconSize(QSize(_TEXT_X - 8, _GLYPH))
        self.setToolTip(tr(
            "With something selected: its layer — pick another to move it "
            "there. With nothing selected: the active layer, where new "
            "objects go. In the list, each row's eye, padlock and target "
            "show, lock or isolate that layer."))
        self.setItemDelegate(_LayerDelegate(self))
        self.view().viewport().installEventFilter(self)
        self.activated.connect(self._on_activated)
        self.refresh()

    def scene(self):
        vp = getattr(self._window, "viewport", None)
        return getattr(vp, "scene", None)

    def panel(self):
        dock = getattr(self._window, "layers_dock", None)
        return getattr(dock, "panel", None)

    # ---- model → view ----
    def refresh(self) -> None:
        """Rows for the document's layers, showing the selection's layer
        (none when it spans several — the box then says so), or the active
        layer when nothing is selected."""
        scene = self.scene()
        if scene is None or self.view().isVisible():
            return                           # never under an open list
        self._filling = True
        # The selection's layers get a dot in the list (the box itself keeps
        # showing the active layer).
        self.selection_layers = L.selection_layers(scene)
        self.clear()
        for ly in scene.layers:
            self.addItem(_row_icon(ly, scene), ly.name)
            self.setItemData(self.count() - 1, ly.name, _NAME)
        current = self.selection_layers
        if not current:
            shown = L.active_layer(scene)
        elif len(current) == 1:
            shown = next(iter(current))
        else:
            shown = None
        self.setPlaceholderText(tr("(several)"))
        self.setCurrentIndex(self.findData(shown, _NAME) if shown else -1)
        self._filling = False

    def showPopup(self) -> None:
        """The list always drops down under the box (some styles centre it
        on the current row, which hides the toolbar); it goes up only when
        the screen has no room below."""
        super().showPopup()
        popup = self.view().window()
        screen = self.screen().availableGeometry()
        below = self.mapToGlobal(QPoint(0, self.height()))
        top = below.y()
        if top + popup.height() > screen.bottom():
            above = self.mapToGlobal(QPoint(0, 0)).y() - popup.height()
            top = above if above >= screen.top() else max(
                screen.top(), screen.bottom() - popup.height())
        popup.move(below.x(), top)

    # ---- view → model ----
    def _on_activated(self, index: int) -> None:
        if self._filling or index < 0:
            return
        name = self.itemData(index, _NAME)
        scene = self.scene()
        panel = self.panel()
        if scene is None or panel is None or not name:
            return
        picked = _taggable(scene.selection)
        if not picked:
            panel.set_active(name)
            self.refresh()
            return
        targets = [e for e in picked if L.layer_of(e) != name]
        if targets:
            from core.history import AssignLayerCommand
            self._window.viewport.history.execute(
                AssignLayerCommand(targets, name))
            self._window.viewport.notify_scene_changed()
        self._window.statusBar().showMessage(
            tr("{n} entities moved to '{layer}'", n=len(targets), layer=name),
            2500)
        self.refresh()

    def eventFilter(self, obj, event) -> bool:
        """A click on a row's eye, padlock or isolate mark acts on that
        layer and keeps the list open; anywhere else on the row picks the
        layer as usual."""
        if obj is self.view().viewport() and event.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            pos = event.position().toPoint()
            index = self.view().indexAt(pos)
            if index.isValid():
                x = pos.x() - self.view().visualRect(index).left()
                part = ("eye" if _EYE_X - 2 <= x < _EYE_X + _GLYPH + 2 else
                        "lock" if _LOCK_X - 2 <= x < _LOCK_X + _GLYPH + 2
                        else "isolate"
                        if _ISO_X - 2 <= x < _ISO_X + _GLYPH + 2
                        and index.data(_NAME) != L.DEFAULT_LAYER
                        else None)
                if part is not None:
                    if event.type() == QEvent.MouseButtonRelease:
                        self.toggle(index.data(_NAME), part)
                        self.view().viewport().update()
                    return True
        return super().eventFilter(obj, event)

    def toggle(self, name: str, part: str) -> None:
        scene = self.scene()
        panel = self.panel()
        ly = scene.layer(name) if scene is not None else None
        if ly is None or panel is None:
            return
        if part == "eye":
            panel.set_visible([name], not ly.visible)
        elif part == "lock":
            panel.set_locked([name], not ly.locked)
        elif part == "isolate":
            # The panel's target, the same rule: on the layer already shown
            # alone, back to what Isolate hid.
            panel.toggle_isolate([name])


def _row_icon(ly, scene) -> QIcon:
    """The closed box's icon: eye, padlock, isolate mark and swatch side by
    side, as in the list."""
    from views.outliner import node_icon
    from views.layers_panel import layer_swatch
    pm = QPixmap(_TEXT_X - 8, _GLYPH)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    icons = [(node_icon("eye" if ly.visible else "eye_off"), _EYE_X - 4),
             (node_icon("lock" if ly.locked else "lock_open"), _LOCK_X - 4),
             (layer_swatch(ly), _SWATCH_X - 4)]
    if ly.name != L.DEFAULT_LAYER:
        icons.append((isolate_icon(L.is_isolated(scene, ly.name)),
                      _ISO_X - 4))
    for icon, x in icons:
        icon.paint(p, QRect(x, 0, _GLYPH, _GLYPH))
    p.end()
    return QIcon(pm)


def _taggable(entities) -> list:
    return L.taggable(entities)


# ---- The toolbar -------------------------------------------------------------

class LayersToolbar:
    """Builds the Layers toolbar on ``window`` and keeps it current."""

    #: (key, label, tip) of the buttons after the drop-down, in order; a
    #: ``None`` is a separator. Short names: the tooltip's second line (the
    #: tip) says they act on the layer of what is selected. First the ones
    #: on the SELECTION's layer, then hide / show all / previous side by
    #: side: hiding and getting things back go together.
    BUTTONS = (
        ("make_active", "Make layer active",
         "The layer of what is selected becomes the active one: new "
         "objects go to it."),
        ("isolate", "Isolate layer",
         "Show only the layer of what is selected."),
        ("lock", "Lock layer",
         "Lock the layer of what is selected: still drawn, but out of "
         "reach."),
        ("to_active", "Move to active layer",
         "Move what is selected to the active layer."),
        None,
        ("hide", "Hide layer", "Hide the layer of what is selected."),
        ("show_all", "Show all layers", "Show every layer again."),
        ("previous", "Previous state",
         "Back to the layers' visibility, lock and active layer before the "
         "last change."),
    )

    def __init__(self, window, toolbar: QToolBar) -> None:
        self._window = window
        self.toolbar = toolbar
        self.actions: dict[str, QAction] = {}
        panel_act = QAction(toolbar_icon("panel"), tr("Layers panel"), window)
        panel_act.setStatusTip(tr("Open the Layers tab."))
        panel_act.setObjectName("layers_open_panel")
        panel_act.triggered.connect(self.open_panel)
        self._redraw_on_theme(panel_act, "panel")
        toolbar.addAction(panel_act)
        self.actions["panel"] = panel_act
        self.combo = LayerCombo(window)
        toolbar.addWidget(self.combo)
        for button in self.BUTTONS:
            if button is None:
                toolbar.addSeparator()
                continue
            key, label, tip = button
            act = QAction(toolbar_icon(key), tr(label), window)
            self._redraw_on_theme(act, key)
            act.setStatusTip(tr(tip))
            act.setObjectName(f"layers_{key}")
            act.triggered.connect(lambda _c=False, k=key: self.run(k))
            toolbar.addAction(act)
            self.actions[key] = act

    def _redraw_on_theme(self, act, key: str) -> None:
        """Into the window's list of drawn icons, so a light/dark switch or
        a new accent colour redraws these too."""
        icons = getattr(self._window, "_icon_actions", None)
        if icons is not None:
            icons.append((act, f"layers_{key}"))

    def _panel(self):
        return self._window.layers_dock.panel

    def open_panel(self) -> None:
        self._window.set_tray_shown(self._window.layers_dock, True)

    def _selection_layers(self) -> list:
        scene = self._window.viewport.scene
        return sorted({L.layer_of(e) for e in _taggable(scene.selection)})

    def run(self, key: str) -> None:
        """One button's work. The ones that need a selection say so in the
        status bar when nothing is selected."""
        panel = self._panel()
        status = self._window.statusBar()
        if key == "previous":
            panel.previous_state()
        elif key == "show_all":
            panel.show_all()
        elif key == "to_active":
            self._to_active()
        else:
            names = self._selection_layers()
            if not names:
                status.showMessage(
                    tr("Select something in the model first."), 3000)
                return
            if key == "make_active":
                if len(names) > 1:
                    status.showMessage(tr(
                        "The selection is on several layers: pick one."), 3000)
                    return
                panel.set_active(names[0])
            elif key == "isolate":
                panel.isolate(names)
            elif key == "hide":
                panel.set_visible(names, False)
            elif key == "lock":
                panel.set_locked(names, True)
        self.combo.refresh()

    def _to_active(self) -> None:
        from core.history import AssignLayerCommand
        scene = self._window.viewport.scene
        name = L.active_layer(scene)
        targets = [e for e in _taggable(scene.selection)
                   if L.layer_of(e) != name]
        if not _taggable(scene.selection):
            self._window.statusBar().showMessage(
                tr("Select something in the model first."), 3000)
            return
        if targets:
            self._window.viewport.history.execute(
                AssignLayerCommand(targets, name))
            self._window.viewport.notify_scene_changed()
        self._window.statusBar().showMessage(
            tr("{n} entities moved to '{layer}'", n=len(targets), layer=name),
            2500)

    def on_scene_changed(self) -> None:
        self.combo.refresh()
