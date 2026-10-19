"""Run after live_thai_bim_v071 and optional full-project script in the native bridge."""
from PySide6.QtWidgets import QTabWidget,QScrollArea
from core.layers import Layer
from ingetrazo_plugin_thai_bim import audit as auditui071,management as managerui071
uiapp071=App07();uipanel071=tb07.setup(uiapp071)
reportui071=auditui071.open_audit(uipanel071)
check07('native audit dialog has four readable report tabs',reportui071.findChild(QTabWidget).count()==4)
reportui071.hide()
uiapp071.scene.layers.extend(Layer('TBIM S test '+str(i)) for i in range(40))
layerui071=managerui071.open_manager(uipanel071);settle07()
scrollui071=layerui071.findChild(QScrollArea)
check07('whole-project layer dialog scrolls long layer list',scrollui071 is not None and scrollui071.verticalScrollBar().maximum()>0)
layerui071.hide();uiapp071.window.deleteLater();settle07()
from core import units as unitsui071
unitsui071.bind_scene(scene)
