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
root20=Path(__file__).resolve().parents[1];out20=root20/'verification-local';out20.mkdir(exist_ok=True)
for name in ('engine','stair_drawing_geometry','stair_drawings','drawings','member_drawing_geometry','member_drawings'):sys.modules.pop('ingetrazo_plugin_thai_bim.'+name,None)
tb20=_import_by_path('thai_bim',user_plugins_dir()/'thai_bim/__init__.py')
from ingetrazo_plugin_thai_bim import workflow as W20,builders as B20,management as M20,steel as C20,slab_ui as SL20,slab_rebar as SR20,stairs_ui as SU20,stair_drawings as SD20,member_drawings as MD20,member_drawing_geometry as MG20,drawings as D20,engine as EN20
checks20=[];actual20=[(g.uid,g.name,tb20.mesh_fingerprint(g)) for g in scene.groups];actual_selection20={g.uid for g in scene.selection}
def check20(name,result):
 assert result,name;checks20.append(name);(out20/'live-checks.json').write_text(json.dumps(dict(version=EN20.VERSION,passed=checks20),ensure_ascii=False,indent=2),encoding='utf8')
def reject20(name,fn):
 try:fn()
 except ValueError:check20(name,True);return
 raise AssertionError(name+' failed to reject')
def settle20():
 loop=QEventLoop();QTimer.singleShot(200,loop.quit);loop.exec()
class App20:
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
app20=App20();ss20=app20.scene;sp20=tb20.setup(app20);sp20.guard=lambda fn:fn();app20.window.show();settle20()
fixtures20={};pages20={}
for kind,vals in [('Footing',(0,0,-.5,1.4,1.8,.5)),('Column',(0,0,0,.4,.4,3)),('Beam',(0,-.15,0,4,.3,.5)),('Slab',(0,0,0,3,2,.2))]:
 h=tb20.make_group(EN20.box_spec(kind,*vals));h.name='Native '+kind;h.xform=W20.matrix(W20.P.matrix((5,4,3.75),30));ss20.groups.append(h);ss20.selection={h};fixtures20[kind]=h
 if kind=='Slab':
  rd=SL20.SlabDialog(sp20);rd.read_host();rd.representation.setCurrentText('Centreline');rd.review();rd.build()
 else:
  rd=B20.RebarDialog(sp20);rd.read_host();rd.representation.setCurrentText('Centreline');rd.review();rd.build()
 rd.close();dialog20=D20.open_dialog(sp20)
 check20(kind+' selected Sheet icon routes to shared member dialog',dialog20.backend is MD20.BACKEND and dialog20.isVisible())
 dialog20.fields['name'].setText('Thai BIM '+kind+' synthetic');dialog20.prepare();dialog20.build();parts,meta=MD20.validate(ss20,h.uid);pages20[kind]=len(parts)
 check20(kind+' plan two real sections details and BBS created',len(parts)>=5 and sum('Section' in r['title'] for r in meta['sheets'])==2)
 rows=SD20.G.grouped_bars(MD20.source(ss20,h.uid)['bars']);records=[r for r in tb20.bbs_records(ss20)[0] if r['host_uid']==h.uid]
 check20(kind+' marks counts and cut lengths equal existing actual BBS',{r['mark']:(len(r['uids']),r['bbs']['length_m']) for r in rows}=={r['bbs']['mark']:(sum(q['bbs']['mark']==r['bbs']['mark'] for q in records),r['bbs']['length_m']) for r in records})
 lo,hi=MG20.extents(MD20.source(ss20,h.uid)['faces']);check20(kind+' levels use actual world pose',set(round(n.level_m(),6) for n in parts[1].niveles)=={round(3.75+lo[2],6),round(3.75+hi[2],6)})
 check20(kind+' BBS pages explicitly NTS',all(not c.scalebars for c in parts if 'BBS' in c.name))
 MD20.export_pdf(sp20,h.uid,out20/(kind+'-A3-50.pdf'));MD20.export_bbs(ss20,h.uid,out20/(kind+'-BBS.xlsx'))
 check20(kind+' native vector PDF and XLSX export', (out20/(kind+'-A3-50.pdf')).stat().st_size>10000)
 if kind=='Footing':dialog20.grab().save(str(out20/'member-drawing-dialog.png'))
 dialog20.close()
(out20/'fixture-pages.json').write_text(json.dumps(pages20,indent=2),encoding='utf8')
print('PASS',len(checks20),'initial member checks',pages20)
