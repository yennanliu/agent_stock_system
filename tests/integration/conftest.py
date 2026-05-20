"""
Session-level setup for integration tests.

The FastAPI TestClient used at module scope does NOT trigger the app's
lifespan handler (which calls init_db). We must initialise the DB and
required directories explicitly before any test runs.
"""
import pytest
from src.tools.db import init_db


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """Initialise SQLite schema before any integration test runs."""
    init_db()
    yield
