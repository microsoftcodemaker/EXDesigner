"""GUI layer (PySide6, optional extra ``gui``). Views hold no logic; view-models are plain Python.

Nothing here is imported by ``app``, ``modules`` or ``core``. This package must stay
importable without PySide6 installed (only ``dfr.ui.shell`` and ``dfr.ui.kit`` may import Qt).
"""
