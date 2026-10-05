"""
Shortlist: composite scoring (pure) and the /recruiter/shortlist endpoint — ranking,
weights, partial scores, flags-never-deduct, completion filtering, org isolation, CSV.
"""

import uuid
from datetime import datetime

from db.models import Candidate, CandidateSession, JobOpening, MCQAnswer, MCQAssessment, Organization
from utils import shortlist


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- unit

def test_written_component_maps_1_to_5_onto_0_to_100():
    assert shortlist.written_component(1) == 0
    assert shortlist.written_component(3) == 50
    assert shortlist.written_component(5) == 100
    assert shortlist.written_component(None) is None


def test_composite_uses_weights():
    w = shortlist.normalize_weights(None)  # 40 / 40 / 20
    result = shortlist.composite_score({"fit": 100, "technical": 50, "written": 0}, w)
    assert result == {"score": 60, "partial": False, "used": ["fit", "technical", "written"]}


def test_missing_component_is_renormalized_not_zeroed():
    w = shortlist.normalize_weights(None)
    result = shortlist.composite_score({"fit": None, "technical": 80, "written": 80}, w)
    assert result["score"] == 80  # not (0*40 + 80*40 + 80*20) / 100 = 48
    assert result["partial"] is True


def test_zero_weight_component_is_ignored_and_not_partial():
    w = shortlist.normalize_weights({"fit": 0})
    result = shortlist.composite_score({"fit": None, "technical": 70, "written": 70}, w)
    assert result == {"score": 70, "partial": False, "used": ["technical", "written"]}


def test_all_zero_weights_fall_back_to_defaults():
    assert shortlist.normalize_weights({"fit": 0, "technical": 0, "written": 0}) == {"fit": 40.0, "technical": 40.0, "written": 20.0}


def test_weights_are_clamped():
    assert shortlist.normalize_weights({"fit": 500, "technical": -5})["fit"] == 100.0
    assert shortlist.normalize_weights({"fit": 500, "technical": -5})["technical"] == 0.0


def test_summary_line_pulls_missing_skills_from_fit_summary():
    line = shortlist.summary_line(
        60, "Meets 2/3 must-haves (missing Kubernetes) · 1/2 nice-to-haves", 7, 10, "advanced", 4.2, 0,
    )
    assert line == "Fit 60 (missing Kubernetes) · Technical 7/10, ended at advanced · Written 4.2/5"


# --------------------------------------------------------------------------- API

def _org(client, db_session, token):
    slug = client.get("/recruiter/org", headers=_auth(token)).json()["org_slug"]
    return db_session.query(Organization).filter(Organization.slug == slug).first()


def _add_candidate(
    db_session, org_id, name, *, technical_correct=5, technical_total=10, written_scores=None,
    fit_score=None, job_id=None, completed=True, tab_switches=0, manipulation=False,
):
    candidate = Candidate(org_id=org_id, name=name, job_id=job_id, fit_score=fit_score,
                          fit_summary=f"Meets fit {fit_score}" if fit_score is not None else None)
    db_session.add(candidate)
    db_session.flush()
    session_row = CandidateSession(candidate_id=candidate.id, current_step="end" if completed else "mcq_assessment",
                                   status="completed" if completed else "in_progress")
    db_session.add(session_row)
    db_session.flush()
    assessment = MCQAssessment(session_id=session_row.id, status="completed" if completed else "in_progress",
                               tab_switch_count=tab_switches, completed_at=datetime.utcnow() if completed else None)
    db_session.add(assessment)
    db_session.flush()
    now = datetime.utcnow()
    for i in range(technical_total):
        db_session.add(MCQAnswer(
            assessment_id=assessment.id, question_index=i, question_type="technical", question_text="Q",
            is_correct=i < technical_correct, difficulty_tier="applied", question_started_at=now, answered_at=now,
        ))
    for j, scores in enumerate(written_scores or []):
        db_session.add(MCQAnswer(
            assessment_id=assessment.id, question_index=100 + j, question_type="open_text", question_text="W",
            text_response="answer", question_started_at=now, answered_at=now,
            judge_scores=scores, judge_manipulation=manipulation,
        ))
    db_session.commit()
    return candidate


FIVES = {"relevance": 5, "specificity": 5, "clarity": 5}
THREES = {"relevance": 3, "specificity": 3, "clarity": 3}


