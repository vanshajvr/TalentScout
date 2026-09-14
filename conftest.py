"""
Shared pytest fixtures for the org-isolation / auth test suite.

IMPORTANT: this module sets the DATABASE_URL environment variable *before*
importing anything from the app (db.database reads DATABASE_URL at import
time), so the app's engine connects to the Neon test branch instead of
dev/prod. Do not reorder the imports below.
"""

import os
import uuid

import pytest
from dotenv import load_dotenv

load_dotenv(".env.test")

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. Create a Neon test branch and set it, "
        "e.g. in a .env.test file:\n"
        "  TEST_DATABASE_URL=postgresql://user:pass@ep-xxxx.neon.tech/talentscout_test?sslmode=require\n"
        "Tests refuse to run without an explicit test database."
    )

if TEST_DATABASE_URL == os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "TEST_DATABASE_URL is identical to DATABASE_URL. Refusing to run tests "
        "against what looks like your dev/prod database."
    )

os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# Safe to import app modules now that DATABASE_URL points at the test branch.
from fastapi.testclient import TestClient  # noqa: E402

from db.database import engine  # noqa: E402
from db.models import Base  # noqa: E402
import utils.auth as auth_module  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    """Create all tables once at the start of the test session, drop them at the end."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_state():
    """
    Runs after every test. Truncates all tables and clears the in-memory
    token store, so each test starts from a blank slate regardless of
    execution order.

    Truncate (not a begin/rollback-per-test pattern) because the app's own
    get_db() dependency opens its own DB session per request, independent
    of any transaction a fixture would hold open — so rollback-based
    isolation wouldn't actually undo anything the app itself committed.
    """
    yield
    table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE")
    auth_module.VALID_TOKENS.clear()


@pytest.fixture
def client():
    return TestClient(app)


def unique_email(local_prefix: str = "test") -> str:
    """
    A real, deliverable domain (gmail.com) so utils.validators.is_valid_email's
    DNS/MX check passes for real — the local part is randomized so repeated
    calls don't collide on the per-org / global-recruiter uniqueness constraints.
    """
    return f"{local_prefix}+{uuid.uuid4().hex[:10]}@gmail.com"


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def signup_org(client):
    """
    Creates a fresh org with its first admin via the real /admin/signup endpoint.
    Returns a dict with the admin's token and account details.
    Call it as signup_org() inside a test, or signup_org(org_name="Acme") to name the org.
    """
    def _signup(org_name: str | None = None, admin_name: str = "Test Admin", password: str = "correct-horse-1"):
        org_name = org_name or f"Org {uuid.uuid4().hex[:8]}"
        email = unique_email("admin")
        resp = client.post("/admin/signup", json={
            "org_name": org_name, "name": admin_name, "email": email, "password": password,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        return {
            "token": data["token"],
            "name": data["name"],
            "email": email,
            "password": password,
            "org_name": org_name,
        }
    return _signup


@pytest.fixture
def invite_and_signup_recruiter(client):
    """
    Given an admin's token, creates an invite code via /admin/invite and signs up
    a new recruiter with it via /recruiter/signup. Returns the new recruiter's
    token and account details, plus the invite code that was used.
    """
    def _do(admin_token: str, name: str = "Test Recruiter", password: str = "correct-horse-2"):
        invite_resp = client.post("/admin/invite", headers=auth_headers(admin_token))
        assert invite_resp.status_code == 200, invite_resp.text
        code = invite_resp.json()["code"]

        email = unique_email("recruiter")
        signup_resp = client.post("/recruiter/signup", json={
            "name": name, "email": email, "password": password, "invite_code": code,
        })
        assert signup_resp.status_code == 200, signup_resp.text
        data = signup_resp.json()
        return {
            "token": data["token"],
            "name": data["name"],
            "email": email,
            "password": password,
            "invite_code": code,
        }
    return _do