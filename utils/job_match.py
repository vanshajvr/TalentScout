"""
Deterministic candidate-to-job fit scoring.

Deliberately not an LLM call: a recruiter needs to see *why* a candidate scored what
they did, the same inputs must always produce the same score, and the logic has to be
unit-testable. The LLM's only job in this feature is turning a free-text JD into the
structured skill lists this module consumes (see routers/jobs.py) — and the recruiter
reviews those lists before they're saved.
"""

import re

MUST_HAVE_WEIGHT = 70
NICE_TO_HAVE_WEIGHT = 20
EXPERIENCE_WEIGHT = 10

# Resume-text matching is skipped for very short skill names — "Go", "R", "C" would
# otherwise match ordinary words ("go-to", "R&D") and inflate scores. Those skills
# still match through the candidate's confirmed tech stack.
MIN_RESUME_TEXT_MATCH_LENGTH = 3

_ALIASES = {
    "node": "nodejs",
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "reactjs": "react",
    "amazonwebservices": "aws",
}


def normalize_skill(skill: str) -> str:
    """'Node.js' -> 'nodejs', 'React.js' -> 'react', 'C++' -> 'c++'. Keeps + and # so
    C, C++ and C# stay distinct."""
    key = re.sub(r"[^a-z0-9+#]", "", skill.lower())
    return _ALIASES.get(key, key)


def clean_skill_list(skills: list | None) -> list[str]:
    """Trims, drops empties, and de-duplicates by normalized name (first spelling wins)."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in skills or []:
        if not isinstance(raw, str):
            continue
        skill = raw.strip()[:80]
        key = normalize_skill(skill)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(skill)
    return result


def split_requirements(must_have: list | None, nice_to_have: list | None) -> tuple[list[str], list[str]]:
    """Cleans both lists and drops any nice-to-have that's already a must-have."""
    must = clean_skill_list(must_have)
    must_keys = {normalize_skill(s) for s in must}
    nice = [s for s in clean_skill_list(nice_to_have) if normalize_skill(s) not in must_keys]
    return must, nice


def _mentioned_in_text(skill: str, text_lower: str) -> bool:
    needle = skill.strip().lower()
    if len(needle) < MIN_RESUME_TEXT_MATCH_LENGTH:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text_lower) is not None


def _match_skills(required: list[str], stack_keys: set[str], text_lower: str) -> tuple[list[dict], list[str]]:
    matched, missing = [], []
    for skill in required:
        if normalize_skill(skill) in stack_keys:
            matched.append({"skill": skill, "source": "tech_stack"})
        elif _mentioned_in_text(skill, text_lower):
            matched.append({"skill": skill, "source": "resume_text"})
        else:
            missing.append(skill)
    return matched, missing


def _format_years(value: float) -> str:
    return f"{value:g} yr" + ("" if value == 1 else "s")


def compute_fit(
    must_have: list[str],
    nice_to_have: list[str],
    min_experience: float | None,
    candidate_tech_stack: list[str] | None,
    candidate_experience: float | None,
    resume_text: str | None,
) -> dict:
    """Returns {"score": 0-100 | None, "summary": str, "details": dict}.

    Each requirement group (must-haves, nice-to-haves, minimum experience) contributes
    its weight only if the job actually specifies it — a job with no nice-to-haves is
    scored out of must-haves + experience, not penalized for an empty list. Returns a
    None score when the job specifies nothing to score against."""
    stack_keys = {normalize_skill(s) for s in (candidate_tech_stack or []) if isinstance(s, str)}
    text_lower = (resume_text or "").lower()

    must_matched, must_missing = _match_skills(must_have, stack_keys, text_lower)
    nice_matched, nice_missing = _match_skills(nice_to_have, stack_keys, text_lower)

    earned = 0.0
    possible = 0
    summary_parts = []

    if must_have:
        possible += MUST_HAVE_WEIGHT
        earned += MUST_HAVE_WEIGHT * len(must_matched) / len(must_have)
        part = f"Meets {len(must_matched)}/{len(must_have)} must-haves"
        if must_missing:
            part += f" (missing {', '.join(must_missing)})"
        summary_parts.append(part)

    if nice_to_have:
        possible += NICE_TO_HAVE_WEIGHT
        earned += NICE_TO_HAVE_WEIGHT * len(nice_matched) / len(nice_to_have)
        summary_parts.append(f"{len(nice_matched)}/{len(nice_to_have)} nice-to-haves")

    experience_detail = None
    if min_experience is not None and min_experience > 0:
        possible += EXPERIENCE_WEIGHT
        meets = candidate_experience is not None and candidate_experience >= min_experience
        if candidate_experience is not None:
            earned += EXPERIENCE_WEIGHT * min(candidate_experience / min_experience, 1.0)
            summary_parts.append(f"{_format_years(candidate_experience)} vs {_format_years(min_experience)} required")
        else:
            summary_parts.append(f"experience unknown ({_format_years(min_experience)} required)")
        experience_detail = {"required": min_experience, "candidate": candidate_experience, "meets": meets}

    score = round(100 * earned / possible) if possible else None

    return {
        "score": score,
        "summary": " · ".join(summary_parts) if summary_parts else "This job lists no requirements to score against",
        "details": {
            "must_have": {"matched": must_matched, "missing": must_missing},
            "nice_to_have": {"matched": nice_matched, "missing": nice_missing},
            "experience": experience_detail,
        },
    }


def apply_job_fit(candidate, job) -> None:
    """Computes fit for a Candidate row against a JobOpening row and writes it onto the
    candidate (caller commits). Clears any stale fit if the candidate has no job."""
    if job is None:
        candidate.fit_score = None
        candidate.fit_summary = None
        candidate.fit_details = None
        return
    fit = compute_fit(
        must_have=job.must_have_skills or [],
        nice_to_have=job.nice_to_have_skills or [],
        min_experience=job.min_experience,
        candidate_tech_stack=candidate.tech_stack,
        candidate_experience=candidate.experience,
        resume_text=candidate.resume_text,
    )
    candidate.fit_score = fit["score"]
    candidate.fit_summary = fit["summary"]
    candidate.fit_details = fit["details"]
