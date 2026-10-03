"""
Makes `game` importable as a package (needed for Vercel's entrypoint,
"game.app:app" — see pyproject.toml). The modules in this directory
(app.py, db.py, solver.py, ...) import each other with bare names
(`import db`, not `from . import db`), matching how they're already run
directly (`cd game && gunicorn app:app`, `python game/app.py` for
Render/Railway/local dev) — those entrypoints put `game/` on sys.path
automatically. Importing as `game.app` from outside does not, so this
adds it explicitly, once, here — nothing inside this directory needs to
change either way.
"""
import os
import sys

_this_dir = os.path.dirname(os.path.abspath(__file__))
if _this_dir not in sys.path:
    sys.path.insert(0, _this_dir)
