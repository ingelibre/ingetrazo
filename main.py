"""IngeTrazo entry point.

Free 3D modeler for architecture, civil engineering, and 3D printing.
Part of the IngePresupuestos ecosystem (modeling → quantity takeoff → budget).

Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
Licensed under GPL-3.0-or-later. See LICENSE.
"""
from __future__ import annotations

import sys

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from views.main_window import MainWindow


def _configure_surface_format() -> None:
    """Request an OpenGL 3.3 Core context with an explicit 24-bit depth buffer.

    Without this, hidden-line removal silently degrades: some platforms hand
    QOpenGLWidget a context with no (or 16-bit) depth buffer, and faces stop
    occluding back-facing edges.
    """
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)  # 4× MSAA — smooths thin edge lines without hurting depth
    QSurfaceFormat.setDefaultFormat(fmt)


def main() -> int:
    _configure_surface_format()
    app = QApplication(sys.argv)
    app.setApplicationName("IngeTrazo")
    app.setOrganizationName("IngeTrazo")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
