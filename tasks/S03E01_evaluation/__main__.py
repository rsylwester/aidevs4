"""S03E01 - evaluation: Detect anomalies in 10,000 sensor JSON files."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

import httpx

from lib.hub import submit_answer
from lib.logging import setup_logging
from lib.tracing import langfuse_session
from settings import settings
from tasks.S03E01_evaluation.checks import CheckResult, check_record
from tasks.S03E01_evaluation.classify_notes import classify_notes

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / ".workspace"
SENSORS_DIR = WORKSPACE / "sensors"


def _download_and_extract() -> None:
    """Download sensors.zip and extract to .workspace/sensors/."""
    if SENSORS_DIR.exists() and any(SENSORS_DIR.iterdir()):
        logger.info("Sensors already extracted at %s", SENSORS_DIR)
        return

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    SENSORS_DIR.mkdir(exist_ok=True)

    url = f"{settings.aidevs_hub_url}/dane/sensors.zip"
    logger.info("Downloading sensors.zip from %s", url)
    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(SENSORS_DIR)

    json_count = len(list(SENSORS_DIR.rglob("*.json")))
    logger.info("Extracted %d JSON files to %s", json_count, SENSORS_DIR)


def _load_all_sensors() -> dict[str, dict[str, Any]]:
    """Load all sensor JSON files. Returns {file_id: data}."""
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(SENSORS_DIR.rglob("*.json")):
        file_id = path.stem  # e.g. "0001" from "0001.json"
        with path.open() as f:
            data: dict[str, Any] = json.load(f)
        records[file_id] = data
    logger.info("Loaded %d sensor records", len(records))
    return records


def run() -> None:
    setup_logging()
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    with langfuse_session("S03E01-evaluation") as session_id:
        logger.info("[bold cyan]S03E01-evaluation | session=%s[/]", session_id)

        # Step 1: Download & extract
        logger.info("[bold]== Download & extract sensors ==[/]")
        _download_and_extract()

        # Step 2: Load all sensor data
        records = _load_all_sensors()

        # Step 3: Programmatic checks
        logger.info("[bold]== Programmatic anomaly checks ==[/]")
        anomaly_ids: set[str] = set()
        data_ok_results: list[CheckResult] = []

        for file_id, data in records.items():
            result = check_record(file_id, data)
            if result.is_anomaly:
                anomaly_ids.add(file_id)
            else:
                data_ok_results.append(result)

        logger.info(
            "Programmatic: %d anomalies, %d data-OK files",
            len(anomaly_ids),
            len(data_ok_results),
        )

        # Step 4: LLM classification of operator notes (data-OK files only)
        logger.info("[bold]== LLM note classification ==[/]")

        # Deduplicate notes
        unique_notes_list: list[str] = sorted({r.operator_note for r in data_ok_results})
        note_to_file_ids: dict[str, list[str]] = {}
        for r in data_ok_results:
            note_to_file_ids.setdefault(r.operator_note, []).append(r.file_id)

        logger.info("%d unique notes from %d data-OK files", len(unique_notes_list), len(data_ok_results))

        flagged_indices = classify_notes(unique_notes_list)
        logger.info("LLM flagged %d unique notes as anomalous", len(flagged_indices))

        # Map flagged notes back to file IDs
        for idx in flagged_indices:
            note = unique_notes_list[idx]
            file_ids = note_to_file_ids.get(note, [])
            logger.info("Flagged note: %r → files: %s", note[:80], file_ids)
            anomaly_ids.update(file_ids)

        # Step 5: Submit
        sorted_ids = sorted(anomaly_ids)
        logger.info("[bold green]Total anomalies: %d[/]", len(sorted_ids))
        logger.info("Anomaly IDs: %s", sorted_ids)

        answer: dict[str, list[str]] = {"recheck": sorted_ids}
        result_resp = submit_answer("evaluation", answer)
        logger.info("[bold green]Submission result: %s[/]", result_resp)


if __name__ == "__main__":
    run()
