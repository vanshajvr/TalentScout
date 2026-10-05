"""
Offline eval harness for the LLM extraction pipelines.

    python -m evals.run                       # both suites, production model
    python -m evals.run resume --verbose      # one suite, print every case
    python -m evals.run jd --model llama-3.3-70b-versatile --save
    python -m evals.run --provider ollama --model llama3 --save
    python -m evals.run --fail-under 0.85     # non-zero exit below threshold (CI)

Runs the exact production code path (utils/extraction.py) against the labeled cases
in evals/datasets/, and scores the output with evals/metrics.py. See evals/README.md
for the dataset format and how to add real resumes.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime

from dotenv import load_dotenv

load_dotenv()

from evals import metrics  # noqa: E402
from utils.extraction import (  # noqa: E402
    BASE_DIR, extract_job_requirements, extract_resume_fields, extract_resume_text,
)

EVALS_DIR = os.path.join(BASE_DIR, "evals")
DATASETS_DIR = os.path.join(EVALS_DIR, "datasets")
RESULTS_DIR = os.path.join(EVALS_DIR, "results")

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"  # matches llm/groq_llm.py


# --------------------------------------------------------------------------- loading

def _load_cases(suite_dir: str, only: str | None) -> list[dict]:
    cases = []
    for name in sorted(os.listdir(suite_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(suite_dir, name)) as f:
            case = json.load(f)
        case.setdefault("id", name.removesuffix(".json"))
        case["_dir"] = suite_dir
        if only is None or only in case["id"]:
            cases.append(case)
    return cases


def _read_case_file(case: dict, key: str) -> str:
    path = os.path.join(case["_dir"], case[key])
    return extract_resume_text(path, os.path.splitext(path)[1].lower())


def _prompt_hash(prompt_path: str) -> str:
    with open(os.path.join(BASE_DIR, prompt_path), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR, stderr=subprocess.DEVNULL, text=True,
        ).strip() + ("-dirty" if subprocess.call(
            ["git", "diff", "--quiet"], cwd=BASE_DIR, stderr=subprocess.DEVNULL) else "")
    except (OSError, subprocess.CalledProcessError):
        return None


def _build_llm(provider: str, model: str | None):
    if provider == "groq":
        from llm.groq_llm import GroqLLM
        if not os.environ.get("GROQ_API_KEY"):
            sys.exit("GROQ_API_KEY is not set (add it to .env), or use --provider ollama.")
        return GroqLLM(model_name=model or DEFAULT_GROQ_MODEL)
    from llm.ollama_llm import OllamaLLM
    return OllamaLLM(model_name=model or "llama3")


# --------------------------------------------------------------------------- suites

def run_resume_suite(llm, only: str | None) -> dict:
    cases = _load_cases(os.path.join(DATASETS_DIR, "resumes"), only)
    results = []
    for case in cases:
        as_of = date.fromisoformat(case["as_of"]) if case.get("as_of") else None
        started = time.perf_counter()
        try:
            predicted = extract_resume_fields(llm, _read_case_file(case, "resume_file"), today=as_of)
            error = None
        except Exception as e:  # scored as an error, not as field outcomes — see summary
            predicted, error = {}, f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - started

        result = {"id": case["id"], "latency_s": round(latency, 2), "error": error, "predicted": predicted}
        if error is None:
            result.update(metrics.score_resume_case(case["expected"], predicted))
        result["expected"] = case["expected"]
        results.append(result)
        _print_resume_case(result)

    scored = [r for r in results if r["error"] is None]
    return {"cases": results, "summary": {**metrics.aggregate_resume(scored), **_run_stats(results)}}


def run_jd_suite(llm, only: str | None) -> dict:
    cases = _load_cases(os.path.join(DATASETS_DIR, "jds"), only)
    results = []
    for case in cases:
        started = time.perf_counter()
        try:
            predicted = extract_job_requirements(llm, case["title"], _read_case_file(case, "description_file"))
            error = None
        except Exception as e:
            predicted, error = {}, f"{type(e).__name__}: {e}"
        latency = time.perf_counter() - started

        result = {"id": case["id"], "latency_s": round(latency, 2), "error": error, "predicted": predicted}
        if error is None:
            result.update(metrics.score_jd_case(case["expected"], predicted))
        result["expected"] = case["expected"]
        results.append(result)
        _print_jd_case(result)

    scored = [r for r in results if r["error"] is None]
    return {"cases": results, "summary": {**metrics.aggregate_jd(scored), **_run_stats(results)}}


def _run_stats(results: list[dict]) -> dict:
    latencies = sorted(r["latency_s"] for r in results)
    return {
        "cases": len(results),
        "errors": sum(1 for r in results if r["error"]),
        "latency_p50_s": latencies[len(latencies) // 2] if latencies else None,
        "latency_max_s": latencies[-1] if latencies else None,
    }


# --------------------------------------------------------------------------- output

VERBOSE = False


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _print_resume_case(r: dict) -> None:
    if r["error"]:
        print(f"  ✗ {r['id']}  ERROR {r['error']}")
        return
    bad = {k: v for k, v in r["fields"].items() if v != "correct"}
    stack = r.get("tech_stack")
    stack_ok = stack is None or (stack["fp"] == 0 and stack["fn"] == 0)
    mark = "✓" if not bad and stack_ok else "✗"
    print(f"  {mark} {r['id']}  ({r['latency_s']}s)")
    if VERBOSE or bad or not stack_ok:
        for name, outcome in r["fields"].items():
            if VERBOSE or outcome != "correct":
                print(f"      {name:<11} {outcome:<12} expected={r['expected'].get(name)!r}  got={r['predicted'].get(name)!r}")
        if stack and (VERBOSE or not stack_ok):
            print(f"      tech_stack  missing={stack['missing']}  extra={stack['extra']}")


def _print_jd_case(r: dict) -> None:
    if r["error"]:
        print(f"  ✗ {r['id']}  ERROR {r['error']}")
        return
    issues = []
    for group in ("must_have", "nice_to_have"):
        if r[group]["missing"] or r[group]["extra"]:
            issues.append(f"{group}: missing={r[group]['missing']} extra={r[group]['extra']}")
    if r["misplaced"]:
        issues.append(f"misplaced={r['misplaced']}")
    if not r["min_experience_correct"]:
        issues.append(f"min_experience: expected={r['expected'].get('min_experience')!r} got={r['predicted'].get('min_experience')!r}")
    print(f"  {'✗' if issues else '✓'} {r['id']}  ({r['latency_s']}s)")
    for line in issues if (issues or VERBOSE) else []:
        print(f"      {line}")


def _print_resume_summary(s: dict) -> None:
    print("\n  Resume extraction")
    print(f"    field accuracy      {_pct(s['field_accuracy'])}   ({s['outcomes']['correct']} correct, "
          f"{s['outcomes']['wrong']} wrong, {s['outcomes']['missed']} missed, {s['outcomes']['hallucinated']} hallucinated)")
    print(f"    hallucination rate  {_pct(s['hallucination_rate'])}   (of fields the resume doesn't contain)")
    ts = s["tech_stack"]
    print(f"    tech stack          P {_pct(ts['precision'])}  R {_pct(ts['recall'])}  F1 {_pct(ts['f1'])}")
    print("    by field:")
    for name, c in s["by_field"].items():
        print(f"      {name:<11} {_pct(c['accuracy']):>7}")
    print(f"    {s['cases']} cases, {s['errors']} errors, latency p50 {s['latency_p50_s']}s / max {s['latency_max_s']}s")


def _print_jd_summary(s: dict) -> None:
    print("\n  JD requirement extraction")
    m, n = s["must_have"], s["nice_to_have"]
    print(f"    must-have           P {_pct(m['precision'])}  R {_pct(m['recall'])}  F1 {_pct(m['f1'])}")
    print(f"    nice-to-have        P {_pct(n['precision'])}  R {_pct(n['recall'])}  F1 {_pct(n['f1'])}")
    print(f"    misplaced skills    {s['misplaced_skills']}   (required <-> optional swaps)")
    print(f"    min experience      {_pct(s['min_experience_accuracy'])}")
    print(f"    {s['cases']} cases, {s['errors']} errors, latency p50 {s['latency_p50_s']}s / max {s['latency_max_s']}s")


def _headline(suite: str, summary: dict) -> float | None:
    """The single number --fail-under checks, per suite."""
    if suite == "resume":
        return summary["field_accuracy"]
    return summary["must_have"]["f1"]


# --------------------------------------------------------------------------- main

def main() -> int:
    global VERBOSE
    parser = argparse.ArgumentParser(description="Run TalentScout's LLM extraction evals.")
    parser.add_argument("suite", nargs="?", choices=["resume", "jd", "all"], default="all")
    parser.add_argument("--provider", choices=["groq", "ollama"], default="groq")
    parser.add_argument("--model", help=f"model name (default: {DEFAULT_GROQ_MODEL} on groq, llama3 on ollama)")
    parser.add_argument("--case", help="only run cases whose id contains this string")
    parser.add_argument("--save", action="store_true", help="write a JSON report to evals/results/")
    parser.add_argument("--fail-under", type=float, metavar="X",
                        help="exit 1 if resume field accuracy or JD must-have F1 is below X (0-1), or any case errors")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    VERBOSE = args.verbose

    llm = _build_llm(args.provider, args.model)
    suites = ["resume", "jd"] if args.suite == "all" else [args.suite]
    print(f"Model: {args.provider}/{llm.model_name}")

    report = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "provider": args.provider,
        "model": llm.model_name,
        "git": _git_sha(),
        "suites": {},
    }
    failed = False
    for suite in suites:
        print(f"\n[{suite}]")
        if suite == "resume":
            result = run_resume_suite(llm, args.case)
            result["prompt_sha"] = _prompt_hash("prompts/resume_extraction_prompt.txt")
            _print_resume_summary(result["summary"])
        else:
            result = run_jd_suite(llm, args.case)
            result["prompt_sha"] = _prompt_hash("prompts/jd_extraction_prompt.txt")
            _print_jd_summary(result["summary"])
        report["suites"][suite] = result

        if args.fail_under is not None:
            headline = _headline(suite, result["summary"])
            if result["summary"]["errors"] or headline is None or headline < args.fail_under:
                print(f"    FAIL: below --fail-under {args.fail_under}")
                failed = True

    if args.save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        model_slug = llm.model_name.replace("/", "_").replace(":", "_")
        path = os.path.join(RESULTS_DIR, f"{stamp}_{args.suite}_{model_slug}.json")
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nSaved report: {os.path.relpath(path, BASE_DIR)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
