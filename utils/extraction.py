"""
The LLM extraction pipelines (resume -> candidate fields, JD -> job requirements),
kept free of FastAPI/DB concerns so the exact same code path serves both the API
routes and the offline eval harness (evals/run.py). Each function raises on LLM or
parse failure — callers decide what a failure means (a logged fallback in the
candidate flow, a 502 for recruiters, a scored failure in evals).
"""

import io
import os
from datetime import date

import pdfplumber
from docx import Document as DocxDocument

from llm.base import BaseLLM
from utils.constants import MCQ_SEEDED_TECHNOLOGIES
from utils.job_match import split_requirements
from utils.llm_json import parse_llm_json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_RESUME_PDF_PAGES = 20  # any real resume is 1-3 pages; a page cap bounds extraction cost/time
RESUME_PROMPT_MAX_CHARS = 6000
JD_PROMPT_MAX_CHARS = 8000
MAX_SKILLS_PER_LIST = 20


def load_prompt(path: str) -> str:
    with open(os.path.join(BASE_DIR, path), "r") as f:
        return f.read()


def extract_resume_text(file_path: str, ext: str) -> str:
    """File-path wrapper, used by the eval harness. Also accepts .txt for eval cases."""
    if ext == ".txt":
        with open(file_path, "r") as f:
            return f.read()
    with open(file_path, "rb") as f:
        return extract_resume_text_from_bytes(f.read(), ext)


def extract_resume_text_from_bytes(content: bytes, ext: str) -> str:
    """Works on the uploaded bytes directly, so a resume never has to touch disk."""
    if ext == ".pdf":
        text_parts = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages[:MAX_RESUME_PDF_PAGES]:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                for link in getattr(page, "hyperlinks", []):
                    uri = link.get("uri", "")
                    if uri:
                        text_parts.append(f"[link: {uri}]")
        return "\n".join(text_parts)
    elif ext == ".docx":
        doc = DocxDocument(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    return ""


def extract_resume_fields(llm: BaseLLM, resume_text: str, today: date | None = None) -> dict:
    """`today` anchors "2022 – Present"-style dates. Without it the model falls back on
    its own idea of the current year (its training cutoff), silently under-counting
    experience. Evals pin it so expected values don't drift as time passes."""
    if not resume_text.strip():
        return {}
    prompt = load_prompt("prompts/resume_extraction_prompt.txt").format(
        today=(today or date.today()).strftime("%B %Y"),
        resume_text=resume_text[:RESUME_PROMPT_MAX_CHARS],
        canonical_technologies=", ".join(MCQ_SEEDED_TECHNOLOGIES),
    )
    parsed = parse_llm_json(llm.generate(prompt, temperature=0, json_mode=True))
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")
    return parsed


def extract_job_requirements(llm: BaseLLM, title: str, description: str) -> dict:
    prompt = load_prompt("prompts/jd_extraction_prompt.txt").format(
        title=title,
        description=description[:JD_PROMPT_MAX_CHARS],
        canonical_technologies=", ".join(MCQ_SEEDED_TECHNOLOGIES),
    )
    parsed = parse_llm_json(llm.generate(prompt, temperature=0, json_mode=True))
    if not isinstance(parsed, dict):
        raise ValueError("expected a JSON object")

    must, nice = split_requirements(parsed.get("must_have_skills"), parsed.get("nice_to_have_skills"))
    try:
        min_experience = float(parsed["min_experience"]) if parsed.get("min_experience") is not None else None
    except (TypeError, ValueError):
        min_experience = None
    if min_experience is not None and not (0 <= min_experience <= 50):
        min_experience = None

    return {
        "must_have_skills": must[:MAX_SKILLS_PER_LIST],
        "nice_to_have_skills": nice[:MAX_SKILLS_PER_LIST],
        "min_experience": min_experience,
    }
