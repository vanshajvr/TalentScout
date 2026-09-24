"""
Populates the MCQQuestion pool via batched LLM generation, one call per
(technology, difficulty_tier) bucket rather than per question.

Safe to re-run: dedupes against existing question_text within the same bucket
before inserting, so running it again to top up a thin bucket won't create
literal duplicates (though the LLM's non-determinism means it may still
generate different-but-similar questions — that's fine, more variety is good).

Run manually: python seed_mcq_pool.py
"""
from dotenv import load_dotenv
load_dotenv()

import os

from db.database import SessionLocal
from db.models import MCQQuestion
from llm.groq_llm import GroqLLM
from utils.constants import MCQ_DIFFICULTY_TIERS, MCQ_FORMATS, MCQ_SEEDED_TECHNOLOGIES
from utils.llm_json import parse_llm_json

llm = GroqLLM()

TECHNOLOGIES = MCQ_SEEDED_TECHNOLOGIES + ["General Programming"]

QUESTIONS_PER_BUCKET = 10  # evenly distributed across the 5 formats

# This script lives at the project root itself, so its own directory IS the root.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_prompt(path: str) -> str:
    with open(os.path.join(BASE_DIR, path), "r") as f:
        return f.read()


def generate_batch(technology: str, difficulty_tier: str) -> list[dict]:
    prompt_template = _load_prompt("prompts/technical_mcq_pool_prompt.txt")
    prompt = prompt_template.format(
        technology=technology, difficulty_tier=difficulty_tier, count=QUESTIONS_PER_BUCKET,
    )
    raw = llm.generate(prompt, temperature=0.6).strip()
    parsed = parse_llm_json(raw)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON array")
    return parsed


def main():
    db = SessionLocal()
    total_inserted = 0
    total_skipped = 0

    try:
        for technology in TECHNOLOGIES:
            for difficulty_tier in MCQ_DIFFICULTY_TIERS:
                existing_texts = {
                    q.question_text for q in db.query(MCQQuestion.question_text).filter(
                        MCQQuestion.technology == technology,
                        MCQQuestion.difficulty_tier == difficulty_tier,
                    ).all()
                }

                if len(existing_texts) >= QUESTIONS_PER_BUCKET:
                    print(f"  {technology} / {difficulty_tier}: SKIP (already has {len(existing_texts)})")
                    continue

                try:
                    batch = generate_batch(technology, difficulty_tier)
                except Exception as e:
                    print(f"  FAILED  {technology} / {difficulty_tier}: {e}")
                    continue

                inserted_here = 0
                for item in batch:
                    question_text = item.get("question_text")
                    options = item.get("options")
                    correct_option_id = item.get("correct_option_id")
                    format_ = item.get("format")

                    if not question_text or not options or len(options) != 4 or not correct_option_id:
                        continue
                    option_ids = {opt.get("id") for opt in options if isinstance(opt, dict)}
                    if len(option_ids) != 4 or correct_option_id not in option_ids:
                        # The LLM claimed a correct_option_id that isn't among its own
                        # options (or the options are malformed) — every possible answer
                        # to this question would be marked wrong. Reject it outright
                        # rather than seeding a genuinely unanswerable question.
                        continue
                    if format_ not in MCQ_FORMATS:
                        format_ = MCQ_FORMATS[0]  # sane default rather than dropping the question
                    if question_text in existing_texts:
                        total_skipped += 1
                        continue

                    db.add(MCQQuestion(
                        technology=technology, difficulty_tier=difficulty_tier, format=format_,
                        question_text=question_text, options=options,
                        correct_option_id=correct_option_id,
                    ))
                    existing_texts.add(question_text)
                    inserted_here += 1

                db.commit()
                total_inserted += inserted_here
                print(f"  {technology} / {difficulty_tier}: +{inserted_here} questions")

        print(f"\nDone. Inserted {total_inserted} questions total, skipped {total_skipped} duplicates.")
    finally:
        db.close()


if __name__ == "__main__":
    main()