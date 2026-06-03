"""Pytest fixtures for jarvis-notifications tests."""

import os

# Set test environment BEFORE importing app modules
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["AUTH_SECRET_KEY"] = "test-secret-key"
os.environ["AUTH_ALGORITHM"] = "HS256"
os.environ["JARVIS_AUTH_BASE_URL"] = "http://localhost:7701"

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Now import app modules after env is set
from app.db import Base, get_db
from app.deps import AuthenticatedUser, get_current_user, verify_app_auth, verify_admin_key
from app.main import app


# Create test engine with SQLite
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


# Enable foreign keys for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _mock_current_user() -> AuthenticatedUser:
    """Mock authenticated user from JWT."""
    return AuthenticatedUser(user_id=42, household_id="test-household-123", email="test@jarvis.local")


async def _mock_app_auth() -> None:
    """Mock app-to-app auth that always succeeds."""
    pass


def _mock_admin_key() -> None:
    """Mock admin key that always succeeds."""
    pass


@pytest.fixture(autouse=True)
def clear_dedup_cache():
    """Clear notification dedup cache + relay JWT cache before each test."""
    from app.services.notification_service import _dedup_cache, _relay_jwt_cache
    _dedup_cache.clear()
    _relay_jwt_cache.clear()
    # Don't let one test's RELAY_* env leak into the next.
    os.environ.pop("RELAY_URL", None)
    os.environ.pop("RELAY_HOUSEHOLD_JWT", None)
    yield
    _dedup_cache.clear()
    _relay_jwt_cache.clear()
    os.environ.pop("RELAY_URL", None)
    os.environ.pop("RELAY_HOUSEHOLD_JWT", None)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with overridden dependencies."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _mock_current_user
    app.dependency_overrides[verify_app_auth] = _mock_app_auth
    app.dependency_overrides[verify_admin_key] = _mock_admin_key

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers():
    """Headers for admin-authenticated requests."""
    return {"X-Api-Key": "test-admin-key"}


@pytest.fixture
def user_token():
    """JWT token for authenticated user."""
    payload = {"sub": "42", "household_id": "test-household-123", "email": "test@jarvis.local"}
    return jwt.encode(payload, "test-secret-key", algorithm="HS256")


@pytest.fixture
def auth_headers(user_token):
    """Headers with Bearer token for user auth."""
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def sample_token_data():
    """Sample push token registration data."""
    return {
        "push_token": "ExponentPushToken[abc123]",
        "device_type": "ios",
        "device_name": "Alex's iPhone",
    }


@pytest.fixture
def another_token_data():
    """Another sample push token."""
    return {
        "push_token": "ExponentPushToken[def456]",
        "device_type": "android",
        "device_name": "Alex's Pixel",
    }


@pytest.fixture
def sample_notification_data():
    """Sample notification payload."""
    return {
        "target_type": "user",
        "target_id": "42",
        "title": "Research Complete",
        "body": "Your research on espresso machines is ready.",
        "data": {"type": "deep_research", "result_id": "abc-123"},
        "priority": "default",
        "category": "research",
    }
