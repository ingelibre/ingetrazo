"""Use IngeTrazo's palette and live stylesheet registry; never set a host theme."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QLabel, QAbstractButton
from .icons import icon, pixmap

STYLE='''
QWidget#goRibbon { background: palette(window); color: palette(window-text); border: 1px solid palette(mid); border-radius: 7px; font-family: "Segoe UI"; font-size: 12px; }
QWidget#goRibbon QToolButton { color: palette(button-text); background: palette(button); border: 1px solid palette(mid); border-radius: 5px; padding: 5px; }
QWidget#goRibbon QToolButton:hover { border-color: palette(highlight); }
QWidget#goRibbon QToolButton:disabled { color: palette(mid); }
QWidget#goPanel, QDialog#goEditor { background: palette(window); color: palette(window-text); font-family: "Segoe UI"; font-size: 13px; }
QLabel { color: palette(window-text); background: transparent; }
QLabel#goTitle { font-size: 16px; font-weight: 700; }
QLabel#goBadge { background: palette(base); border-radius: 10px; padding: 3px 9px; color: palette(window-text); font-weight: 600; }
QLabel#goMuted { color: MUTED_COLOR; font-size: 11px; }
QLabel#goStatus { color: MUTED_COLOR; font-size: 11px; padding: 4px 0; }
QLabel#goSection { font-weight: 600; padding-top: 4px; }
QTabWidget::pane { border: none; }
QTabBar::tab { color: MUTED_COLOR; background: palette(window); padding: 10px 19px; border-radius: 17px; font-weight: 600; }
QTabBar::tab:selected { background: palette(base); color: palette(window-text); }
QTabBar::tab:hover { color: palette(window-text); }
QScrollArea { border: none; background: palette(window); }
QWidget#goPage { background: palette(window); }
QRadioButton { color: palette(window-text); spacing: 10px; padding: 6px 0; }
QRadioButton::indicator { width: 19px; height: 19px; border: 1px solid palette(mid); border-radius: 10px; background: palette(window); }
QPushButton, QToolButton { color: palette(button-text); background: palette(button); border: 1px solid palette(mid); border-radius: 9px; padding: 9px; }
QPushButton:hover, QToolButton:hover { background: palette(midlight); border-color: palette(highlight); }
QPushButton:disabled { color: MUTED_COLOR; background: palette(window); }
QPushButton#goCard { text-align: left; background: palette(base); border: 1px solid palette(mid); border-radius: 11px; padding: 13px; min-height: 70px; }
QPushButton#goCard:hover { background: palette(alternate-base); border-color: palette(highlight); }
QPushButton#goRun { min-height: 28px; font-weight: 600; background: palette(base); }
QComboBox, QDoubleSpinBox, QPlainTextEdit, QTableWidget { background: palette(base); color: palette(text); border: 1px solid palette(mid); border-radius: 7px; padding: 6px; selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }
QComboBox QAbstractItemView { color: palette(text); background: palette(base); selection-background-color: palette(highlight); selection-color: palette(highlighted-text); }
QHeaderView::section { background: palette(button); color: palette(button-text); border: none; padding: 7px; }
QTableWidget { alternate-background-color: palette(alternate-base); gridline-color: palette(mid); }
QCheckBox { color: palette(window-text); spacing: 8px; }
QScrollBar:vertical { background: palette(window); width: 7px; }
QScrollBar::handle:vertical { background: palette(mid); border-radius: 3px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
'''

def apply_style(widget):
    from views.theme import style
    # The host uses str.format: escape QSS braces, preserving its muted token.
    template=STYLE.replace('{','{{').replace('}','}}').replace('MUTED_COLOR','{muted}')
    style(widget,template)

class ThemeAware:
    def changeEvent(self,event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.ApplicationPaletteChange,QEvent.Type.PaletteChange,QEvent.Type.ThemeChange):
            self.refresh_theme_icons()
    def refresh_theme_icons(self):
        self.setWindowIcon(icon())
        for label in self.findChildren(QLabel):
            key=label.property('go_icon')
            if key: label.setPixmap(pixmap(str(key),int(label.property('go_icon_size') or 21)))
        for button in self.findChildren(QAbstractButton):
            key=button.property('go_icon')
            if key: button.setIcon(icon(str(key)))
        for name in ('menu_action','dock'):
            obj=getattr(self,name,None)
            if obj is not None:
                if name=='dock': obj.setWindowIcon(icon())
                else: obj.setIcon(icon())
