"""Repeat v19 stair sheet lifecycle with the shared v20 sheet backend."""
from PySide6.QtCore import Qt,QEvent,QPointF
from PySide6.QtGui import QMouseEvent,QKeyEvent
class NativeEvents07:
 @staticmethod
 def mouseClick(widget,button,modifiers,point):
  for event,buttons in ((QEvent.MouseButtonPress,button),(QEvent.MouseButtonRelease,Qt.NoButton)):
   QApplication.sendEvent(widget,QMouseEvent(event,QPointF(point),QPointF(widget.mapToGlobal(point)),button,buttons,modifiers))
root07=root20;App07=App20;tb07=tb20;W07=W20;B07=B20;M07=M20;C07=C20;settle07=settle20
for name20 in ('live_stair_drawings_v19.py','live_stair_sheet_lifecycle_v19.py','live_stair_sheet_forms_v19.py','live_stair_sheet_guards_v19.py'):
 text20=(root20/'tests'/name20).read_text(encoding='utf-8-sig').replace("root07/'thai_bim/verification-v19'","out20")
 exec(compile(text20,name20,'exec'))
for description20 in checks19:check20('Repeated stair: '+description20,True)
print('PASS',len(checks19),'repeated stair sheet checks;',len(checks20),'total native checks')
