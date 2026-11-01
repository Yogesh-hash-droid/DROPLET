"""
P2 admin authentication tests for PUT /api/config (DB-free).

Covers, against an in-memory SQLite database (no MySQL, no SQL against a live
server):
  * missing X-Admin-Key            -> HTTP 401
  * incorrect X-Admin-Key          -> HTTP 401
  * correct X-Admin-Key            -> configuration update succeeds
  * ADMIN_API_KEY not configured   -> HTTP 503 (fail closed)
  * unauthorized requests do NOT change the stored configuration
  * GET /api/config needs no key (unchanged read path)

The configured key value is never echoed in any response (asserted here).
POST /api/readings is deliberately out of scope: it stays unauthenticated for
the simulator/ESP8266 (separate, temporary device-security risk).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.security import require_admin_key

# Test-only credential - NOT a real secret, safe to commit.
TEST_ADMIN_KEY = "test-admin-key-not-a-real-secret"
# Sentinel used as the "incorrect" key.
WRONG_KEY = "definitely-wrong-key"

CONFIG_UPDATE = {"tds_max": 600.0}


# ---------------------------------------------------------------------------
# Fixtures: in-memory database + get_db override. The auth dependency is
# deliberately NOT overridden - these tests exercise the real security path.
# Any stray override left by another module is neutralized for this module.
# ---------------------------------------------------------------------------
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield TestingSessionLocal
    engine.dispose()


@pytest.fixture()
def client(db):
    previous_db = app.dependency_overrides.get(get_db)
    previous_auth = app.dependency_overrides.pop(require_admin_key, None)

    def override_get_db():
        session = db()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(require_admin_key, None)
    if previous_db is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_db
    if previous_auth is not None:
        app.dependency_overrides[require_admin_key] = previous_auth


@pytest.fixture()
def configured_key(monkeypatch):
    """Point the cached Settings singleton at a known test key (auto-reverted)."""
    monkeypatch.setattr(get_settings(), "ADMIN_API_KEY", TEST_ADMIN_KEY)
    return TEST_ADMIN_KEY


@pytest.fixture()
def unconfigured_key(monkeypatch):
    """Simulate a server deployed WITHOUT ADMIN_API_KEY (fail-closed path)."""
    monkeypatch.setattr(get_settings(), "ADMIN_API_KEY", None)
    return None


# ---------------------------------------------------------------------------
# Read path must stay open (requirement: GET /api/config unchanged)
# ---------------------------------------------------------------------------
def test_get_config_requires_no_key(client, configured_key):
    res = client.get("/api/config")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "tds_max" in body and "status_good_min" in body


# ---------------------------------------------------------------------------
# 1. Missing key -> 401
# ---------------------------------------------------------------------------
def test_put_missing_key_returns_401(client, configured_key):
    res = client.put("/api/config", json=CONFIG_UPDATE)
    assert res.status_code == 401, res.text
    detail = res.json().get("detail", "")
    assert "X-Admin-Key" in detail
    # Never expose the configured key in the response
    assert configured_key not in res.text


# ---------------------------------------------------------------------------
# 2. Incorrect key -> 401
# ---------------------------------------------------------------------------
def test_put_incorrect_key_returns_401(client, configured_key):
    res = client.put(
        "/api/config", json=CONFIG_UPDATE, headers={"X-Admin-Key": WRONG_KEY}
    )
    assert res.status_code == 401, res.text
    assert res.json().get("detail") == "Invalid admin key."
    # Never echo either the supplied or the configured key
    assert WRONG_KEY not in res.text
    assert configured_key not in res.text


# ---------------------------------------------------------------------------
# 3. Correct key -> update succeeds
# ---------------------------------------------------------------------------
def test_put_correct_key_updates_config(client, configured_key):
    res = client.put(
        "/api/config", json=CONFIG_UPDATE, headers={"X-Admin-Key": configured_key}
    )
    assert res.status_code == 200, res.text
    assert res.json()["tds_max"] == 600.0
    # Persisted: a keyless GET reflects the change
    assert client.get("/api/config").json()["tds_max"] == 600.0
    # And the configured key still never appears in the success response
    assert configured_key not in res.text


# ---------------------------------------------------------------------------
# 4. Missing server configuration -> 503 (fail closed, checked before the key)
# ---------------------------------------------------------------------------
def test_put_unconfigured_server_returns_503(client, unconfigured_key):
    # Even a would-be-correct-looking header must not enable updates
    res = client.put(
        "/api/config", json=CONFIG_UPDATE, headers={"X-Admin-Key": "anything"}
    )
    assert res.status_code == 503, res.text
    assert "not configured" in res.json().get("detail", "")


def test_put_unconfigured_server_returns_503_without_header(client, unconfigured_key):
    res = client.put("/api/config", json=CONFIG_UPDATE)
    assert res.status_code == 503, res.text


# ---------------------------------------------------------------------------
# 5. Unauthorized requests do not change the configuration
# ---------------------------------------------------------------------------
def test_unauthorized_requests_do_not_change_config(client, configured_key):
    before = client.get("/api/config").json()

    # (a) missing key
    res_a = client.put("/api/config", json={"tds_max": 12345.0})
    assert res_a.status_code == 401
    # (b) wrong key
    res_b = client.put(
        "/api/config", json={"tds_max": 12345.0}, headers={"X-Admin-Key": WRONG_KEY}
    )
    assert res_b.status_code == 401

    after = client.get("/api/config").json()
    assert after == before
    assert after["tds_max"] != 12345.0


def test_unconfigured_server_does_not_change_config(client, unconfigured_key):
    # Establish a value while the auth dependency is overridden (authorized),
    # then switch to fail-closed mode and prove rejected writes change nothing.
    app.dependency_overrides[require_admin_key] = lambda: None
    try:
        res_ok = client.put("/api/config", json={"tds_max": 777.0})
        assert res_ok.status_code == 200, res_ok.text
    finally:
        app.dependency_overrides.pop(require_admin_key, None)

    before = client.get("/api/config").json()
    assert before["tds_max"] == 777.0

    res = client.put("/api/config", json={"tds_max": 555.0})
    assert res.status_code == 503

    after = client.get("/api/config").json()
    assert after == before
    assert after["tds_max"] == 777.0
