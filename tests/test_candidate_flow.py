"""
Candidate intake flow end to end, plus the state and timing machinery around it:
persisted conversation state, the inactivity sweep, and the DB-backed rate limiter.
"""

import threading
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from db.database import SessionLocal
from db.models import Candidate, CandidateSession, Organization, RateLimitEvent
from utils.rate_limit import check_rate_limit


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _org_slug(client, token):
    return client.get("/recruiter/org", headers=_auth(token)).json()["org_slug"]


@pytest.fixture
def fake_resume_extraction(monkeypatch):
    from routers import candidate
    monkeypatch.setattr(candidate, "extract_resume_text", lambda path, ext: "Python developer, 3 years")
    monkeypatch.setattr(candidate, "_extract_resume_fields", lambda text, db, sid: {
        "email": f"cand+{uuid.uuid4().hex[:8]}@gmail.com", "phone": "+91 98765 43210", "location": "Pune",
        "experience": "3", "role": "Backend Engineer", "tech_stack": ["Python", "SQL"],
        "education": "B.Tech", "linkedin": None, "github": None,
    })


def test_full_intake_flow_persists_state_at_every_step(client, signup_org, db_session, fake_resume_extraction):
    admin = signup_org()
    start = client.post("/sessions", params={"org": _org_slug(client, admin["token"])})
    assert start.status_code == 200, start.text
    sid = start.json()["session_id"]

    def stored_step():
        db_session.expire_all()
        return db_session.get(CandidateSession, uuid.UUID(sid)).conversation_state["step"]

    assert stored_step() == "greeting"
    assert client.post(f"/sessions/{sid}/messages", json={"text": "hi"}).json()["step"] == "ask_name"
    assert client.post(f"/sessions/{sid}/messages", json={"text": "Priya Raman"}).json()["step"] == "upload_resume"
    assert stored_step() == "upload_resume"

    upload = client.post(f"/sessions/{sid}/resume", files={"file": ("cv.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert upload.status_code == 200, upload.text
    assert stored_step() == "confirm_resume_data"
    extracted = upload.json()["extracted"]

    confirm = client.post(f"/sessions/{sid}/resume/confirm", json={**extracted, "experience": "3"})
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["step"] == "mcq_assessment"
    assert stored_step() == "mcq_assessment"

    db_session.expire_all()
    session_row = db_session.get(CandidateSession, uuid.UUID(sid))
    candidate = db_session.get(Candidate, session_row.candidate_id)
    assert (candidate.name, candidate.email, candidate.tech_stack) == ("Priya Raman", extracted["email"], ["Python", "SQL"])
    assert session_row.conversation_state["candidate"]["name"] == "Priya Raman"


def test_session_from_before_state_persistence_still_works(client, signup_org, db_session):
    # Rows created before conversation_state existed have it null — they must resume
    # from current_step instead of 404ing.
    admin = signup_org()
    org = db_session.query(Organization).filter(Organization.slug == _org_slug(client, admin["token"])).first()
    candidate = Candidate(org_id=org.id)
    db_session.add(candidate)
    db_session.flush()
    legacy = CandidateSession(candidate_id=candidate.id, current_step="ask_name", conversation_state=None)
    db_session.add(legacy)
    db_session.commit()

    resp = client.post(f"/sessions/{legacy.id}/messages", json={"text": "Arjun Nair"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["step"] == "upload_resume"


def test_sweep_uses_last_activity_and_activity_reopens_swept_sessions(client, signup_org, db_session):
    admin = signup_org()
    org = db_session.query(Organization).filter(Organization.slug == _org_slug(client, admin["token"])).first()
    three_days_ago = datetime.utcnow() - timedelta(days=3)

    def add_session(last_activity):
        c = Candidate(org_id=org.id)
        db_session.add(c)
        db_session.flush()
        s = CandidateSession(candidate_id=c.id, current_step="ask_name", started_at=three_days_ago,
                             last_activity_at=last_activity, conversation_state={"step": "ask_name"})
        db_session.add(s)
        db_session.commit()
        return s.id

    still_working = add_session(datetime.utcnow() - timedelta(hours=1))
    gone_quiet = add_session(None)

    client.get("/recruiter/overview", headers=_auth(admin["token"]))
    db_session.expire_all()
    assert db_session.get(CandidateSession, still_working).status == "in_progress"
    assert db_session.get(CandidateSession, gone_quiet).status == "abandoned"

    # The quiet candidate comes back: the session reopens and the sweep leaves it alone.
    assert client.post(f"/sessions/{gone_quiet}/messages", json={"text": "Kevin Osei"}).status_code == 200
    client.get("/recruiter/overview", headers=_auth(admin["token"]))
    db_session.expire_all()
    assert db_session.get(CandidateSession, gone_quiet).status == "in_progress"


def test_rate_limit_counts_within_window_and_expires(db_session):
    key = f"test:{uuid.uuid4().hex}"
    for _ in range(3):
        check_rate_limit(db_session, key, max_requests=3, window_minutes=60)
    with pytest.raises(HTTPException) as exc:
        check_rate_limit(db_session, key, max_requests=3, window_minutes=60)
    assert exc.value.status_code == 429

    # Age every event out of the window: the key is usable again, and the old rows are cleaned up.
    db_session.query(RateLimitEvent).filter(RateLimitEvent.key == key).update(
        {"created_at": datetime.utcnow() - timedelta(hours=2)}, synchronize_session=False,
    )
    db_session.commit()
    check_rate_limit(db_session, key, max_requests=3, window_minutes=60)
    assert db_session.query(RateLimitEvent).filter(RateLimitEvent.key == key).count() == 1


def test_rate_limit_holds_under_concurrent_requests():
    # 8 simultaneous requests against a limit of 3: exactly 3 may pass. Without the
    # advisory lock, several can read "under the limit" before any of them records itself.
    key = f"test:{uuid.uuid4().hex}"
    results: list[int] = []
    barrier = threading.Barrier(8)

    def attempt():
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))  # connect before the race starts
            barrier.wait()
            check_rate_limit(db, key, max_requests=3, window_minutes=60)
            results.append(200)
        except HTTPException as e:
            results.append(e.status_code)
        finally:
            db.close()

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(results) == [200] * 3 + [429] * 5
