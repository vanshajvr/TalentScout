import logging
import uuid

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, JobOpening, Recruiter
from llm.groq_llm import GroqLLM
from utils.auth import require_recruiter
from utils.extraction import MAX_SKILLS_PER_LIST, extract_job_requirements
from utils.job_match import apply_job_fit, split_requirements
from utils.rate_limit import check_rate_limit

router = APIRouter(prefix="/recruiter/jobs")
logger = logging.getLogger(__name__)

llm = GroqLLM()


class ParseJobRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=20000)


class CreateJobRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=20000)
    must_have_skills: list[str] = Field(default_factory=list, max_length=MAX_SKILLS_PER_LIST)
    nice_to_have_skills: list[str] = Field(default_factory=list, max_length=MAX_SKILLS_PER_LIST)
    min_experience: float | None = Field(default=None, ge=0, le=50)


class UpdateJobRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=20000)
    must_have_skills: list[str] | None = Field(default=None, max_length=MAX_SKILLS_PER_LIST)
    nice_to_have_skills: list[str] | None = Field(default=None, max_length=MAX_SKILLS_PER_LIST)
    min_experience: float | None = Field(default=None, ge=0, le=50)
    clear_min_experience: bool = False  # min_experience=None alone means "unchanged"
    status: str | None = None  # open | closed


def _job_payload(job: JobOpening, candidate_count: int = 0) -> dict:
    return {
        "id": str(job.id),
        "title": job.title,
        "description": job.description,
        "must_have_skills": job.must_have_skills or [],
        "nice_to_have_skills": job.nice_to_have_skills or [],
        "min_experience": job.min_experience,
        "status": job.status,
        "candidate_count": candidate_count,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _get_org_job_or_404(db: SQLASession, job_id: str, org_id) -> JobOpening:
    try:
        jid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found")
    job = db.get(JobOpening, jid)
    if job is None or job.org_id != org_id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/parse")
def parse_job_description(
    body: ParseJobRequest, db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter),
):
    """LLM-assisted extraction of structured requirements from a pasted JD. Returns a
    draft only — nothing is saved until the recruiter reviews it and calls POST /."""
    check_rate_limit(db, f"parse_jd:{recruiter.id}", max_requests=30, window_minutes=60)

    try:
        return extract_job_requirements(llm, body.title, body.description)
    except Exception as e:
        logger.warning("JD extraction failed: %s", e)
        raise HTTPException(status_code=502, detail="Couldn't extract requirements automatically — please enter them manually.")


@router.get("")
def list_jobs(db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter)):
    jobs = (
        db.query(JobOpening)
        .filter(JobOpening.org_id == recruiter.org_id)
        .order_by(JobOpening.created_at.desc())
        .all()
    )
    counts = dict(
        db.query(Candidate.job_id, func.count(Candidate.id))
        .filter(Candidate.org_id == recruiter.org_id, Candidate.job_id.isnot(None))
        .group_by(Candidate.job_id)
        .all()
    )
    return [_job_payload(j, counts.get(j.id, 0)) for j in jobs]


@router.post("")
def create_job(body: CreateJobRequest, db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter)):
    must, nice = split_requirements(body.must_have_skills, body.nice_to_have_skills)
    job = JobOpening(
        org_id=recruiter.org_id,
        title=body.title.strip(),
        description=body.description.strip(),
        must_have_skills=must,
        nice_to_have_skills=nice,
        min_experience=body.min_experience,
        created_by=recruiter.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _job_payload(job)


@router.patch("/{job_id}")
def update_job(
    job_id: str, body: UpdateJobRequest,
    db: SQLASession = Depends(get_db), recruiter: Recruiter = Depends(require_recruiter),
):
    job = _get_org_job_or_404(db, job_id, recruiter.org_id)

    if body.status is not None:
        if body.status not in ("open", "closed"):
            raise HTTPException(status_code=400, detail="status must be 'open' or 'closed'")
        job.status = body.status
    if body.title is not None:
        job.title = body.title.strip()
    if body.description is not None:
        job.description = body.description.strip()

    requirements_changed = (
        body.must_have_skills is not None or body.nice_to_have_skills is not None
        or body.min_experience is not None or body.clear_min_experience
    )
    if requirements_changed:
        must, nice = split_requirements(
            body.must_have_skills if body.must_have_skills is not None else job.must_have_skills,
            body.nice_to_have_skills if body.nice_to_have_skills is not None else job.nice_to_have_skills,
        )
        job.must_have_skills = must
        job.nice_to_have_skills = nice
        if body.clear_min_experience:
            job.min_experience = None
        elif body.min_experience is not None:
            job.min_experience = body.min_experience

        # Re-score everyone already scored against this job, so the ranking always
        # reflects the job's current requirements. Candidates who haven't confirmed
        # their resume yet (no fit_summary) get scored when they do.
        for candidate in db.query(Candidate).filter(Candidate.job_id == job.id, Candidate.fit_summary.isnot(None)).all():
            apply_job_fit(candidate, job)

    db.commit()
    count = db.query(Candidate).filter(Candidate.job_id == job.id).count()
    return _job_payload(job, count)
