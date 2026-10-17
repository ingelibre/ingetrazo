"""GO Structural Analysis v0.2.4 — IngeTrazo Plugin API v2 entry point."""
def setup(app):
    from .ui import setup as create_panel
    return create_panel(app)
__version__='0.2.4'
