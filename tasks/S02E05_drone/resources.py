"""Download and prepare drone API resources."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx
from markdownify import markdownify  # type: ignore[import-untyped]

from settings import settings

if TYPE_CHECKING:
    from pathlib import Path

    from tasks.S02E05_drone.tracking import TokenTracker

logger = logging.getLogger(__name__)

DRONE_HTML_URL = "***REMOVED***/dane/drone.html"
DRONE_MAP_URL = f"{settings.aidevs_hub_url}/data/{settings.aidevs_key}/drone.png"


def ensure_resources(resources_dir: Path) -> None:
    """Download drone.html and drone.png if not already cached."""
    html_path = resources_dir / "drone.html"
    if not html_path.exists():
        logger.info("Downloading drone documentation from %s", DRONE_HTML_URL)
        resp = httpx.get(DRONE_HTML_URL, timeout=30)
        resp.raise_for_status()
        html_path.write_text(resp.text, encoding="utf-8")
        logger.info("Saved drone.html (%d bytes)", len(resp.text))

    png_path = resources_dir / "drone.png"
    if not png_path.exists():
        logger.info("Downloading drone map from %s", DRONE_MAP_URL)
        resp = httpx.get(DRONE_MAP_URL, timeout=30)
        resp.raise_for_status()
        png_path.write_bytes(resp.content)
        logger.info("Saved drone.png (%d bytes)", len(resp.content))


def convert_html_to_markdown(resources_dir: Path) -> Path:
    """Convert drone.html to drone.md using markdownify with CSS stripped. Cached."""
    from bs4 import BeautifulSoup

    md_path = resources_dir / "drone.md"
    if md_path.exists():
        logger.info("Using cached drone.md")
        return md_path

    html_path = resources_dir / "drone.html"
    html_text = html_path.read_text(encoding="utf-8")

    # Strip <style> tags before conversion
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup.find_all("style"):
        tag.decompose()

    md_text: str = markdownify(str(soup), heading_style="ATX")
    md_path.write_text(md_text, encoding="utf-8")
    logger.info("Converted drone.html → drone.md (%d chars)", len(md_text))
    return md_path


def analyze_documentation(resources_dir: Path, tracker: TokenTracker) -> str:
    """Analyze drone.md with a thinking model. Returns structured analysis. Cached."""
    analysis_path = resources_dir / "drone_analysis.md"
    if analysis_path.exists():
        logger.info("Using cached drone_analysis.md")
        return analysis_path.read_text(encoding="utf-8")

    md_text = (resources_dir / "drone.md").read_text(encoding="utf-8")

    from tasks.S02E05_drone.llm import chat

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an expert API documentation analyst. Your task is to analyze drone API "
                "documentation and produce a clear, actionable reference. The documentation "
                "intentionally contains conflicting and misleading function names. Identify: "
                "1) The exact instruction string format expected in the instructions array "
                "2) Which functions/instructions are actually needed for a bombing mission "
                "3) Any traps or misleading elements in the docs "
                "4) The minimal correct sequence to: set destination, set landing sector, "
                "   configure flight, set mission objective to destroy, and initiate flight "
                "Be precise about exact string syntax expected in each instruction."
            ),
        },
        {
            "role": "user",
            "content": f"Analyze this drone API documentation thoroughly:\n\n{md_text}",
        },
    ]

    response = chat(model="openrouter/openai/gpt-5", messages=messages, label="doc-analyzer")
    tracker.track(response, label="doc-analyzer")

    result_text: str = response.content or ""
    analysis_path.write_text(result_text, encoding="utf-8")
    logger.info("Documentation analysis saved (%d chars)", len(result_text))
    return result_text
