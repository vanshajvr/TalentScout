from typing import Any

from json_repair import repair_json


def parse_llm_json(raw: str) -> Any:
    """
    Strips markdown code fences if present, then parses via json_repair — a library
    purpose-built for fixing malformed JSON from LLM outputs (unescaped quotes inside
    string values, literal newlines instead of \\n, trailing commas, unterminated
    strings, etc). Raises ValueError on input too broken to recover from — callers
    should still catch and handle failures.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`").replace("json", "", 1).strip()

    result = repair_json(text, return_objects=True)
    if result == "" or result is None:
        raise ValueError("json_repair could not recover any structure from this input")
    return result