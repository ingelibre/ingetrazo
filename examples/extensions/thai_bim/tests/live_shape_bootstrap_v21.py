"""Run via the IngeTrazo AI bridge; all model work in an isolated native scene."""
import copy,json,sys,importlib,math
from pathlib import Path
from core.extensions import _import_by_path,user_plugins_dir
from core.history import History
from core.scene import Scene
from formats.igz import load_into
from PySide6.QtWidgets import QMainWindow,QDockWidget,QApplication,QPushButton
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtGui import QMatrix4x4
from views.viewport import Viewport
from views.composer import ComposerWindow
from core.composition import TextoItem,Composicion
root21=Path(__file__).resolve().parents[1];out21=root21/'verification-local';out21.mkdir(exist_ok=True)
for name in list(sys.modules):
 if name.startswith('ingetrazo_plugin_thai_bim'):sys.modules.pop(name,None)
tb21=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import workflow as W21,builders as B21,management as M21,steel as C21,slab_ui as SL21,slab_rebar as SR21,stairs_ui as SU21,stair_drawings as SD21,member_drawings as MD21,member_drawing_geometry as MG21,drawings as D21,engine as EN21
checks21=[];actual21=[(g.uid,g.name,tb21.mesh_fingerprint(g)) for g in scene.groups];actual_selection21={g.uid for g in scene.selection}
def check21(name,result):
 assert result,name;checks21.append(name);(out21/'live-checks.json').write_text(json.dumps(dict(version=EN21.VERSION,passed=checks21),ensure_ascii=False,indent=2),encoding='utf8')
def reject21(name,fn):
 try:fn()
 except ValueError:check21(name,True);return
 raise AssertionError(name+' failed to reject')
def settle21():
 loop=QEventLoop();QTimer.singleShot(210,loop.quit);loop.exec()
class App21:
 api_version=2
 def __init__(self):
  self.window=QMainWindow();self.window.resize(1000,700);self.viewport=Viewport(self.window);self.window.setCentralWidget(self.viewport);self.window.viewport=self.viewport;self.window._current_path=None
  self.window._ensure_composer=self.ensure_composer;self.window._refresh_sheet_tabs=lambda:None
 def ensure_composer(self):
  if not hasattr(self.window,'_composer'):self.window._composer=ComposerWindow(self.window)
  return self.window._composer
 @property
 def scene(self):return self.viewport.scene
 def document_data(self,default):return default
 def on_document_changed(self,fn):self.viewport.sceneVersionChanged.connect(lambda version:fn())
 def add_panel(self,title,widget):d=QDockWidget(title,self.window);d.setWidget(widget);return d
 def add_menu_action(self,*args,**kwargs):pass
 def add_overlay(self,fn):self.viewport._ext_overlays.append(fn)
 def add_snap_provider(self,fn):self.viewport._ext_snap_providers.append(fn)
 def world_to_pixels(self,points):return self.viewport.world_to_pixels(points)
app21=App21();ss21=app21.scene;sp21=tb21.setup(app21);sp21.guard=lambda fn:fn();app21.window.show();settle21()

from ingetrazo_plugin_thai_bim import shape_geometry as SG21,shape_edit as SH21,path_geometry as PG21,selected_geometry as SE21,stairs as ST21
print('READY',EN21.VERSION)
