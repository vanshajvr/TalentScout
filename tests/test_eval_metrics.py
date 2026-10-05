"""
Unit tests for the eval scoring (evals/metrics.py) — if the ruler is wrong, every
number the eval harness reports is wrong with it. No DB, no LLM.
"""

import glob
import json
import os

from evals import metrics


def test_scalar_outcomes_cover_all_four_cases():
    exact = metrics.match_exact
    assert metrics.score_scalar("a@x.com", "A@X.com ", exact) == "correct"
    assert metrics.score_scalar(None, None, exact) == "correct"
    assert metrics.score_scalar(None, "", exact) == "correct"
    assert metrics.score_scalar("a@x.com", "b@x.com", exact) == "wrong"
    assert metrics.score_scalar("a@x.com", None, exact) == "missed"
    assert metrics.score_scalar(None, "invented@x.com", exact) == "hallucinated"


def test_phone_ignores_formatting_and_country_code():
    assert metrics.match_phone("+91 98765 43210", "9876543210")
    assert metrics.match_phone("+1 (415) 555-0142", "415.555.0142")
    assert not metrics.match_phone("+1 415 555 0142", "415 555 0143")


def test_url_ignores_scheme_www_and_trailing_slash():
    assert metrics.match_url("https://www.linkedin.com/in/meera/", "linkedin.com/in/meera")
    assert not metrics.match_url("github.com/a", "github.com/b")


def test_experience_tolerance():
    assert metrics.match_experience(4.0, "4.4")
    assert metrics.match_experience("3+", 3)
    assert not metrics.match_experience(4.0, 4.6)
    assert not metrics.match_experience(4.0, "four")


def test_fuzzy_text_accepts_rephrasing_but_not_different_values():
    assert metrics.match_fuzzy_text("Backend Engineer at Finlytics", "Backend Engineer, Finlytics")
    assert metrics.match_fuzzy_text("Pune, India", "Pune, Maharashtra, India")
    assert not metrics.match_fuzzy_text("Pune, India", "Mumbai, India")


def test_skill_sets_use_fit_scorer_normalization():
    s = metrics.score_set(["Node.js", "SQL", "Go"], ["node", "SQL", "Rust"])
    assert (s["tp"], s["fp"], s["fn"]) == (2, 1, 1)
    assert s["missing"] == ["go"] and s["extra"] == ["rust"]


def test_prf_edge_cases():
    assert metrics.prf(0, 0, 0) == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert metrics.prf(0, 2, 2)["f1"] == 0.0


def test_resume_case_only_scores_labeled_fields():
    r = metrics.score_resume_case({"email": "a@x.com", "github": None}, {"email": "a@x.com", "phone": "123"})
    assert r["fields"] == {"email": "correct", "github": "correct"}
    assert r["null_labeled"] == ["github"]


def test_resume_aggregate_hallucination_rate_is_over_null_labels():
    cases = [
        metrics.score_resume_case({"email": "a@x.com", "github": None, "phone": None}, {"email": "a@x.com", "github": "github.com/fake"}),
        metrics.score_resume_case({"email": "b@x.com", "linkedin": None}, {"email": "b@x.com"}),
    ]
    summary = metrics.aggregate_resume(cases)
    # 3 null-labeled fields, 1 hallucinated
    assert summary["hallucination_rate"] == 1 / 3
    assert summary["field_accuracy"] == 4 / 5


def test_jd_case_flags_misplaced_skills():
    r = metrics.score_jd_case(
        {"must_have_skills": ["Python", "SQL"], "nice_to_have_skills": ["AWS"], "min_experience": 3},
        {"must_have_skills": ["Python"], "nice_to_have_skills": ["SQL", "AWS"], "min_experience": 3.0},
    )
    assert r["misplaced"] == ["sql"]
    assert r["min_experience_correct"]
    assert r["must_have"]["fn"] == 1


def test_dataset_files_are_well_formed():
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "evals", "datasets")
    resume_cases = glob.glob(os.path.join(root, "resumes", "*.json"))
    jd_cases = glob.glob(os.path.join(root, "jds", "*.json"))
    assert resume_cases and jd_cases

    for path in resume_cases:
        case = json.load(open(path))
        assert os.path.exists(os.path.join(os.path.dirname(path), case["resume_file"])), path
        assert set(case["expected"]) <= set(metrics.RESUME_FIELD_MATCHERS) | {"tech_stack"}, path
    for path in jd_cases:
        case = json.load(open(path))
        assert case["title"] and os.path.exists(os.path.join(os.path.dirname(path), case["description_file"])), path
        assert set(case["expected"]) == {"must_have_skills", "nice_to_have_skills", "min_experience"}, path


def test_judge_aggregate_reports_pair_gap_and_injection_resistance():
    labels = {"relevance": 5, "specificity": 5, "clarity": 5}
    low = {"relevance": 1, "specificity": 1, "clarity": 2}
    results = [
        {**metrics.score_judge_case(labels, {"relevance": 5, "specificity": 5, "clarity": 5}), "pair": "p"},
        {**metrics.score_judge_case(labels, {"relevance": 5, "specificity": 4, "clarity": 3}), "pair": "p"},
        {**metrics.score_judge_case(low, {"relevance": 5, "specificity": 5, "clarity": 5}), "kind": "injection", "flagged": False},
        {**metrics.score_judge_case(low, {"relevance": 1, "specificity": 1, "clarity": 3}), "kind": "injection", "flagged": True},
        {**metrics.score_judge_case(labels, labels), "flagged": True},
    ]
    s = metrics.aggregate_judge(results)
    assert s["pair_gaps"] == {"p": 1.0}  # 5.0 vs 4.0 overall for the same content
    assert (s["injection_flagged"], s["injection_complied"], s["injection_cases"]) == (1, 1, 2)
    assert (s["false_flags"], s["non_injection_cases"]) == (1, 3)
    assert s["by_dimension"]["relevance"]["mae"] == 0.8  # errors 0, 0, 4, 0, 0


def test_judge_dataset_is_well_formed():
    from utils.constants import MCQ_OPEN_TEXT_MAX_CHARS
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "evals", "datasets", "judge")
    paths = glob.glob(os.path.join(root, "*.json"))
    assert paths
    pairs: dict[str, list[dict]] = {}
    for path in paths:
        case = json.load(open(path))
        assert case["question"] and len(case["answer"]) <= MCQ_OPEN_TEXT_MAX_CHARS, path
        assert set(case["expected"]) == set(metrics.JUDGE_DIMENSIONS), path
        assert all(1 <= v <= 5 for v in case["expected"].values()), path
        if case.get("pair"):
            pairs.setdefault(case["pair"], []).append(case["expected"])
    # A language pair only measures bias if both sides carry identical labels.
    for labels in pairs.values():
        assert len(labels) >= 2 and all(l == labels[0] for l in labels), labels
