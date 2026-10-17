"""Refresh the existing toolbar entry without adding duplicate actions or geometry."""
realpanel21=viewport.window()._thai_bim_panel
actions21=[a for a in realpanel21.toolbar.actions() if 'Instance dimensions' in a.text()]
assert len(actions21)==1
actions21[0].triggered.disconnect();actions21[0].triggered.connect(lambda checked=False:realpanel21.guard(lambda:UI21.open_dialog(realpanel21)))
for b in realpanel21.findChildren(QPushButton):
 if 'Instance dimensions' in b.text():
  b.clicked.disconnect();b.clicked.connect(lambda checked=False:realpanel21.guard(lambda:UI21.open_dialog(realpanel21)))
if realpanel21.parentWidget():realpanel21.parentWidget().setWindowTitle('Thai BIM 0.21')
check21('Existing real toolbar refreshed without duplicate selected-edit icons',len(actions21)==1)
check21('User model untouched by toolbar refresh',actual21==[(g.uid,g.name,tb21.mesh_fingerprint(g)) for g in scene.groups] and actual_selection21=={g.uid for g in scene.selection})
print('INSTALLED',EN21.VERSION,len(checks21),'checks')
