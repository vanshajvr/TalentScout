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


def test_admin_cannot_change_own_role(client, signup_org):
    # This is also what keeps a sole admin from demoting themselves: the only admin
    # who could demote the last admin is that admin.
    admin = signup_org()
    team = client.get("/admin/team", headers={"Authorization": f"Bearer {admin['token']}"}).json()
    admin_id = next(r["id"] for r in team if r["email"] == admin["email"])

    resp = client.post("/admin/team/role", json={"recruiter_id": admin_id, "new_role": "recruiter"},
                        headers={"Authorization": f"Bearer {admin['token']}"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "You can't change your own role"


def test_demoted_admin_loses_admin_actions_immediately(client, signup_org, invite_and_signup_recruiter):
    # The sequential version of the "two admins demote each other" race: once one
    # demotion lands, the other admin's next team change must be refused — so the
    # org can never end up with zero admins.
    admin_a = signup_org()
    b = invite_and_signup_recruiter(admin_a["token"])
    headers_a = {"Authorization": f"Bearer {admin_a['token']}"}
    headers_b = {"Authorization": f"Bearer {b['token']}"}
    team = client.get("/admin/team", headers=headers_a).json()
    a_id = next(r["id"] for r in team if r["email"] == admin_a["email"])
    b_id = next(r["id"] for r in team if r["email"] == b["email"])

    assert client.post("/admin/team/role", json={"recruiter_id": b_id, "new_role": "admin"}, headers=headers_a).status_code == 200
    assert client.post("/admin/team/role", json={"recruiter_id": a_id, "new_role": "recruiter"}, headers=headers_b).status_code == 200

    resp = client.post("/admin/team/role", json={"recruiter_id": b_id, "new_role": "recruiter"}, headers=headers_a)
    assert resp.status_code == 403
    team = client.get("/admin/team", headers=headers_b).json()
    assert [r["role"] for r in team].count("admin") == 1


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

def test_concurrent_admin_changes_serialize_on_the_admin_lock(client, signup_org, invite_and_signup_recruiter):
    # The actual race: A and B (both admins) act on each other at the same time.
    # A's transaction holds the admin-row lock and demotes B; B's transaction must
    # block on the lock, then see it is no longer an admin, rather than both landing.
    import threading
    from fastapi import HTTPException
    from db.database import SessionLocal
    from db.models import Recruiter
    from routers.admin import _lock_org_admins

    admin_a = signup_org()
    b = invite_and_signup_recruiter(admin_a["token"])
    headers_a = {"Authorization": f"Bearer {admin_a['token']}"}
    team = client.get("/admin/team", headers=headers_a).json()
    a_id = next(r["id"] for r in team if r["email"] == admin_a["email"])
    b_id = next(r["id"] for r in team if r["email"] == b["email"])
    client.post("/admin/team/role", json={"recruiter_id": b_id, "new_role": "admin"}, headers=headers_a)

    s1, s2 = SessionLocal(), SessionLocal()
    outcome = {}
    try:
        # Open B's connection and load B's row up front, so the only thing that can
        # delay B below is the lock itself — not connection setup to the database.
        b_row = s2.get(Recruiter, uuid.UUID(b_id))
        s2.commit()
        a_row = s1.get(Recruiter, uuid.UUID(a_id))
        _lock_org_admins(s1, a_row)
        s1.get(Recruiter, uuid.UUID(b_id)).role = "recruiter"
        s1.flush()  # A's demotion of B is written but not committed; the lock is held

        def b_acts():
            try:
                _lock_org_admins(s2, b_row)
                outcome["result"] = "allowed"
            except HTTPException as e:
                outcome["result"] = e.status_code

        t = threading.Thread(target=b_acts)
        t.start()
        t.join(timeout=1.0)
        assert t.is_alive(), "B's request should be blocked while A holds the admin lock"

        s1.commit()
        t.join(timeout=10)
        assert outcome["result"] == 403
    finally:
        s1.close()
        s2.rollback()
        s2.close()
