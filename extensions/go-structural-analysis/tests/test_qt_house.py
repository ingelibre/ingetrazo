import pytest
pytest.importorskip('PySide6')
from test_qt_v02 import panel,qtapp
from go_structural_analysis.model3d import cantilever3d
from PySide6.QtGui import QImage,QPainter,QColor

def test_house_catalog_and_model_load_visibility(panel):
    assert panel.examples.findData('3d_house_phetnaray')>=0
    panel.put(cantilever3d()); panel.diagram.setCurrentText('Model')
    panel.tabs.setCurrentIndex(0); panel.labels.setChecked(False)
    def render():
        image=QImage(1000,700,QImage.Format.Format_ARGB32); image.fill(QColor('white'))
        painter=QPainter(image)
        try: panel.paint(panel.app.viewport,painter)
        finally: painter.end()
        return image
    panel.show_loads.setChecked(False); clean=render()
    panel.show_loads.setChecked(True); with_loads=render()
    assert clean!=with_loads
    panel.show_loads.setChecked(False); panel.tabs.setCurrentIndex(1)
    assert render()==with_loads
