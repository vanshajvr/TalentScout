"""
Org-isolation tests: verifies that org_id filtering at the query level
actually prevents cross-org data access, per-org email uniqueness works
as designed, and new candidates always land in the correct org.

Filled in one test at a time — see conftest.py for shared fixtures
(client, signup_org, invite_and_signup_recruiter, db_session).
"""

import uuid

from sqlalchemy.exc import IntegrityError

from db.models import Candidate, CandidateSession, Organization

def test_recruiter_cannot_fetch_another_orgs_candidate_by_id(client, signup_org, db_session):
    org_a_admin = signup_org()
    org_b_admin = signup_org()

    org_b_slug = client.get("/recruiter/org", headers={"Authorization": f"Bearer {org_b_admin['token']}"}).json()["org_slug"]
    org_b_row = db_session.query(Organization).filter(Organization.slug == org_b_slug).first()

    candidate_b = Candidate(org_id=org_b_row.id)
    db_session.add(candidate_b)
    db_session.commit()

    resp = client.get(
        f"/recruiter/candidates/{candidate_b.id}/questions",
        headers={"Authorization": f"Bearer {org_a_admin['token']}"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Candidate not found"


def test_recruiter_candidate_list_excludes_other_orgs(client, signup_org, db_session):
    org_a_admin = signup_org()
    org_b_admin = signup_org()

    org_b_slug = client.get("/recruiter/org", headers={"Authorization": f"Bearer {org_b_admin['token']}"}).json()["org_slug"]
    org_b_row = db_session.query(Organization).filter(Organization.slug == org_b_slug).first()

    candidate_b = Candidate(org_id=org_b_row.id, name="Org B Candidate")
    db_session.add(candidate_b)
    db_session.flush()
    db_session.add(CandidateSession(candidate_id=candidate_b.id, current_step="greeting"))
    db_session.commit()

    resp = client.get("/recruiter/candidates", headers={"Authorization": f"Bearer {org_a_admin['token']}"})

    assert resp.status_code == 200
    returned_ids = {c["id"] for c in resp.json()}
    assert str(candidate_b.id) not in returned_ids


def test_same_email_allowed_across_different_orgs(client, signup_org, db_session):
    org_a_admin = signup_org()
    org_b_admin = signup_org()

    org_a_slug = client.get("/recruiter/org", headers={"Authorization": f"Bearer {org_a_admin['token']}"}).json()["org_slug"]
    org_b_slug = client.get("/recruiter/org", headers={"Authorization": f"Bearer {org_b_admin['token']}"}).json()["org_slug"]
    org_a_row = db_session.query(Organization).filter(Organization.slug == org_a_slug).first()
    org_b_row = db_session.query(Organization).filter(Organization.slug == org_b_slug).first()

    shared_email = f"shared+{uuid.uuid4().hex[:8]}@gmail.com"
    db_session.add(Candidate(org_id=org_a_row.id, email=shared_email))
    db_session.commit()

    db_session.add(Candidate(org_id=org_b_row.id, email=shared_email))
    db_session.commit()  # should not raise — per-org uniqueness, not global


def test_duplicate_email_rejected_within_same_org(client, signup_org, db_session):
    org_admin = signup_org()
    org_slug = client.get("/recruiter/org", headers={"Authorization": f"Bearer {org_admin['token']}"}).json()["org_slug"]
    org_row = db_session.query(Organization).filter(Organization.slug == org_slug).first()

    dup_email = f"dup+{uuid.uuid4().hex[:8]}@gmail.com"
    db_session.add(Candidate(org_id=org_row.id, email=dup_email))
    db_session.commit()

    db_session.add(Candidate(org_id=org_row.id, email=dup_email))
    try:
        db_session.commit()
        assert False, "expected an IntegrityError from the uq_candidate_org_email constraint"
    except IntegrityError:
        db_session.rollback()


def test_new_candidate_created_via_org_slug_lands_in_correct_org(client, signup_org, db_session):
    org_a_admin = signup_org()
    org_b_admin = signup_org()

    org_a_slug = client.get("/recruiter/org", headers={"Authorization": f"Bearer {org_a_admin['token']}"}).json()["org_slug"]
    org_a_row = db_session.query(Organization).filter(Organization.slug == org_a_slug).first()

    resp = client.post("/sessions", params={"org": org_a_slug})
    assert resp.status_code == 200, resp.text
    session_id = resp.json()["session_id"]

    session_row = db_session.query(CandidateSession).filter(CandidateSession.id == uuid.UUID(session_id)).first()
    candidate_row = db_session.query(Candidate).filter(Candidate.id == session_row.candidate_id).first()

    assert candidate_row.org_id == org_a_row.id


def test_unknown_org_slug_returns_404(client):
    resp = client.post("/sessions", params={"org": "this-org-does-not-exist"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Unknown organization"