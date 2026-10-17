"""Native mouse/keyboard placement, host review, rigid BBS and Undo in isolated scenes."""
import copy,json,sys
from pathlib import Path
from core.extensions import _import_by_path,user_plugins_dir
from core.scene import Scene
from core.history import History,MoveGroupCommand,RotateGroupCommand
from core.group import world_mesh
from formats.igz import save_scene,load_into
from formats.gltf import save_glb
from PySide6.QtWidgets import QMainWindow,QDockWidget,QLabel,QApplication
from PySide6.QtCore import Qt,QEvent,QEventLoop,QTimer,QPoint,QPointF
from PySide6.QtGui import QVector3D,QAction,QMouseEvent,QKeyEvent
from tools.base import ToolContext
from tools.select import SelectTool
from core.snap import SnapResult
from views.viewport import Viewport

root07=Path(__file__).resolve().parents[1]
out07=root07/'verification-local';out07.mkdir(exist_ok=True)
for suffix in ('engine','visuals','structures','builders','detailing','placement','workflow','steel','management','audit','drawings','drawing_layout'):sys.modules.pop('ingetrazo_plugin_thai_bim.'+suffix,None)
tb07=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import workflow as W07,builders as B07,management as M07,steel as C07,audit as A071
checks07=[];actual07=(list(scene.groups),scene.version,set(scene.selection))
def check07(name,value):
    assert value,name;checks07.append(name)
    (out07/'live-checks.json').write_text(json.dumps(dict(version=tb07.E.VERSION,passed=checks07),indent=2),encoding='utf-8')
def rejects07(name,fn):
    try:fn()
    except ValueError:check07(name,True);return
    raise AssertionError(name+' did not reject')
def settle07():
    loop=QEventLoop();QTimer.singleShot(250,loop.quit);loop.exec()
class NativeEvents07:
    # The installed app omits QtTest; dispatch actual Qt events through QApplication.
    @staticmethod
    def mouseMove(widget,point):
        QApplication.sendEvent(widget,QMouseEvent(QEvent.MouseMove,QPointF(point),QPointF(widget.mapToGlobal(point)),Qt.NoButton,Qt.NoButton,Qt.NoModifier))
    @staticmethod
    def mouseClick(widget,button,modifiers,point):
        for event,buttons in [(QEvent.MouseButtonPress,button),(QEvent.MouseButtonRelease,Qt.NoButton)]:
            QApplication.sendEvent(widget,QMouseEvent(event,QPointF(point),QPointF(widget.mapToGlobal(point)),button,buttons,modifiers))
    @staticmethod
    def keyClick(widget,key):
        QApplication.sendEvent(widget,QKeyEvent(QEvent.KeyPress,int(key),Qt.NoModifier,'r' if key==Qt.Key_R else ''))
        QApplication.sendEvent(widget,QKeyEvent(QEvent.KeyRelease,int(key),Qt.NoModifier))
# Reuse the current panel; retain the original document/overlay callbacks.
panel07=viewport.window()._thai_bim_panel;old07=panel07.create_member.__func__.__globals__
for name in ['E','make_group','mesh_fingerprint','quantity_rows','identity_issues','roof_update','NormalizeColors','MultiRoofDialog','CutDialog','roof_planes_from_groups','multi_roof_update','cutting_runs']:old07[name]=getattr(tb07,name)
old07.update(ExchangeGroups=tb07.ExchangeGroups)
for method in ('create_member','update_member','execute'):getattr(panel07,method).__func__.__code__=getattr(tb07.Panel,method).__code__
bg07=panel07.open_builder.__globals__
for name in ('RoofDialog','StairDialog','RebarDialog'):bg07[name]=getattr(B07,name)
bg07.update(S=B07.S,D=B07.D,E=tb07.E,open_bbs=B07.open_bbs)
for dialog07 in panel07.builder_dialogs.values():dialog07.hide();dialog07.deleteLater()
panel07.builder_dialogs={};B07.add_tools(panel07);W07.install(panel07);M07.install(panel07);A071.install(panel07);panel07.dock.setWindowTitle(tb07.TITLE)
panel07.grid_columns.__func__.__code__=tb07.Panel.grid_columns.__code__
wg07=panel07.workflow.refresh.__func__.__globals__
for name in ('E','P','D','S','host_token','host_notices','bar_unchanged','host_matches','bar_specs','review_specs','placement_of','placed_member_command','PlacementDialog','PlacementTool'):
    wg07[name]=getattr(W07,name)

class App07:
    api_version=2
    def __init__(self):
        self.window=QMainWindow();self.window.setWindowTitle('Thai BIM isolated verification');self.window.resize(960,700)
        self.viewport=Viewport(self.window);self.window.setCentralWidget(self.viewport);self.callbacks=[]
    @property
    def scene(self):return self.viewport.scene
    def document_data(self,default):return getattr(self,'project_data',default)
    def on_document_changed(self,fn):self.callbacks.append(fn);self.viewport.sceneVersionChanged.connect(lambda version:fn())
    def add_panel(self,title,widget):d=QDockWidget(title,self.window);d.setWidget(widget);return d
    def add_menu_action(self,*args,**kwargs):pass
    def add_overlay(self,fn):self.viewport._ext_overlays.append(fn)
    def add_snap_provider(self,fn):self.viewport._ext_snap_providers.append(fn)
    def world_to_pixels(self,points):return self.viewport.world_to_pixels(points)
checks07=json.loads((out07/'live-checks.json').read_text(encoding='utf-8'))['passed']
