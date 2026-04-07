"""S03E04 - negotiations: expose item-search tools for the hub agent."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

from lib.logging import setup_logging
from settings import settings

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / ".workspace"

CSV_BASE_URL = f"{settings.aidevs_hub_url}/dane/s03e04_csv"
CSV_FILES = ("cities.csv", "items.csv", "connections.csv")


def _download_csvs() -> None:
    """Download CSV data files if not already present."""
    WORKSPACE.mkdir(exist_ok=True)
    for name in CSV_FILES:
        target = WORKSPACE / name
        if target.exists():
            logger.info("CSV already exists: %s", target)
            continue
        url = f"{CSV_BASE_URL}/{name}"
        logger.info("Downloading %s", url)
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
        target.write_text(resp.text, encoding="utf-8")
        logger.info("Saved %s (%d bytes)", target, len(resp.text))


def check_result() -> dict[str, object]:
    """Poll the hub for the async negotiation result."""
    payload = {
        "apikey": settings.aidevs_key,
        "task": "negotiations",
        "answer": {"action": "check"},
    }
    resp = httpx.post(settings.aidevs_verify_address, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def run() -> None:
    setup_logging()
    _download_csvs()

    import dotenv
    import ngrok
    import uvicorn

    dotenv.load_dotenv()
    listener = ngrok.forward(8000, authtoken_from_env=True)
    public_url = str(listener.url())
    logger.info("Public URL: %s", public_url)

    import tasks.S03E04_negotiations.server as srv

    srv.PUBLIC_URL = public_url
    srv.check_result_fn = check_result

    logger.info("Starting server on port 8000 …")
    uvicorn.run(
        "tasks.S03E04_negotiations.server:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )


if __name__ == "__main__":
    run()
