"""Test configuration: each test runs against its own temporary SQLite DB.

The LABDATA_DB_PATH variable is set BEFORE loading main.py, because main.py
creates its SQLAlchemy engine when imported.
"""
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("LABDATA_DB_PATH", str(tmp_path / "test.db"))
    module_name = f"labdata_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, root / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        with TestClient(module.app) as test_client:
            yield test_client
    finally:
        if 'module' in locals() and hasattr(module, "engine"):
            module.engine.dispose()
        sys.modules.pop(module_name, None)
