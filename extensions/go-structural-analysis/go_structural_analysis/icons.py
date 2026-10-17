"""Small vector-style Qt icons; no external assets or font dependencies."""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QPalette, QGuiApplication

def pixmap(name='extension',size=32):
    app=QGuiApplication.instance(); palette=app.palette() if app else QPalette()
    dark=palette.color(QPalette.ColorRole.Window).lightness()<128
    image=QPixmap(size,size); image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.scale(size/32,size/32)
    p.setPen(QPen(palette.color(QPalette.ColorRole.ButtonText),1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    if name=='extension':
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor('#253b3a' if dark else '#def0eb')); p.drawRoundedRect(QRectF(1,1,30,30),8,8)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor('#8cddd0' if dark else '#21665a'),1.8))
        for a,b in [((6,23),(16,8)),((16,8),(26,23)),((6,23),(26,23)),((6,23),(21,15.5)),((11,15.5),(26,23)),((11,15.5),(21,15.5))]: p.drawLine(QPointF(*a),QPointF(*b))
        p.setBrush(QColor('#d8faf3' if dark else '#21665a'))
        for x,y in [(6,23),(16,8),(26,23)]: p.drawEllipse(QPointF(x,y),1.8,1.8)
    elif name=='nodes':
        for a,b in [((8,23),(15,7)),((15,7),(25,17)),((8,23),(25,17)),((8,23),(21,26))]: p.drawLine(QPointF(*a),QPointF(*b))
        for x,y in [(8,23),(15,7),(25,17),(21,26)]: p.drawEllipse(QPointF(x,y),2.8,2.8)
    elif name=='members':
        p.drawLine(7,24,25,6); p.drawLine(5,21,22,4); p.drawLine(10,27,28,9); p.drawLine(5,21,10,27); p.drawLine(22,4,28,9)
        for i in [10,14,18,22]: p.drawLine(i,26-i,i+3,29-i)
    elif name=='sections':
        for y in [9,23]: p.drawLine(6,y,26,y)
        p.drawLine(15,9,15,23); p.drawLine(18,9,18,23); p.drawLine(6,12,26,12); p.drawLine(6,20,26,20)
    elif name=='supports':
        p.drawEllipse(QPointF(16,7),3,3); p.drawLine(16,10,16,25); p.drawArc(QRectF(5,11,22,17),180*16,180*16); p.drawLine(5,16,5,21); p.drawLine(27,16,27,21)
    elif name=='materials':
        p.drawRect(QRectF(7,7,18,18)); p.drawLine(7,13,25,13); p.drawLine(7,19,25,19); p.drawLine(13,7,13,13); p.drawLine(19,13,19,19); p.drawLine(13,19,13,25)
    elif name in ('point','distributed'):
        for x in ([16] if name=='point' else [7,16,25]):
            p.drawLine(x,5,x,22); p.drawLine(x,22,x-4,17); p.drawLine(x,22,x+4,17)
        p.drawLine(5,27,27,27)
    elif name=='run':
        p.drawEllipse(QPointF(16,16),11,11); p.drawLine(13,10,22,16); p.drawLine(22,16,13,22); p.drawLine(13,22,13,10)
    elif name=='save':
        p.drawRoundedRect(QRectF(6,5,20,23),2,2); p.drawRect(QRectF(11,5,10,8)); p.drawRect(QRectF(11,19,10,9))
    elif name=='workspace':
        p.drawRoundedRect(QRectF(4,5,24,23),3,3); p.drawLine(4,11,28,11); p.drawLine(12,11,12,28)
    elif name=='back':
        p.drawLine(26,16,6,16); p.drawLine(6,16,13,9); p.drawLine(6,16,13,23)
    else:
        p.drawRoundedRect(QRectF(7,5,18,23),2,2)
        for y in [11,16,21]: p.drawLine(11,y,21,y)
    p.end(); return image

def icon(name='extension'): return QIcon(pixmap(name,64))
