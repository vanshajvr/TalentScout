"""
Unit tests for the deterministic fit scorer (utils/job_match.py) — no DB, no LLM.
"""

from utils.job_match import clean_skill_list, compute_fit, normalize_skill


def test_normalize_skill_aliases_and_punctuation():
    assert normalize_skill("Node.js") == normalize_skill("node") == "nodejs"
    assert normalize_skill("React.js") == normalize_skill("React") == "react"
    assert normalize_skill("Golang") == "go"
    assert normalize_skill("K8s") == "kubernetes"


def test_normalize_skill_keeps_c_variants_distinct():
    assert len({normalize_skill("C"), normalize_skill("C++"), normalize_skill("C#")}) == 3


def test_clean_skill_list_dedupes_by_normalized_name():
    assert clean_skill_list(["Node.js", " node ", "", "Python", None, "python"]) == ["Node.js", "Python"]


def test_perfect_match_scores_100():
    fit = compute_fit(
        must_have=["Python", "SQL"], nice_to_have=["Docker"], min_experience=2,
        candidate_tech_stack=["Python", "SQL", "Docker"], candidate_experience=3, resume_text="",
    )
    assert fit["score"] == 100
    assert fit["details"]["must_have"]["missing"] == []


def test_missing_must_have_is_named_in_summary():
    fit = compute_fit(
        must_have=["Python", "Kubernetes"], nice_to_have=[], min_experience=None,
        candidate_tech_stack=["Python"], candidate_experience=None, resume_text="",
    )
    # Only must-haves are specified, so they carry the whole score: 1 of 2 -> 50.
    assert fit["score"] == 50
    assert "Meets 1/2 must-haves (missing Kubernetes)" in fit["summary"]


def test_weights_must_70_nice_20_experience_10():
    fit = compute_fit(
        must_have=["Python"], nice_to_have=["AWS"], min_experience=4,
        candidate_tech_stack=["Python"], candidate_experience=2, resume_text="",
    )
    # 70 (must) + 0 (nice) + 10 * 2/4 (experience) = 75
    assert fit["score"] == 75
    assert fit["details"]["experience"] == {"required": 4, "candidate": 2, "meets": False}


def test_skill_found_in_resume_text_counts_with_source():
    fit = compute_fit(
        must_have=["Kubernetes"], nice_to_have=[], min_experience=None,
        candidate_tech_stack=["Python"], candidate_experience=None,
        resume_text="Deployed services to Kubernetes clusters on GKE.",
    )
    assert fit["score"] == 100
    assert fit["details"]["must_have"]["matched"] == [{"skill": "Kubernetes", "source": "resume_text"}]


def test_short_skill_names_do_not_match_ordinary_words():
    fit = compute_fit(
        must_have=["Go"], nice_to_have=[], min_experience=None,
        candidate_tech_stack=["Python"], candidate_experience=None,
        resume_text="My go-to approach is to go deep on profiling.",
    )
    assert fit["score"] == 0


def test_java_does_not_match_javascript():
    fit = compute_fit(
        must_have=["Java"], nice_to_have=[], min_experience=None,
        candidate_tech_stack=["JavaScript"], candidate_experience=None,
        resume_text="Built dashboards in JavaScript.",
    )
    assert fit["score"] == 0


def test_unknown_experience_earns_nothing_but_is_explained():
    fit = compute_fit(
        must_have=[], nice_to_have=[], min_experience=3,
        candidate_tech_stack=[], candidate_experience=None, resume_text="",
    )
    assert fit["score"] == 0
    assert "experience unknown" in fit["summary"]


def test_job_with_no_requirements_has_no_score():
    fit = compute_fit(
        must_have=[], nice_to_have=[], min_experience=None,
        candidate_tech_stack=["Python"], candidate_experience=5, resume_text="",
    )
    assert fit["score"] is None
