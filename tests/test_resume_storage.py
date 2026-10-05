"""
Resume files live in Postgres (resume_files), not on local disk: upload, download,
org isolation, cascade on delete, header safety, and the legacy on-disk fallback.
"""

import uuid
from urllib.parse import unquote

from db.models import Candidate, Organization, ResumeFile
from tests.test_candidate_flow import fake_resume_extraction  # noqa: F401  (pytest fixture)

PDF_BYTES = b"%PDF-1.4\n" + bytes(range(256)) * 4  # binary content must round-trip exactly


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _org_slug(client, token):
    return client.get("/recruiter/org", headers=_auth(token)).json()["org_slug"]


def _upload(client, token, filename="Priya Raman CV.pdf"):
    sid = client.post("/sessions", params={"org": _org_slug(client, token)}).json()["session_id"]
    client.post(f"/sessions/{sid}/messages", json={"text": "hi"})
    client.post(f"/sessions/{sid}/messages", json={"text": "Priya Raman"})
    resp = client.post(f"/sessions/{sid}/resume", files={"file": (filename, PDF_BYTES, "application/pdf")})
    assert resp.status_code == 200, resp.text
    return sid


def _candidate_id(client, token):
    return client.get("/recruiter/candidates", headers=_auth(token)).json()[0]["id"]


def test_upload_is_stored_in_postgres_and_downloads_byte_for_byte(client, signup_org, db_session, fake_resume_extraction):
    admin = signup_org()
    _upload(client, admin["token"])
    cid = _candidate_id(client, admin["token"])

    stored = db_session.query(ResumeFile).filter(ResumeFile.candidate_id == uuid.UUID(cid)).one()
    assert stored.data == PDF_BYTES and stored.size_bytes == len(PDF_BYTES)
    assert db_session.get(Candidate, uuid.UUID(cid)).resume_path is None  # nothing written to disk

    resp = client.get(f"/recruiter/candidates/{cid}/resume", headers=_auth(admin["token"]))
    assert resp.status_code == 200
    assert resp.content == PDF_BYTES
    assert resp.headers["content-type"] == "application/pdf"
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")
    assert unquote(disposition.split("''", 1)[1]) == "Priya Raman CV.pdf"


def test_hostile_filename_cannot_break_the_header(client, signup_org, fake_resume_extraction):
    admin = signup_org()
    _upload(client, admin["token"], filename='cv"; filename="evil.exe\r\nX-Injected: 1.pdf')
    cid = _candidate_id(client, admin["token"])

    resp = client.get(f"/recruiter/candidates/{cid}/resume", headers=_auth(admin["token"]))
    assert resp.status_code == 200
    assert "x-injected" not in resp.headers
    assert '"' not in resp.headers["content-disposition"].split("''", 1)[1]


def test_other_org_cannot_download(client, signup_org, fake_resume_extraction):
    org_a = signup_org()
    org_b = signup_org()
    _upload(client, org_b["token"])
    cid_b = _candidate_id(client, org_b["token"])

    assert client.get(f"/recruiter/candidates/{cid_b}/resume", headers=_auth(org_a["token"])).status_code == 404


def test_deleting_candidate_deletes_the_file(client, signup_org, db_session, fake_resume_extraction):
    admin = signup_org()
    _upload(client, admin["token"])
    cid = _candidate_id(client, admin["token"])

    resp = client.post("/recruiter/candidates/delete", json={"candidate_ids": [cid]}, headers=_auth(admin["token"]))
    assert resp.json() == {"deleted": 1}
    db_session.expire_all()
    assert db_session.query(ResumeFile).filter(ResumeFile.candidate_id == uuid.UUID(cid)).count() == 0


def test_legacy_on_disk_resume_still_downloads(client, signup_org, db_session, tmp_path):
    admin = signup_org()
    org = db_session.query(Organization).filter(Organization.slug == _org_slug(client, admin["token"])).first()
    legacy_file = tmp_path / "old.pdf"
    legacy_file.write_bytes(PDF_BYTES)
    present = Candidate(org_id=org.id, resume_filename="old.pdf", resume_path=str(legacy_file))
    gone = Candidate(org_id=org.id, resume_filename="lost.pdf", resume_path=str(tmp_path / "wiped-by-deploy.pdf"))
    db_session.add_all([present, gone])
    db_session.commit()

    resp = client.get(f"/recruiter/candidates/{present.id}/resume", headers=_auth(admin["token"]))
    assert resp.status_code == 200 and resp.content == PDF_BYTES
    assert client.get(f"/recruiter/candidates/{gone.id}/resume", headers=_auth(admin["token"])).status_code == 404
