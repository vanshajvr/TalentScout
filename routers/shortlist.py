import csv
import io
import uuid

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as SQLASession

from db.database import get_db
from db.models import Candidate, CandidateSession, MCQAnswer, MCQAssessment, Recruiter
from routers.recruiter import _csv_safe, _job_titles, _sweep_stale_sessions
from utils.auth import require_recruiter
from utils.judge import overall
from utils.shortlist import (
    COMPONENTS, composite_score, integrity_flags, normalize_weights, summary_line,
    technical_component, written_component,
)

router = APIRouter(prefix="/recruiter/shortlist")


def _scoped_candidates(q, job_id: str | None):
    if job_id == "none":
        return q.filter(Candidate.job_id.is_(None))
    if job_id:
        try:
            return q.filter(Candidate.job_id == uuid.UUID(job_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid job_id")
    return q


def _build_shortlist(db: SQLASession, org_id, job_id: str | None, weights: dict[str, float]) -> dict:
    # Only finished assessments are ranked — a half-done one would rank on whatever
    # it has so far, which says more about timing than about the candidate.
    rows = _scoped_candidates(
        db.query(Candidate, MCQAssessment)
        .join(CandidateSession, CandidateSession.candidate_id == Candidate.id)
        .join(MCQAssessment, MCQAssessment.session_id == CandidateSession.id)
        .filter(Candidate.org_id == org_id, MCQAssessment.status == "completed"),
        job_id,
    ).all()
    in_scope = _scoped_candidates(db.query(Candidate.id).filter(Candidate.org_id == org_id), job_id).count()

    answers_by_assessment: dict = {}
    if rows:
        for a in (
            db.query(MCQAnswer)
            .filter(MCQAnswer.assessment_id.in_([assessment.id for _, assessment in rows]))
            .order_by(MCQAnswer.question_index)
            .all()
        ):
            answers_by_assessment.setdefault(a.assessment_id, []).append(a)

    job_titles = _job_titles(db, org_id)
    entries = []
    for candidate, assessment in rows:
        answers = answers_by_assessment.get(assessment.id, [])
        technical = [a for a in answers if a.question_type == "technical"]
        technical_correct = sum(1 for a in technical if a.is_correct)
        written = [a for a in answers if a.question_type == "open_text" and a.answered_at is not None]
        written_overalls = [o for o in (overall(a.override_scores or a.judge_scores) for a in written) if o is not None]
        written_average = round(sum(written_overalls) / len(written_overalls), 1) if written_overalls else None

        components = {
            "fit": float(candidate.fit_score) if candidate.fit_score is not None else None,
            "technical": technical_component(technical_correct, len(technical)),
            "written": written_component(written_average),
        }
        result = composite_score(components, weights)
        entries.append({
            "candidate_id": str(candidate.id),
            "name": candidate.name,
            "email": candidate.email,
            "job_title": job_titles.get(candidate.job_id),
            "score": result["score"],
            "partial": result["partial"],
            "components": {c: round(v) if v is not None else None for c, v in components.items()},
            "technical": {
                "correct": technical_correct,
                "total": len(technical),
                "final_tier": technical[-1].difficulty_tier if technical else None,
            },
            "written": {"average": written_average, "pending": len(written) - len(written_overalls)},
            "fit_summary": candidate.fit_summary,
            "flags": integrity_flags(
                assessment.tab_switch_count, assessment.fullscreen_exit_count,
                sum(1 for a in written if a.judge_manipulation),
            ),
            "summary": summary_line(
                candidate.fit_score, candidate.fit_summary, technical_correct, len(technical),
                technical[-1].difficulty_tier if technical else None,
                written_average, len(written) - len(written_overalls),
            ),
            "completed_at": assessment.completed_at.isoformat() if assessment.completed_at else None,
        })

    # Best composite first; ties go to the stronger technical result, then whoever
    # finished first. Unscorable rows (no weighted component at all) go last.
    entries.sort(key=lambda e: (
        e["score"] is None,
        -(e["score"] or 0),
        -(e["components"]["technical"] or 0),
        e["completed_at"] or "",
    ))
    for rank, e in enumerate(entries, start=1):
        e["rank"] = rank

    return {
        "weights": weights,
        "ranked": len(entries),
        "not_yet_completed": in_scope - len(entries),
        "candidates": entries,
    }


@router.get("")
def get_shortlist(
    job_id: str | None = None,
    w_fit: float | None = None, w_technical: float | None = None, w_written: float | None = None,
    limit: int | None = None,
    format: str = "json",
    db: SQLASession = Depends(get_db),
    recruiter: Recruiter = Depends(require_recruiter),
):
    if format not in ("json", "csv"):
        raise HTTPException(status_code=400, detail="format must be 'json' or 'csv'")
    if limit is not None and not 1 <= limit <= 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")

    _sweep_stale_sessions(db, recruiter.org_id)
    # An omitted weight means "use the default", which is what a missing key means
    # to normalize_weights — so drop the Nones rather than passing them through.
    given = {"fit": w_fit, "technical": w_technical, "written": w_written}
    weights = normalize_weights({c: w for c, w in given.items() if w is not None})
    shortlist = _build_shortlist(db, recruiter.org_id, job_id, weights)
    if limit is not None:
        shortlist["candidates"] = shortlist["candidates"][:limit]

    if format == "json":
        return shortlist

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Rank", "Name", "Email", "Job", "Score", "Partial",
        *[f"{c.title()} (0-100)" for c in COMPONENTS],
        "Technical", "Final Difficulty", "Written Avg (1-5)", "Flags", "Summary",
    ])
    for e in shortlist["candidates"]:
        writer.writerow([
            e["rank"], _csv_safe(e["name"]), _csv_safe(e["email"]), _csv_safe(e["job_title"] or ""),
            e["score"] if e["score"] is not None else "", "yes" if e["partial"] else "",
            *[e["components"][c] if e["components"][c] is not None else "" for c in COMPONENTS],
            f"{e['technical']['correct']}/{e['technical']['total']}", e["technical"]["final_tier"] or "",
            e["written"]["average"] if e["written"]["average"] is not None else "",
            _csv_safe("; ".join(f["label"] for f in e["flags"])), _csv_safe(e["summary"]),
        ])
    return StreamingResponse(
        iter([buffer.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=shortlist.csv"},
    )
