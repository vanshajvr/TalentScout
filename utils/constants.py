STEPS = [
    "greeting", "ask_name", "upload_resume", "confirm_resume_data",
    "mcq_assessment", "end"
]
EXIT_KEYWORDS = {"exit", "quit", "stop", "goodbye", "bye"}

MAX_TECHNICAL_QUESTIONS = 4
BEHAVIORAL_QUESTION_TEMPLATES = [
    "What draws you to the {role} role, and where do you see it fitting into your career goals?",
    "What led you to choose your field of study, and how has it shaped the way you approach {role_lower} work?",
]

# --- MCQ assessment ---
MCQ_TECHNICAL_COUNT = 10
MCQ_BEHAVIORAL_COUNT = 5
MCQ_OPEN_TEXT_COUNT = 2
MCQ_TOTAL_COUNT = MCQ_TECHNICAL_COUNT + MCQ_BEHAVIORAL_COUNT + MCQ_OPEN_TEXT_COUNT

MCQ_TECHNICAL_TIME_LIMIT_SECONDS = 60
MCQ_OPEN_TEXT_MAX_CHARS = 300

MCQ_FORMATS = [
    "debugging_triage", "architecture_tradeoff", "spot_the_bug",
    "systems_at_scale", "decisional_judgment",
]

# Low to high — matches _difficulty_tier()'s ordering in candidate.py, reused as-is
# for the adaptive-difficulty rule (2 correct in a row -> bump one tier, 2 wrong -> drop one).
MCQ_DIFFICULTY_TIERS = ["fundamentals", "applied", "advanced"]