def test_shortlist_ranks_completed_candidates_and_excludes_incomplete(client, signup_org, db_session):
    admin = signup_org()
    org = _org(client, db_session, admin["token"])
    _add_candidate(db_session, org.id, "Middle", technical_correct=6, written_scores=[THREES])
    _add_candidate(db_session, org.id, "Top", technical_correct=9, written_scores=[FIVES])
    _add_candidate(db_session, org.id, "Bottom", technical_correct=2, written_scores=[THREES])
    _add_candidate(db_session, org.id, "Unfinished", technical_correct=10, completed=False)

    data = client.get("/recruiter/shortlist", headers=_auth(admin["token"])).json()
    assert [c["name"] for c in data["candidates"]] == ["Top", "Middle", "Bottom"]
    assert [c["rank"] for c in data["candidates"]] == [1, 2, 3]
    assert (data["ranked"], data["not_yet_completed"]) == (3, 1)

    top = data["candidates"][0]
    # No job -> fit missing -> partial, renormalized over technical (40) + written (20)
    assert top["partial"] is True
    assert top["components"] == {"fit": None, "technical": 90, "written": 100}
    assert top["score"] == round((90 * 40 + 100 * 20) / 60)


def test_weights_change_the_ranking(client, signup_org, db_session):
    admin = signup_org()
    org = _org(client, db_session, admin["token"])
    _add_candidate(db_session, org.id, "Coder", technical_correct=10, written_scores=[THREES])
    _add_candidate(db_session, org.id, "Writer", technical_correct=5, written_scores=[FIVES])

    default = client.get("/recruiter/shortlist", headers=_auth(admin["token"])).json()
    assert default["candidates"][0]["name"] == "Coder"

    writing_heavy = client.get(
        "/recruiter/shortlist", params={"w_technical": 10, "w_written": 90}, headers=_auth(admin["token"]),
    ).json()
    assert writing_heavy["candidates"][0]["name"] == "Writer"
    assert writing_heavy["weights"] == {"fit": 40.0, "technical": 10.0, "written": 90.0}


def test_integrity_flags_are_shown_but_never_lower_the_score(client, signup_org, db_session):
    admin = signup_org()
    org = _org(client, db_session, admin["token"])
    _add_candidate(db_session, org.id, "Clean", technical_correct=8, written_scores=[FIVES])
    _add_candidate(db_session, org.id, "Flagged", technical_correct=8, written_scores=[FIVES],
                   tab_switches=3, manipulation=True)

    rows = {c["name"]: c for c in client.get("/recruiter/shortlist", headers=_auth(admin["token"])).json()["candidates"]}
    assert rows["Clean"]["score"] == rows["Flagged"]["score"]
    assert rows["Clean"]["flags"] == []
    assert {f["type"] for f in rows["Flagged"]["flags"]} == {"tab_switch", "manipulation"}


def test_ungraded_written_answers_are_partial_not_zero(client, signup_org, db_session):
    admin = signup_org()
    org = _org(client, db_session, admin["token"])
    _add_candidate(db_session, org.id, "Pending", technical_correct=8, written_scores=[None])

    row = client.get("/recruiter/shortlist", headers=_auth(admin["token"])).json()["candidates"][0]
    assert row["components"]["written"] is None
    assert row["written"]["pending"] == 1
    assert row["score"] == 80
    assert "not graded yet" in row["summary"]


def test_job_filter_includes_fit_and_scopes_candidates(client, signup_org, db_session):
    admin = signup_org()
    org = _org(client, db_session, admin["token"])
    job = JobOpening(org_id=org.id, title="Backend Engineer", description="...", must_have_skills=["Python"])
    db_session.add(job)
    db_session.commit()
    _add_candidate(db_session, org.id, "Applied", technical_correct=5, written_scores=[THREES], fit_score=100, job_id=job.id)
    _add_candidate(db_session, org.id, "General", technical_correct=10, written_scores=[FIVES])

    data = client.get("/recruiter/shortlist", params={"job_id": str(job.id)}, headers=_auth(admin["token"])).json()
    assert [c["name"] for c in data["candidates"]] == ["Applied"]
    row = data["candidates"][0]
    assert row["partial"] is False
    assert row["job_title"] == "Backend Engineer"
    assert row["score"] == round((100 * 40 + 50 * 40 + 50 * 20) / 100)

    assert client.get("/recruiter/shortlist", params={"job_id": "nope"}, headers=_auth(admin["token"])).status_code == 400


def test_shortlist_is_org_isolated(client, signup_org, db_session):
    org_a = signup_org()
    org_b = signup_org()
    _add_candidate(db_session, _org(client, db_session, org_b["token"]).id, "Other Org", written_scores=[FIVES])

    data = client.get("/recruiter/shortlist", headers=_auth(org_a["token"])).json()
    assert data["candidates"] == [] and data["not_yet_completed"] == 0


def test_shortlist_csv_export_neutralizes_formulas(client, signup_org, db_session):
    admin = signup_org()
    org = _org(client, db_session, admin["token"])
    _add_candidate(db_session, org.id, "=HYPERLINK(\"x\")", technical_correct=7, written_scores=[FIVES])

    resp = client.get("/recruiter/shortlist", params={"format": "csv"}, headers=_auth(admin["token"]))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("Rank,Name,Email")
    assert "'=HYPERLINK" in lines[1]
