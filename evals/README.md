# Extraction evals

TalentScout depends on two LLM extraction steps:

- **Resume → candidate fields** (email, phone, experience, role, tech stack, …).
  Candidates confirm these fields, and they drive question difficulty and job fit.
- **Job description → requirements** (must-have and nice-to-have skills, minimum
  experience). Recruiters review these, and candidates are ranked against them.

This harness measures both against labeled cases. It runs the **same code path as
production** (`utils/extraction.py`), so a prompt or model change shows up here
before candidates see it.

```bash
python -m evals.run                         # both suites, production model (Groq)
python -m evals.run resume -v               # one suite, every field of every case
python -m evals.run --case 05               # cases whose id contains "05"
python -m evals.run --model llama-3.3-70b-versatile --save    # compare a model
python -m evals.run --provider ollama --model llama3          # local, offline
python -m evals.run --fail-under 0.9        # exit 1 below threshold (CI gate)
```

`--save` writes a JSON report to `evals/results/` (gitignored). Each report holds
the model, the git commit and a hash of each prompt file, so you can always tell
which prompt version produced which numbers.

## What gets measured

**Resume extraction.** Each scalar field gets one of four outcomes:

| outcome | meaning |
|---|---|
| correct | matches the label (both null also counts as correct) |
| wrong | both present, but different |
| missed | the resume has it; the model returned null |
| **hallucinated** | the resume doesn't have it; the model invented a value |

Hallucinations are counted separately on purpose. In a hiring tool, an invented
phone number or GitHub profile is worse than a blank. The **hallucination rate**
is calculated only over fields labeled null, because those are the only fields
where a hallucination can happen.

Matching tolerates formatting differences:

- Phones compare on their last 10 digits.
- URLs ignore the scheme, `www.` and a trailing slash.
- Experience is correct within ±0.5 years.
- Location, role and education match if every expected word appears in the
  prediction, or if the two strings are at least 80% similar.

Tech stacks are scored with precision, recall and F1, using the same skill
normalization as the fit scorer (`utils/job_match.py`).

**JD extraction.** Must-have and nice-to-have skills are scored with precision,
recall and F1. Minimum experience is scored as exact-match accuracy.
**Misplaced skills** counts required skills extracted as optional, and the
reverse. Each one moves a candidate's fit score far more than its effect on F1
suggests.

## Results

October 2026, `openai/gpt-oss-120b` on Groq, seed dataset:

| suite | metric | score |
|---|---|---|
| resume (8 cases) | field accuracy | 100% (64/64) |
| | hallucination rate | 0% (0 of 13 null-labeled fields) |
| | tech stack P / R / F1 | 97.3% / 100% / 98.6% |
| JD (6 cases) | must-have P / R / F1 | 94.4% / 100% / 97.1% |
| | nice-to-have F1 | 100% |
| | misplaced skills | 0 |
| | min-experience accuracy | 100% |

The only misses were both "Spring Boot" listed as its own skill rather than folded
into Java. That's arguably a labeling choice, not an error. Repeat runs at
temperature 0 still vary by about one field.

**Read these numbers carefully.** The seed cases are clean, synthetic plain text.
Each one targets a known failure mode: contact details behind PDF links, "Present"
end dates, overlapping jobs, degree years that shouldn't count as experience, and
missing fields that invite hallucination. A strong model handles all of these
when the input is clean. Real resumes add noise from PDF text extraction
(multi-column layouts, tables, broken lines), which these cases don't cover. The
next step that would make these numbers meaningful is labeling 20–30 real resumes.

### A hypothesis the eval rejected

The resume prompt didn't tell the model today's date, so "Jan 2023 – Present"
seemed likely to be measured against the model's training cutoff. With the date
line removed, `gpt-oss-120b` still got experience right on 8/8 cases. The date
line stays in the prompt because it costs nothing and protects models with older
cutoffs, like the Ollama fallback. But on the production model, it was never the
problem.

## Adding cases

A case is a `.json` label file next to its input file. The `id` is the file name.

**Resume** (`datasets/resumes/`). The input can be `.txt`, `.pdf` or `.docx`.
PDFs go through the same `pdfplumber` + hyperlink extraction as uploads.

```json
{
  "resume_file": "09_my_case.pdf",
  "as_of": "2026-10-01",
  "notes": "What this case is testing",
  "expected": {
    "email": "...", "phone": "...", "location": "...", "experience": 3.5,
    "role": "Title at Company", "education": "...",
    "linkedin": null, "github": null,
    "tech_stack": ["Python", "SQL"]
  }
}
```

- `as_of` stands in for today's date, so "Present" end dates keep their expected
  values no matter when you run the eval.
- Set a field to `null` when the resume doesn't contain it. That's what makes
  hallucinations measurable.
- Leave a field out entirely if you're unsure of the right answer. It won't be
  scored.

**JD** (`datasets/jds/`):

```json
{
  "title": "Backend Engineer",
  "description_file": "07_my_jd.txt",
  "notes": "...",
  "expected": { "must_have_skills": ["Python"], "nice_to_have_skills": [], "min_experience": 2 }
}
```

**Real resumes contain personal data.** Prefix their files with `private_` (for
example `private_01.pdf` and `private_01.json`). `.gitignore` excludes
`evals/datasets/**/private_*`, so they're evaluated locally and never committed.
Only add a real resume with the candidate's consent.
