"""S04E04 — Filesystem: reconstruct Natan's trade notes on Centrala's fake FS."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import httpx

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from settings import settings
from tasks.S04E04_filesystem.agent import run_agent
from tasks.S04E04_filesystem.sandbox import NotesSandbox, docker_available

logger = logging.getLogger(__name__)

_WORKSPACE = Path(__file__).parent / ".workspace"
_NOTES_DIR = _WORKSPACE / "notes"
_SESSION_LOG = _WORKSPACE / "session_log.md"
_NOTES_ZIP_PATH = "/dane/natan_notes.zip"


def _download_and_extract() -> None:
    if _NOTES_DIR.exists() and any(_NOTES_DIR.iterdir()):
        logger.info("[dim]Notes already extracted at %s[/]", _NOTES_DIR)
        return

    _NOTES_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{settings.aidevs_hub_url.rstrip('/')}{_NOTES_ZIP_PATH}"
    logger.info("[cyan]Downloading %s...[/]", url)
    resp = httpx.get(url, timeout=60, follow_redirects=True)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(_NOTES_DIR)

    count = sum(1 for _ in _NOTES_DIR.rglob("*") if _.is_file())
    logger.info("[bold green]Extracted %d files to %s[/]", count, _NOTES_DIR)


def run() -> None:
    """Entry point for S04E04 filesystem task."""
    setup_logging()

    if not docker_available():
        msg = "Docker CLI not found on PATH — Daytona self-hosted requires docker compose"
        raise RuntimeError(msg)

    logger.info("[bold cyan]S04E04 filesystem — preparing notes[/]")
    _download_and_extract()

    with langfuse_session("S04E04_filesystem") as session_id:
        logger.info("[bold cyan]session=%s[/]", session_id)
        with NotesSandbox(notes_dir=_NOTES_DIR, log_file=_SESSION_LOG) as sandbox:
            done_body = run_agent(sandbox, _WORKSPACE)
        logger.info("[bold green]Final Centrala response: %s[/]", done_body)


if __name__ == "__main__":
    run()
