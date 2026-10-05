"""
Job openings: CRUD, org isolation, job-specific screening links, and fit ranking.
See conftest.py for shared fixtures (client, signup_org, db_session).
"""

import uuid

from db.models import Candidate, CandidateSession, JobOpening, Organization
from utils.job_match import apply_job_fit

JOB_BODY = {
    "title": "Backend Engineer",
    "description": "We need strong Python and SQL. Docker is a plus.",
    "must_have_skills": ["Python", "SQL"],
    "nice_to_have_skills": ["Docker"],
    "min_experience": 2,
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _org_slug(client, token: str) -> str:
    return client.get("/recruiter/org", headers=_auth(token)).json()["org_slug"]


def _create_job(client, token: str, **overrides) -> dict:
    resp = client.post("/recruiter/jobs", json={**JOB_BODY, **overrides}, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_create_job_cleans_and_dedupes_skills(client, signup_org):
    admin = signup_org()
    job = _create_job(
        client, admin["token"],
        must_have_skills=["Python", " python ", "SQL", ""],
        nice_to_have_skills=["Docker", "SQL"],  # SQL is already a must-have
    )
    assert job["must_have_skills"] == ["Python", "SQL"]
    assert job["nice_to_have_skills"] == ["Docker"]
    assert job["status"] == "open"


def test_jobs_are_isolated_per_org(client, signup_org):
    org_a = signup_org()
    org_b = signup_org()
    job_b = _create_job(client, org_b["token"])

    listed = client.get("/recruiter/jobs", headers=_auth(org_a["token"])).json()
    assert job_b["id"] not in {j["id"] for j in listed}

    resp = client.patch(f"/recruiter/jobs/{job_b['id']}", json={"status": "closed"}, headers=_auth(org_a["token"]))
    assert resp.status_code == 404


def test_session_cannot_attach_to_another_orgs_job(client, signup_org):
    org_a = signup_org()
    org_b = signup_org()
    job_b = _create_job(client, org_b["token"])

    resp = client.post("/sessions", params={"org": _org_slug(client, org_a["token"]), "job": job_b["id"]})
    assert resp.status_code == 404

    resp = client.get(f"/organizations/{_org_slug(client, org_a['token'])}/jobs/{job_b['id']}")
    assert resp.status_code == 404


def test_closed_job_link_returns_410(client, signup_org):
    admin = signup_org()
    job = _create_job(client, admin["token"])
    client.patch(f"/recruiter/jobs/{job['id']}", json={"status": "closed"}, headers=_auth(admin["token"]))

    resp = client.get(f"/organizations/{_org_slug(client, admin['token'])}/jobs/{job['id']}")
    assert resp.status_code == 410


def test_public_job_endpoint_hides_requirements(client, signup_org):
    admin = signup_org()
    job = _create_job(client, admin["token"])

    resp = client.get(f"/organizations/{_org_slug(client, admin['token'])}/jobs/{job['id']}")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"name", "job_title"}


def test_session_started_from_job_link_is_attached_to_job(client, signup_org, db_session):
    admin = signup_org()
    job = _create_job(client, admin["token"])

    resp = client.post("/sessions", params={"org": _org_slug(client, admin["token"]), "job": job["id"]})
    assert resp.status_code == 200, resp.text

    session_row = db_session.get(CandidateSession, uuid.UUID(resp.json()["session_id"]))
    candidate = db_session.get(Candidate, session_row.candidate_id)
    assert str(candidate.job_id) == job["id"]


def _add_scored_candidate(db_session, org_id, job_id, name, tech_stack, experience):
    candidate = Candidate(org_id=org_id, job_id=job_id, name=name, tech_stack=tech_stack, experience=experience)
    job = db_session.get(JobOpening, job_id)
    apply_job_fit(candidate, job)
    db_session.add(candidate)
    db_session.flush()
    db_session.add(CandidateSession(candidate_id=candidate.id, current_step="mcq_assessment"))
    db_session.commit()
    return candidate


def test_candidates_ranked_by_fit_within_job_and_rescored_on_edit(client, signup_org, db_session):
    admin = signup_org()
    job = _create_job(client, admin["token"])
    org_row = db_session.query(Organization).filter(Organization.slug == _org_slug(client, admin["token"])).first()
    job_uuid = uuid.UUID(job["id"])

    _add_scored_candidate(db_session, org_row.id, job_uuid, "Weak", ["Java"], 0)
    _add_scored_candidate(db_session, org_row.id, job_uuid, "Strong", ["Python", "SQL", "Docker"], 3)

    rows = client.get("/recruiter/candidates", params={"job_id": job["id"]}, headers=_auth(admin["token"])).json()
    assert [r["name"] for r in rows] == ["Strong", "Weak"]
    assert rows[0]["fit_score"] == 100
    assert rows[0]["job_title"] == "Backend Engineer"

    # Making Java the only must-have should flip the ranking without any candidate action.
    resp = client.patch(
        f"/recruiter/jobs/{job['id']}",
        json={"must_have_skills": ["Java"], "nice_to_have_skills": [], "clear_min_experience": True},
        headers=_auth(admin["token"]),
    )
    assert resp.status_code == 200, resp.text
    rows = client.get("/recruiter/candidates", params={"job_id": job["id"]}, headers=_auth(admin["token"])).json()
    assert [r["name"] for r in rows] == ["Weak", "Strong"]


def test_parse_job_description_uses_llm_draft(client, signup_org, monkeypatch):
    admin = signup_org()
    from routers import jobs

    monkeypatch.setattr(
        jobs.llm, "generate",
        lambda *a, **k: '{"must_have_skills": ["Python", "python"], "nice_to_have_skills": ["Python", "AWS"], "min_experience": "3"}',
    )
    resp = client.post(
        "/recruiter/jobs/parse", json={"title": "Backend Engineer", "description": "..."}, headers=_auth(admin["token"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"must_have_skills": ["Python"], "nice_to_have_skills": ["AWS"], "min_experience": 3.0}


def test_parse_job_description_reports_llm_failure(client, signup_org, monkeypatch):
    admin = signup_org()
    from routers import jobs

    def _boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(jobs.llm, "generate", _boom)
    resp = client.post(
        "/recruiter/jobs/parse", json={"title": "Backend Engineer", "description": "..."}, headers=_auth(admin["token"]),
    )
    assert resp.status_code == 502
