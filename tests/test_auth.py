"""
Auth tests: role gating, token expiry, single-use invite codes, and
last-admin protection.

Filled in one test at a time — see conftest.py for shared fixtures
(client, signup_org, invite_and_signup_recruiter).
"""


# --- Role gating ---

def test_non_admin_recruiter_gets_403_on_admin_only_route():
    # TODO: a plain recruiter (not admin) hitting e.g. GET /admin/team gets 403.
    pass


def test_admin_can_access_admin_only_route():
    # TODO: sanity check the positive case — admin token succeeds on the same route.
    pass


def test_unauthenticated_request_gets_401():
    # TODO: no Authorization header on a protected route -> 401, not 403/500.
    pass


# --- Token expiry ---

def test_expired_token_is_rejected():
    # TODO: a token past its TTL is rejected with 401 ("Session expired...").
    # Likely needs to manipulate utils.auth.VALID_TOKENS directly to backdate
    # the expiry rather than waiting 12 real hours.
    pass


def test_invalid_or_unknown_token_is_rejected():
    # TODO: a well-formed but never-issued token -> 401 ("Invalid or expired session").
    pass


# --- Invite codes ---

def test_invite_code_is_single_use():
    # TODO: using the same invite code twice -> second attempt is rejected (403).
    pass


def test_invalid_invite_code_rejected():
    # TODO: signing up with a made-up invite code -> 403.
    pass


# --- Last-admin protection ---

def test_cannot_remove_last_admin():
    # TODO: POST /admin/team/remove targeting the only admin in an org -> 400.
    pass


def test_cannot_demote_last_admin():
    # TODO: POST /admin/team/role demoting the only admin to "recruiter" -> 400.
    pass


def test_can_remove_admin_when_another_admin_remains():
    # TODO: sanity check the positive case — removing one of two admins succeeds.
    pass