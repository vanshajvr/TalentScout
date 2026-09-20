"""
Auth tests: role gating, token expiry, single-use invite codes, and
last-admin protection.

Filled in one test at a time — see conftest.py for shared fixtures
(client, signup_org, invite_and_signup_recruiter).
"""

from datetime import datetime, timedelta
import uuid

import utils.auth as auth_module
from db.models import RecruiterSession


# --- Role gating ---

def test_non_admin_recruiter_gets_403_on_admin_only_route(client, signup_org, invite_and_signup_recruiter):
    admin = signup_org()
    recruiter = invite_and_signup_recruiter(admin["token"])

    resp = client.get("/admin/team", headers={"Authorization": f"Bearer {recruiter['token']}"})

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin access required"


def test_admin_can_access_admin_only_route(client, signup_org):
    admin = signup_org()

    resp = client.get("/admin/team", headers={"Authorization": f"Bearer {admin['token']}"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["email"] == admin["email"]
    assert body[0]["role"] == "admin"


def test_unauthenticated_request_gets_401(client):
    resp = client.get("/admin/team")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


# --- Token expiry ---

def test_expired_token_is_rejected(client, signup_org, db_session):
    admin = signup_org()

    # Force this specific token's session row to already be expired in the DB,
    # without waiting 12 real hours. Token validity now lives entirely in
    # RecruiterSession (see utils/auth.py), not an in-memory store.
    session_row = db_session.query(RecruiterSession).filter(
        RecruiterSession.token_hash == auth_module.hash_token(admin["token"])
    ).first()
    session_row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    resp = client.get("/admin/team", headers={"Authorization": f"Bearer {admin['token']}"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Session expired — please log in again"


def test_invalid_or_unknown_token_is_rejected(client):
    fake_token = "this-token-was-never-issued-by-the-server"

    resp = client.get("/admin/team", headers={"Authorization": f"Bearer {fake_token}"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired session"


# --- Invite codes ---

def test_invite_code_is_single_use(client, signup_org):
    admin = signup_org()
    invite_resp = client.post("/admin/invite", headers={"Authorization": f"Bearer {admin['token']}"})
    code = invite_resp.json()["code"]

    first_resp = client.post("/recruiter/signup", json={
        "name": "First Recruiter", "email": f"first+{uuid.uuid4().hex[:8]}@gmail.com",
        "password": "pw-first-1", "invite_code": code,
    })
    assert first_resp.status_code == 200, first_resp.text

    second_resp = client.post("/recruiter/signup", json={
        "name": "Second Recruiter", "email": f"second+{uuid.uuid4().hex[:8]}@gmail.com",
        "password": "pw-second-1", "invite_code": code,
    })

    assert second_resp.status_code == 403
    assert second_resp.json()["detail"] == "This invite code has already been used"


def test_invalid_invite_code_rejected(client):
    resp = client.post("/recruiter/signup", json={
        "name": "Nobody", "email": f"nobody+{uuid.uuid4().hex[:8]}@gmail.com",
        "password": "pw-nobody-1", "invite_code": "this-code-does-not-exist",
    })

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Invalid invite code"


# --- Last-admin protection ---

def test_cannot_remove_last_admin(client, signup_org):
    admin = signup_org()
    team = client.get("/admin/team", headers={"Authorization": f"Bearer {admin['token']}"}).json()
    admin_id = next(r["id"] for r in team if r["email"] == admin["email"])

    resp = client.post("/admin/team/remove", json={"recruiter_id": admin_id},
                        headers={"Authorization": f"Bearer {admin['token']}"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Can't remove the last admin in this org"


def test_cannot_demote_last_admin(client, signup_org):
    admin = signup_org()
    team = client.get("/admin/team", headers={"Authorization": f"Bearer {admin['token']}"}).json()
    admin_id = next(r["id"] for r in team if r["email"] == admin["email"])

    resp = client.post("/admin/team/role", json={"recruiter_id": admin_id, "new_role": "recruiter"},
                        headers={"Authorization": f"Bearer {admin['token']}"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Can't demote the last admin in this org"


def test_can_remove_admin_when_another_admin_remains(client, signup_org, invite_and_signup_recruiter):
    admin = signup_org()
    recruiter = invite_and_signup_recruiter(admin["token"])

    team = client.get("/admin/team", headers={"Authorization": f"Bearer {admin['token']}"}).json()
    recruiter_id = next(r["id"] for r in team if r["email"] == recruiter["email"])

    # Promote the recruiter to admin, so the org now has two admins.
    promote_resp = client.post("/admin/team/role", json={"recruiter_id": recruiter_id, "new_role": "admin"},
                                headers={"Authorization": f"Bearer {admin['token']}"})
    assert promote_resp.status_code == 200, promote_resp.text

    # Original admin removes the newly-promoted one — should succeed since one admin remains.
    remove_resp = client.post("/admin/team/remove", json={"recruiter_id": recruiter_id},
                               headers={"Authorization": f"Bearer {admin['token']}"})

    assert remove_resp.status_code == 200
    assert remove_resp.json() == {"removed": True}