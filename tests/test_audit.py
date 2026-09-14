"""
Audit trail tests: invite expiry, invite revocation, IP/user-agent capture
on invite redemption, and RecruiterSession login/logout tracking.

Filled in one test at a time — see conftest.py for shared fixtures
(client, signup_org, invite_and_signup_recruiter, db_session).
"""

import uuid

from db.models import RecruiterSession
from utils.auth import hash_token


# --- Invite expiry ---

def test_invite_expires_after_set_duration():
    # TODO: create invite with expires_in_days, backdate its expires_at,
    # then attempt redemption -> 403 "This invite code has expired".
    pass


def test_expired_unused_invite_excluded_from_pending_count():
    # TODO: /admin/overview's pending_invites excludes an unused invite
    # whose expires_at is in the past.
    pass


# --- Invite revocation ---

def test_revoked_invite_rejected_on_redemption():
    # TODO: revoke an unused invite via /admin/invite/revoke, then attempt
    # redemption -> 403 "This invite code has been revoked".
    pass


def test_revoking_already_used_invite_succeeds_as_record_keeping():
    # TODO: revoking a used invite still returns 200 {"revoked": True} —
    # purely a record-keeping flag, doesn't undo the account already created.
    pass


def test_revoke_nonexistent_invite_returns_404():
    # TODO: /admin/invite/revoke with a made-up code -> 404.
    pass


def test_revoked_invite_excluded_from_pending_count():
    # TODO: /admin/overview's pending_invites excludes a revoked-but-unused invite.
    pass


# --- IP / user-agent capture ---

def test_invite_redemption_captures_ip_and_user_agent():
    # TODO: signup via invite with a custom User-Agent header, then check the
    # InviteToken row directly (used_ip, used_user_agent) — not exposed via
    # the /admin/invites API response, so this needs a direct DB query.
    pass


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


def test_logout_closes_session_row():
    # TODO: login -> logout -> the matching RecruiterSession row now has
    # ended_at set and end_reason == "logout".
    pass


def test_expired_token_closes_session_row_as_expired():
    # TODO: login -> backdate VALID_TOKENS entry -> hit a protected route ->
    # 401, and the RecruiterSession row is closed with end_reason == "expired".
    pass


def test_concurrent_logins_create_separate_session_rows():
    # TODO: log in twice for the same recruiter -> two distinct
    # RecruiterSession rows with two different token_hash values.
    pass