"""Slab systems, polygon sections, physical scales and native source guards."""
from ingetrazo_plugin_thai_bim import path_geometry as PG20
for mode20 in ('Two-way','Precast','Polygon'):
 if mode20=='Polygon':spec20,pose20=PG20.polygon([(0,0),(3,0),(3,1),(1,1),(1,3),(0,3)],3.75,dict(height=.2))
 else:spec20=EN20.box_spec('Slab',0,0,0,3,2,.2);pose20=W20.P.matrix((10,4,3.75),45)
 h20=tb20.make_group(spec20);h20.name='Native Slab '+mode20;h20.xform=W20.matrix(pose20);ss20.groups.append(h20);ss20.selection={h20};fixtures20['Slab-'+mode20]=h20
 rd20=SL20.SlabDialog(sp20);rd20.read_host();rd20.mode.setCurrentText('One-way' if mode20=='Polygon' else mode20)
 if mode20=='Precast':rd20.dowels.setChecked(True)
 rd20.review();rd20.build();rd20.close();d20=MD20.open_dialog(sp20);d20.fields['name'].setText('Thai BIM Slab '+mode20+' synthetic');d20.prepare();d20.build()
 parts20,meta20=MD20.validate(ss20,h20.uid);check20('Slab '+mode20+' actual cage sections and detail sheets created',len(parts20)>4)
 bars20=MD20.source(ss20,h20.uid)['bars'];rows20=SD20.G.grouped_bars(bars20);existing20=[b for b in tb20.bbs_records(ss20)[0] if b['host_uid']==h20.uid]
 check20('Slab '+mode20+' drawing marks exactly equal existing BBS',{r['mark']:len(r['uids']) for r in rows20}=={r['bbs']['mark']:sum(q['bbs']['mark']==r['bbs']['mark'] for q in existing20) for r in existing20})
 if mode20=='Precast':check20('precast mesh and end-dowel roles retained',any('dowel' in b['role'].lower() for b in bars20) and any('mesh' in b['role'].lower() for b in bars20))
 if mode20=='Polygon':check20('native concave slab plan has true reentrant corner',any(abs(s.w_mm)<.001 and s.h_mm>0 for s in parts20[0].shapes))
 MD20.export_pdf(sp20,h20.uid,out20/('Slab-'+mode20+'-A3-50.pdf'));MD20.export_bbs(ss20,h20.uid,out20/('Slab-'+mode20+'-BBS.xlsx'));pages20['Slab-'+mode20]=len(parts20)
 d20.close()
# Re-export original four with the final dimension placement.
for kind20 in ('Footing','Column','Beam','Slab'):
 h20=fixtures20[kind20];ss20.selection={h20};d20=MD20.open_dialog(sp20);d20.prepare();d20.build()
 if any(r['reasons'] for r in MD20.status(ss20,h20.uid)):d20.acknowledge()
 MD20.export_pdf(sp20,h20.uid,out20/(kind20+'-A3-50.pdf'));MD20.export_bbs(ss20,h20.uid,out20/(kind20+'-BBS.xlsx'))
 if kind20=='Footing':d20.grab().save(str(out20/'member-drawing-dialog.png'))
 d20.close()
h20=fixtures20['Footing'];ss20.selection={h20};d20=MD20.open_dialog(sp20)
for scale20 in (20,25):
 d20.scale.setCurrentText(str(scale20));d20.prepare();d20.build();d20.acknowledge();parts20,_=MD20.validate(ss20,h20.uid)
 check20('native member physical scale '+str(scale20),any(abs(c.real_distance_m()-1.4)<1e-6 for c in parts20[0].cotas))
 MD20.export_pdf(sp20,h20.uid,out20/('Footing-scale-'+str(scale20)+'-A3.pdf'))
d20.scale.setCurrentText('50');d20.prepare();d20.build();d20.acknowledge();d20.close()
M20.compact_save(ss20,out20/'members-drawings-ไทย.igz');round20=Scene();load_into(round20,out20/'members-drawings-ไทย.igz')
check20('all seven member sets current after native IGZ Unicode roundtrip',all(not any(r['reasons'] for r in MD20.status(round20,h.uid)) for h in fixtures20.values()))
check20('member tools retain existing 21 toolbar actions',len(sp20.toolbar.actions())==21)
check20('member workflows preserve user document geometry and selection',actual20==[(g.uid,g.name,tb20.mesh_fingerprint(g)) for g in scene.groups] and actual_selection20=={g.uid for g in scene.selection})
(out20/'fixture-pages.json').write_text(json.dumps(pages20,indent=2),encoding='utf8')
print('PASS',len(checks20),'member checks',pages20)
