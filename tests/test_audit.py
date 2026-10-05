"""
Audit trail tests: invite expiry, invite revocation, IP/user-agent capture
on invite redemption, and RecruiterSession login/logout tracking.

Filled in one test at a time — see conftest.py for shared fixtures
(client, signup_org, invite_and_signup_recruiter, db_session).
"""

from datetime import datetime, timedelta

from db.models import RecruiterSession, InviteToken
from utils.auth import hash_token
from conftest import unique_email, auth_headers


# --- Invite expiry ---

def test_invite_expires_after_set_duration(client, signup_org, db_session):
    admin = signup_org()

    invite_resp = client.post(
        "/admin/invite", json={"expires_in_days": 1}, headers=auth_headers(admin["token"])
    )
    assert invite_resp.status_code == 200, invite_resp.text
    code = invite_resp.json()["code"]

    # Backdate expires_at directly rather than waiting a real day.
    token_row = db_session.query(InviteToken).filter(InviteToken.code == code).first()
    token_row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    signup_resp = client.post("/recruiter/signup", json={
        "name": "Late Recruiter", "email": unique_email("late"), "password": "correct-horse-1",
        "invite_code": code,
    })
    assert signup_resp.status_code == 403
    assert signup_resp.json()["detail"] == "This invite code has expired"


def test_expired_unused_invite_excluded_from_pending_count(client, signup_org, db_session):
    admin = signup_org()

    invite_resp = client.post(
        "/admin/invite", json={"expires_in_days": 1}, headers=auth_headers(admin["token"])
    )
    code = invite_resp.json()["code"]

    overview_before = client.get("/admin/overview", headers=auth_headers(admin["token"]))
    assert overview_before.json()["pending_invites"] == 1

    token_row = db_session.query(InviteToken).filter(InviteToken.code == code).first()
    token_row.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    overview_after = client.get("/admin/overview", headers=auth_headers(admin["token"]))
    assert overview_after.json()["pending_invites"] == 0


# --- Invite revocation ---

def test_revoked_invite_rejected_on_redemption(client, signup_org):
    admin = signup_org()

    invite_resp = client.post("/admin/invite", headers=auth_headers(admin["token"]))
    code = invite_resp.json()["code"]

    revoke_resp = client.post(
        "/admin/invite/revoke", json={"code": code}, headers=auth_headers(admin["token"])
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    signup_resp = client.post("/recruiter/signup", json={
        "name": "Blocked Recruiter", "email": unique_email("blocked"), "password": "correct-horse-1",
        "invite_code": code,
    })
    assert signup_resp.status_code == 403
    assert signup_resp.json()["detail"] == "This invite code has been revoked"


def test_revoking_already_used_invite_succeeds_as_record_keeping(client, signup_org, invite_and_signup_recruiter):
    admin = signup_org()
    recruiter = invite_and_signup_recruiter(admin["token"])

    revoke_resp = client.post(
        "/admin/invite/revoke", json={"code": recruiter["invite_code"]}, headers=auth_headers(admin["token"])
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    # The recruiter account created earlier still exists and can still log in —
    # revoking a used code is a record-keeping flag, not an undo.
    login_resp = client.post("/recruiter/login", json={
        "email": recruiter["email"], "password": recruiter["password"],
    })
    assert login_resp.status_code == 200


def test_revoke_nonexistent_invite_returns_404(client, signup_org):
    admin = signup_org()

    revoke_resp = client.post(
        "/admin/invite/revoke", json={"code": "this-code-was-never-issued"}, headers=auth_headers(admin["token"])
    )
    assert revoke_resp.status_code == 404
    assert revoke_resp.json()["detail"] == "Invite code not found"


def test_revoked_invite_excluded_from_pending_count(client, signup_org):
    admin = signup_org()

    invite_resp = client.post("/admin/invite", headers=auth_headers(admin["token"]))
    code = invite_resp.json()["code"]

    overview_before = client.get("/admin/overview", headers=auth_headers(admin["token"]))
    assert overview_before.json()["pending_invites"] == 1

    revoke_resp = client.post(
        "/admin/invite/revoke", json={"code": code}, headers=auth_headers(admin["token"])
    )
    assert revoke_resp.status_code == 200

    overview_after = client.get("/admin/overview", headers=auth_headers(admin["token"]))
    assert overview_after.json()["pending_invites"] == 0


# --- IP / user-agent capture ---

def test_invite_redemption_captures_ip_and_user_agent(client, signup_org, db_session):
    admin = signup_org()

    invite_resp = client.post("/admin/invite", headers=auth_headers(admin["token"]))
    code = invite_resp.json()["code"]

    signup_resp = client.post(
        "/recruiter/signup",
        json={
            "name": "Tracked Recruiter", "email": unique_email("tracked"),
            "password": "correct-horse-1", "invite_code": code,
        },
        headers={"User-Agent": "CustomTestAgent/1.0"},
    )
    assert signup_resp.status_code == 200, signup_resp.text

    token_row = db_session.query(InviteToken).filter(InviteToken.code == code).first()
    assert token_row.used_ip is not None
    assert token_row.used_user_agent == "CustomTestAgent/1.0"


# --- RecruiterSession tracking ---

def test_successful_login_creates_session_row(client, signup_org, db_session):
    admin = signup_org()

    login_resp = client.post("/recruiter/login", json={"email": admin["email"], "password": admin["password"]})
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["token"]

    row = db_session.query(RecruiterSession).filter(
        RecruiterSession.token_hash == hash_token(token)
    ).first()

    assert row is not None
    assert row.success is True
    assert row.email_attempted == admin["email"]
    assert row.ended_at is None
    assert row.end_reason is None


def test_failed_login_creates_session_row(client, signup_org, db_session):
    admin = signup_org()
    team = client.get("/admin/team", headers={"Authorization": f"Bearer {admin['token']}"}).json()
    admin_id = next(r["id"] for r in team if r["email"] == admin["email"])

    resp = client.post("/recruiter/login", json={"email": admin["email"], "password": "wrong-password"})
    assert resp.status_code == 401

    row = db_session.query(RecruiterSession).filter(
        RecruiterSession.email_attempted == admin["email"], RecruiterSession.success.is_(False)
    ).order_by(RecruiterSession.started_at.desc()).first()

    assert row is not None
    assert str(row.recruiter_id) == admin_id
    assert row.token_hash is None
    assert row.ended_at is None


def test_logout_closes_session_row(client, signup_org, db_session):
    admin = signup_org()

    login_resp = client.post("/recruiter/login", json={"email": admin["email"], "password": admin["password"]})
    token = login_resp.json()["token"]

    logout_resp = client.post("/recruiter/logout", headers=auth_headers(token))
    assert logout_resp.status_code == 200
    assert logout_resp.json()["logged_out"] is True

    row = db_session.query(RecruiterSession).filter(
        RecruiterSession.token_hash == hash_token(token)
    ).first()
    assert row.ended_at is not None
    assert row.end_reason == "logout"


def test_expired_token_closes_session_row_as_expired():
    # TODO: login -> backdate the RecruiterSession row's expires_at directly (token
    # validity now lives entirely in the DB, see utils/auth.py) -> hit a protected
    # route -> 401, and the row is closed with end_reason == "expired".
    pass


def test_concurrent_logins_create_separate_session_rows():
    # TODO: log in twice for the same recruiter -> two distinct
    # RecruiterSession rows with two different token_hash values.
    pass