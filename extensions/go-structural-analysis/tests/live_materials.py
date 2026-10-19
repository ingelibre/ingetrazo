"""Live editor checks; no data is written into the user's document."""
import copy
import importlib
import json
from pathlib import Path

def verify_materials(viewport):
    p=viewport.window()._go_structural_panel
    if p.thread is not None: raise RuntimeError('Wait for analysis')
    ui=importlib.reload(importlib.import_module(p.__module__))
    original=copy.deepcopy(p.app.scene.plugin_data)
    out=Path.home()/'Projects/ingecad/extensions/go-structural-analysis/artifacts/materials'
    out.mkdir(parents=True,exist_ok=True)
    editor=ui.Editor(ui.benchmark(),p)
    checks=[]
    try:
        for name in ['Concrete','Aluminium','Wood']:
            editor.material_presets.setCurrentText(name); editor.add_material_button.click()
            checks.append({'check':name+'_row','status':'Passed' if editor.tables['materials'].rowCount()==len(checks)+2 else 'Failed'})
        table=editor.tables['materials']; table.item(1,1).setText('31000000')
        editor.material_presets.setCurrentText('Concrete'); editor.add_material_button.click()
        checks.append({'check':'no_duplicate_or_overwrite','status':'Passed' if table.rowCount()==4 and table.item(1,1).text()=='31000000' else 'Failed'})
        combo=editor.tables['members'].cellWidget(0,ui.FIELDS['members'].index('material'))
        names=[combo.itemText(i) for i in range(combo.count())]
        checks.append({'check':'member_material_choices','status':'Passed' if names==['Steel','Concrete','Aluminium','Wood'] else 'Failed','choices':names})
        combo.setCurrentText('Wood'); editor.tabs.setCurrentIndex(list(ui.FIELDS).index('materials')); editor.show()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents(); editor.grab().save(str(out/'materials-editor.png'))
        editor.accept_model()
        checks.append({'check':'editor_validation','status':'Passed' if editor.data['members'][0]['material']=='Wood' and len(editor.data['materials'])==4 else 'Failed'})
        legacy=ui.Editor(ui.benchmark(),p); legacy.accept_model()
        checks.append({'check':'legacy_roundtrip','status':'Passed' if legacy.data==ui.benchmark() else 'Failed'}); legacy.deleteLater()
    finally:
        editor.close(); editor.deleteLater()
        checks.append({'check':'original_document_preserved','status':'Passed' if p.app.scene.plugin_data==original else 'Failed'})
        (out/'live-results.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    return checks
