"""
Org-isolation tests: verifies that org_id filtering at the query level
actually prevents cross-org data access, per-org email uniqueness works
as designed, and new candidates always land in the correct org.

Filled in one test at a time — see conftest.py for shared fixtures
(client, signup_org, invite_and_signup_recruiter).
"""


def test_recruiter_cannot_fetch_another_orgs_candidate_by_id():
    # TODO: recruiter in org A cannot GET a candidate belonging to org B,
    # even by guessing/using a real candidate_id from org B directly.
    pass


def test_recruiter_candidate_list_excludes_other_orgs():
    # TODO: /recruiter/candidates for org A never includes org B's candidates.
    pass


def test_same_email_allowed_across_different_orgs():
    # TODO: the same candidate email can exist in org A and org B independently
    # (per-org uniqueness, not global).
    pass


def test_duplicate_email_rejected_within_same_org():
    # TODO: creating two candidates with the same email inside one org is rejected.
    pass


def test_new_candidate_created_via_org_slug_lands_in_correct_org():
    # TODO: POST /sessions?org=<org-A-slug> creates a candidate whose org_id
    # matches org A, and never org B, even when both orgs exist simultaneously.
    # (Org is resolved purely from the slug -> Organization lookup in
    # start_session; there's no client-supplied org_id to spoof directly, so
    # this test is really about that slug resolution being correct.)
    pass


def test_unknown_org_slug_returns_404():
    # TODO: POST /sessions?org=<nonexistent-slug> returns 404, not a
    # silently-created candidate with a null/default org.
    pass