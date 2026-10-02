import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GAME_DIR = ROOT / "game"
if str(GAME_DIR) not in sys.path:
    sys.path.insert(0, str(GAME_DIR))

import db
import app as game_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask client backed by a fresh temporary SQLite database."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_game.db")
    db.init_db()

    game_app.app.config.update(TESTING=True)
    with game_app.app.test_client() as client:
        yield client
