import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.database import Base, get_db, get_db_session
from app.main import app
from app.settings import settings


@pytest.fixture
def temp_env(tmp_path: Path):
    """Setup isolated database and storage directory per test."""
    temp_db_file = tmp_path / "test_certs.db"
    temp_storage = tmp_path / "storage"
    temp_storage.mkdir(parents=True, exist_ok=True)

    orig_db_url = settings.DATABASE_URL
    orig_storage_dir = settings.STORAGE_DIR
    orig_sync_mode = settings.SYNC_MODE

    # Configure isolated test environment
    test_db_url = f"sqlite:///{temp_db_file}"
    settings.DATABASE_URL = test_db_url
    settings.STORAGE_DIR = temp_storage
    settings.SYNC_MODE = True  # Deterministic execution for tests

    # Create isolated test engine and session factory
    test_engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # Patch database engine in database module
    import app.database as app_db
    orig_engine = app_db.engine
    orig_SessionLocal = app_db.SessionLocal
    app_db.engine = test_engine
    app_db.SessionLocal = TestingSessionLocal

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    yield {
        "engine": test_engine,
        "session_maker": TestingSessionLocal,
        "storage_dir": temp_storage,
        "db_file": temp_db_file,
    }

    # Teardown
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
    app_db.engine = orig_engine
    app_db.SessionLocal = orig_SessionLocal
    settings.DATABASE_URL = orig_db_url
    settings.STORAGE_DIR = orig_storage_dir
    settings.SYNC_MODE = orig_sync_mode


@pytest.fixture
def client(temp_env) -> Generator[TestClient, None, None]:
    """TestClient fixture with isolated database and storage."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session(temp_env) -> Generator[Session, None, None]:
    """Direct database session fixture for inspecting state in tests."""
    session = temp_env["session_maker"]()
    try:
        yield session
    finally:
        session.close()
