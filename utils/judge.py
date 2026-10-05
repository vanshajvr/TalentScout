"""
LLM-as-judge for the open-text screening answers.

Pure (no DB/FastAPI) so the same function serves the background grading in
routers/mcq.py, the recruiter's "grade now" endpoint, and the judge eval suite in
evals/run.py. Raises on LLM or validation failure — callers decide what that means.

The judge's output is advisory: recruiters see the rationale next to the answer and
can override any score (see MCQAnswer.override_scores).
"""

import hashlib
import re

from llm.base import BaseLLM
from utils.constants import MCQ_OPEN_TEXT_MAX_CHARS
from utils.extraction import load_prompt
from utils.llm_json import parse_llm_json

JUDGE_PROMPT_PATH = "prompts/open_text_judge_prompt.txt"
RUBRIC_DIMENSIONS = ("relevance", "specificity", "clarity")
MAX_RATIONALE_CHARS = 600

_ANSWER_MARKER_RE = re.compile(r"<\s*/?\s*candidate_answer\s*>", re.IGNORECASE)


def judge_prompt_sha() -> str:
    return hashlib.sha256(load_prompt(JUDGE_PROMPT_PATH).encode()).hexdigest()[:12]


def _strip_markers(text: str) -> str:
    """A candidate could type "</candidate_answer>" to close the data block early and
    smuggle text in as if it were part of the rubric. Removing the markers keeps the
    whole answer inside the block."""
    return _ANSWER_MARKER_RE.sub("", text)


def _valid_score(value) -> int:
    if isinstance(value, bool):
        raise ValueError("score must be a number")
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"score must be a number: {value!r}")
    if score != int(score) or not 1 <= score <= 5:
        raise ValueError(f"score out of range: {value!r}")
    return int(score)


def overall(scores: dict | None) -> float | None:
    if not scores:
        return None
    return round(sum(scores[d] for d in RUBRIC_DIMENSIONS) / len(RUBRIC_DIMENSIONS), 2)


def validate_scores(scores) -> dict:
    """Shared by the judge's output and the recruiter override endpoint."""
    if not isinstance(scores, dict):
        raise ValueError("scores must be an object")
    return {d: _valid_score(scores.get(d)) for d in RUBRIC_DIMENSIONS}


def judge_open_text(llm: BaseLLM, question: str, answer: str, role: str | None) -> dict:
    """Returns {"scores": {relevance, specificity, clarity}, "rationale": str,
    "manipulation_attempt": bool}. The flag is surfaced to the recruiter rather than
    folded into the scores, so a manipulation attempt is visible, not just penalized."""
    prompt = load_prompt(JUDGE_PROMPT_PATH).format(
        role=role or "unspecified",
        question=question,
        answer=_strip_markers(answer)[:MCQ_OPEN_TEXT_MAX_CHARS],
        max_chars=MCQ_OPEN_TEXT_MAX_CHARS,
    )
    parsed = parse_llm_json(llm.generate(prompt, temperature=0, json_mode=True))
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    rationale = parsed.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("missing rationale")
    manipulation = parsed.get("manipulation_attempt", False)
    if not isinstance(manipulation, bool):
        raise ValueError("manipulation_attempt must be true or false")
    return {
        "scores": validate_scores(parsed),
        "rationale": rationale.strip()[:MAX_RATIONALE_CHARS],
        "manipulation_attempt": manipulation,
    }
