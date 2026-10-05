"""
Composite ranking for the recruiter shortlist. Pure functions — the router gathers
the data, this module scores it, tests/test_shortlist.py covers it.

Design choices, each deliberate:
- Every component is 0-100 and shown on its own next to the composite, so a recruiter
  can always see *why* someone ranks where they do.
- Components that don't exist for a candidate (no job -> no fit score; written answers
  not graded yet) are left out and the remaining weights renormalized, rather than
  counted as zero. The row is marked partial so that's visible.
- Integrity signals (tab switches, fullscreen exits, grader-manipulation attempts) are
  flags for human review, never deductions. A tab switch can be a notification or an
  accessibility tool; silently lowering a rank over it would penalize people for
  things the system can't actually interpret.
"""

COMPONENTS = ("fit", "technical", "written")
DEFAULT_WEIGHTS = {"fit": 40, "technical": 40, "written": 20}


def technical_component(correct: int, total: int) -> float | None:
    return 100 * correct / total if total else None


def written_component(average_1_to_5: float | None) -> float | None:
    """Maps the judge's 1-5 average onto 0-100 (1 -> 0, 5 -> 100)."""
    if average_1_to_5 is None:
        return None
    return 100 * (average_1_to_5 - 1) / 4


def normalize_weights(weights: dict | None) -> dict[str, float]:
    """Clamps each weight to 0-100; falls back to the defaults if they're all zero."""
    raw = {c: max(0.0, min(100.0, float((weights or {}).get(c, DEFAULT_WEIGHTS[c])))) for c in COMPONENTS}
    if not any(raw.values()):
        raw = {c: float(w) for c, w in DEFAULT_WEIGHTS.items()}
    return raw


def composite_score(components: dict[str, float | None], weights: dict[str, float]) -> dict:
    """Returns {"score": 0-100 | None, "partial": bool, "used": [component names]}.
    partial means a component that carries weight is missing for this candidate."""
    used = [c for c in COMPONENTS if components.get(c) is not None and weights[c] > 0]
    total_weight = sum(weights[c] for c in used)
    if not total_weight:
        return {"score": None, "partial": True, "used": []}
    score = sum(components[c] * weights[c] for c in used) / total_weight
    missing_weighted = [c for c in COMPONENTS if components.get(c) is None and weights[c] > 0]
    return {"score": round(score), "partial": bool(missing_weighted), "used": used}


def integrity_flags(tab_switches: int, fullscreen_exits: int, manipulation_attempts: int) -> list[dict]:
    flags = []
    if tab_switches:
        flags.append({"type": "tab_switch", "label": f"{tab_switches} tab switch{'es' if tab_switches != 1 else ''}"})
    if fullscreen_exits:
        flags.append({"type": "fullscreen_exit", "label": f"{fullscreen_exits} fullscreen exit{'s' if fullscreen_exits != 1 else ''}"})
    if manipulation_attempts:
        flags.append({"type": "manipulation", "label": "tried to instruct the AI grader"})
    return flags


def summary_line(
    fit_score: int | None, fit_summary: str | None,
    technical_correct: int, technical_total: int, final_tier: str | None,
    written_average: float | None, written_pending: int,
) -> str:
    parts = []
    if fit_score is not None:
        missing = ""
        if fit_summary and "(missing " in fit_summary:
            missing = " (" + fit_summary.split("(", 1)[1].split(")", 1)[0] + ")"
        parts.append(f"Fit {fit_score}{missing}")
    if technical_total:
        tier = f", ended at {final_tier}" if final_tier else ""
        parts.append(f"Technical {technical_correct}/{technical_total}{tier}")
    if written_average is not None:
        parts.append(f"Written {written_average:g}/5")
    elif written_pending:
        parts.append("Written answers not graded yet")
    return " · ".join(parts) if parts else "No scored results yet"
