"""LLM-based job tagging for the people task."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from lib.llm import get_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a job classification assistant. For each numbered job description, assign one or more tags.

Available tags:
- IT — programming, software, data, sysadmin, DevOps
- transport — driving, logistics, delivery, shipping, fleet
- edukacja — teaching, training, tutoring, academic
- medycyna — healthcare, doctor, nurse, pharmacy, dentist
- praca z ludźmi — social work, HR, customer service, sales, consulting
- praca z pojazdami — mechanic, vehicle repair, automotive
- praca fizyczna — construction, warehouse, cleaning, manual labour

Return tags for every person. Use the exact tag names listed above.
Respond with valid JSON matching this schema: {"results": [{"index": <int>, "tags": [<str>, ...]}]}\
"""


class PersonTags(BaseModel):
    """Tags for a single person identified by index."""

    index: int
    tags: list[str]


class TaggingResult(BaseModel):
    """Batch tagging result."""

    results: list[PersonTags]


def tag_jobs(jobs: list[tuple[int, str]]) -> list[PersonTags]:
    """Send numbered job descriptions to LLM and return tags."""
    lines = [f"{idx}: {desc}" for idx, desc in jobs]
    user_msg = "\n".join(lines)

    llm = get_llm()
    response = llm.invoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
    )
    result = TaggingResult.model_validate_json(response.content)  # type: ignore[arg-type]
    logger.info("Tagged %d jobs", len(result.results))
    return result.results
