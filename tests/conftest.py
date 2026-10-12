"""Shared pytest fixtures.

The suite runs against its own SQLite file so the delivered demo database is
never polluted by a test run.
"""

from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_DB = ROOT / "test-data.db"

for suffix in ("", "-wal", "-shm"):
    candidate = pathlib.Path(str(TEST_DB) + suffix)
    if candidate.exists():
        candidate.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["SECRET_KEY"] = "cenius-dev-test-session-key"
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app_module():
    import app  # noqa: E402  (imports only after DATABASE_URL is set)

    app.app._setup_server()
    return app


@pytest.fixture()
def client(app_module):
    return app_module.server.test_client()


@pytest.fixture()
def auth_client(app_module):
    """A test client already signed in as the seeded demo coordinator."""
    from tests.dash_client import sign_in

    test_client = app_module.server.test_client()
    sign_in(test_client)
    return test_client


def pytest_sessionfinish(session, exitstatus):  # pragma: no cover - cleanup hook
    for suffix in ("", "-wal", "-shm"):
        candidate = pathlib.Path(str(TEST_DB) + suffix)
        if candidate.exists():
            candidate.unlink()
