"""Bootstrap isolated native stair sheets and first end-to-end PDF."""
import importlib,copy,json,math
from pathlib import Path
from core.composition import TextoItem,Composicion
from views.composer import ComposerWindow
from ingetrazo_plugin_thai_bim import stairs as ST15,engine as EN19,stairs_ui as SU19,stair_drawings as SD19,stair_drawing_geometry as DG19
EN19=importlib.reload(EN19);DG19=importlib.reload(DG19);SD19=importlib.reload(SD19);SU19=importlib.reload(SU19)
out19=root07/'verification-local';out19.mkdir(exist_ok=True);actual19=(list(scene.groups),scene.version,set(scene.selection));checks19=[]
def check19(name,value):
 assert value,name;checks19.append(name);(out19/'stair-drawing-checks.json').write_text(json.dumps(dict(version=EN19.VERSION,passed=checks19),ensure_ascii=False,indent=2),encoding='utf8')
def reject19(name,fn):
 try:fn()
 except ValueError:check19(name,True);return
 raise AssertionError(name+' did not reject')
sa19=App07();sw19=sa19.window;sw19.viewport=sa19.viewport;sw19._current_path=None
sw19._ensure_composer=lambda:sw19._composer if hasattr(sw19,'_composer') else createComposer19()
def createComposer19():
 sw19._composer=ComposerWindow(sw19);return sw19._composer
sw19._refresh_sheet_tabs=lambda:None
ss19=sa19.scene;sp19=tb07.setup(sa19);sp19.guard=lambda fn:fn();sw19.show();settle07()
sc19=SU19.open_dialog(sp19,False);sc19.create();host19=sc19.host();sc19.review();sc19.build_rebar()
user19=Composicion(name='Unrelated user sheet');ss19.compositions.append(user19)
sd19=SD19.open_dialog(sp19);check19('native stair drawing dialog opens without overriding QWidget.show',sd19.isVisible())
sd19.fields['name'].setText('Thai BIM Stair synthetic');sd19.prepare();sd19.build();parts19,meta19=SD19.validate(ss19,host19.uid)
check19('native plan sections bar details and BBS pages all created',len(parts19)>4 and any(r['title']=='BBS' for r in meta19['sheets']) and user19 in ss19.compositions)
check19('native drawing preview contains generated lines',sd19.preview.comp is not None and len(sd19.preview.comp.shapes)>20)
sd19.grab().save(str(out19/'stair-drawing-dialog.png'))
SD19.export_pdf(sp19,host19.uid,out19/'stair-Straight-A3-50.pdf');SD19.export_bbs(ss19,host19.uid,out19/'stair-Straight-BBS.xlsx')
check19('native multi-page PDF and actual-cage BBS XLSX export complete',(out19/'stair-Straight-A3-50.pdf').stat().st_size>1000 and (out19/'stair-Straight-BBS.xlsx').stat().st_size>1000)
M07.compact_save(ss19,out19/'stair-drawing-Straight.igz')
print('PASS bootstrap '+str(len(checks19))+' checks / '+str(len(parts19))+' sheets / '+EN19.VERSION)
