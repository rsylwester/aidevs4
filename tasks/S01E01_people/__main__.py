"""S01E01 - people task: find transport workers from Grudziadz born 1986-2006."""

from __future__ import annotations

import csv
import io
import logging

from lib.hub import fetch_data, submit_answer
from lib.logging import setup_logging
from tasks.S01E01_people.constants import (
    COL_BIRTH_DATE,
    COL_BIRTH_PLACE,
    COL_GENDER,
    COL_JOB,
    COL_NAME,
    COL_SURNAME,
    DATA_FILE,
    FILTER_CITY,
    FILTER_GENDER,
    FILTER_YEAR_MAX,
    FILTER_YEAR_MIN,
    TARGET_TAG,
    TASK_NAME,
)
from tasks.S01E01_people.tagging import tag_jobs

logger = logging.getLogger(__name__)


def _parse_csv(raw: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw))
    return list(reader)


def _filter_people(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter: male, from Grudziadz, born 1986-2006."""
    filtered: list[dict[str, str]] = []
    for row in rows:
        gender = row.get(COL_GENDER, "").strip().upper()
        birth_place = row.get(COL_BIRTH_PLACE, "").strip()
        birth_date = row.get(COL_BIRTH_DATE, "").strip()
        if not birth_date:
            continue
        year = int(birth_date[:4])
        if gender == FILTER_GENDER and birth_place == FILTER_CITY and FILTER_YEAR_MIN <= year <= FILTER_YEAR_MAX:
            filtered.append(row)
    return filtered


def run() -> None:
    setup_logging()

    logger.info("[bold cyan]Fetching %s from hub...[/]", DATA_FILE)
    raw_csv = fetch_data(DATA_FILE)
    rows = _parse_csv(raw_csv)
    logger.info("[green]Parsed %d rows from CSV[/]", len(rows))

    candidates = _filter_people(rows)
    logger.info(
        "[yellow]After filter (%s, %s, %d-%d): %d candidates[/]",
        FILTER_GENDER,
        FILTER_CITY,
        FILTER_YEAR_MIN,
        FILTER_YEAR_MAX,
        len(candidates),
    )

    # Build (index, job) pairs for tagging
    jobs: list[tuple[int, str]] = []
    for i, row in enumerate(candidates):
        job = row.get(COL_JOB, "").strip()
        if job:
            jobs.append((i, job))

    logger.info("[bold cyan]Sending %d jobs to LLM for tagging...[/]", len(jobs))
    tagged = tag_jobs(jobs)

    # Map index -> tags
    tag_map: dict[int, list[str]] = {t.index: t.tags for t in tagged}

    # Build answer objects for people with target tag
    answer: list[dict[str, str | list[str]]] = []
    for i, row in enumerate(candidates):
        tags = tag_map.get(i, [])
        if any(TARGET_TAG in t.lower() for t in tags):
            name = row.get(COL_NAME, "")
            surname = row.get(COL_SURNAME, "")
            entry: dict[str, str | list[str]] = {
                "name": name,
                "surname": surname,
                "gender": row.get(COL_GENDER, ""),
                "born": row.get(COL_BIRTH_DATE, "")[:4],
                "city": row.get(COL_BIRTH_PLACE, ""),
                "tags": tags,
            }
            answer.append(entry)
            logger.info(
                "[bold green]\\u2713 Transport match:[/] %s %s [dim](tags: %s)[/]", name, surname, ", ".join(tags)
            )

    logger.info("[bold magenta]Transport workers found: %d[/]", len(answer))
    logger.info("[bold cyan]Submitting answer to hub...[/]")
    submit_answer(TASK_NAME, answer)


if __name__ == "__main__":
    run()
