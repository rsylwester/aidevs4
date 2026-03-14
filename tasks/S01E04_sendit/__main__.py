"""S01E04 - sendit: fill SPK transport declaration by reading multi-file documentation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx
from pydantic_ai import Agent
from pydantic_ai.messages import BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from lib.hub import submit_answer
from lib.logging import setup_logging
from settings import settings

logger = logging.getLogger(__name__)

ARTIFACTS = Path(__file__).parent / ".artifacts"
DOC_BASE_URL = "https://***REDACTED***/dane/doc/"

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _openrouter_model(model_name: str) -> OpenAIChatModel:
    """Create an OpenAI-compatible model routed through OpenRouter."""
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
        ),
    )


# -- Agent -------------------------------------------------------------------

agent = Agent(
    _openrouter_model("openai/gpt-4o"),
    instructions="""\
You are an SPK (System Przesylek Konduktorskich) documentation specialist. Your task is to \
fill out a transport declaration form correctly by reading the SPK documentation.

## Transport parameters
- NADAWCA (identyfikator): 450202122
- PUNKT NADAWCZY: Gdańsk
- PUNKT DOCELOWY: Żarnowiec
- Waga: 2800 kg
- Budżet: 0 PP (free — covered by System for strategic shipments)
- Zawartość: kasety z paliwem do reaktora
- UWAGI SPECJALNE: BRAK — do not add any notes
- Date: 2026-03-14

## Your workflow
1. Download `index.md` from the documentation server to discover the documentation structure.
2. Follow ALL `[include file="..."]` references — download and read every referenced document. \
Some files might be access-restricted; that's OK, just note that and move on.
3. If a file is an image (like .png), download it, then use read_artifact to get a vision description.
4. After reading ALL relevant docs, fill out the declaration template from zalacznik-E.md.
5. Submit the filled declaration using submit_final_answer.

## Critical rules for filling the declaration
- Preserve the EXACT formatting of the template (headers, separators, Polish diacritics).
- Copy template lines character-for-character from zalacznik-E.md, only replacing [placeholder] parts.
- Use information from the documentation for: category, route, fees, WDP, sender ID, etc.
- For UWAGI SPECJALNE put "BRAK" — do not add any special notes.
- Calculate WDP (extra wagons beyond standard 2): total = ceil(weight / capacity), WDP = total - 2.
- Check if the route is blocked and what exceptions apply.
- Check fee exemptions for the shipment category.

## Important
- Read ALL referenced attachments before filling the form — do not guess.
- If the hub rejects your submission, read the error carefully, investigate using your tools, \
and fix the declaration.
- Do NOT give up. Keep iterating until you succeed or exhaust all options.
""",
)


# -- Agent tools --------------------------------------------------------------


@agent.tool_plain
def download_doc(url: str) -> str:
    """Download a document from the SPK documentation server.

    Accepts a full URL or a filename relative to the doc base URL.
    Text files are returned as content; images are saved and must be read with read_artifact.

    Args:
        url: Full URL or filename relative to the doc base URL.
    """
    if not url.startswith("http"):
        url = DOC_BASE_URL + url

    logger.info("[bold cyan]Downloading: %s[/]", url)
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()

    content_type = resp.headers.get("content-type", "")
    filename = url.rsplit("/", maxsplit=1)[-1]
    filepath = ARTIFACTS / filename

    is_image = any(filename.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS) or "image" in content_type

    if is_image:
        filepath.write_bytes(resp.content)
        logger.info("[green]Saved image: %s (%d bytes)[/]", filename, len(resp.content))
        return f"Image saved as {filename}. Use read_artifact to view it."

    text = resp.text
    filepath.write_text(text, encoding="utf-8")
    logger.info("[green]Saved text: %s (%d chars)[/]", filename, len(text))
    return text


@agent.tool_plain
def list_artifacts() -> str:
    """List all files currently saved in the artifacts directory."""
    files = sorted(ARTIFACTS.iterdir())
    if not files:
        return "No artifacts yet."
    lines = [f"{f.name} ({f.stat().st_size} bytes)" for f in files if f.is_file()]
    return "\n".join(lines)


@agent.tool_plain
async def read_artifact(filename: str) -> str:
    """Read an artifact file. Text files return content; images are described using vision AI.

    Args:
        filename: Name of the file in the artifacts directory.
    """
    filepath = ARTIFACTS / filename

    if not filepath.exists():
        return f"Error: {filename} not found in artifacts."

    is_image = any(filename.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS)

    if not is_image:
        return filepath.read_text(encoding="utf-8")

    # Use vision LLM to describe the image
    logger.info("[bold cyan]Analyzing image with vision: %s[/]", filename)
    img_bytes = filepath.read_bytes()

    suffix = filepath.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
    media_type = mime.get(suffix, "image/png")

    vision_agent: Agent[None, str] = Agent(
        _openrouter_model("openai/gpt-4.1-mini"),
        instructions="Describe images in detail. If it contains a table, reproduce the table data as structured text.",
    )
    result = await vision_agent.run(
        [
            "Describe this image in detail. If it contains a table, reproduce the table "
            "data as structured text. Include ALL text, numbers, route codes, and city names visible.",
            BinaryContent(data=img_bytes, media_type=media_type),
        ],
    )
    description = result.output
    logger.info("[green]Vision description: %s[/]", description[:200])
    return description


@agent.tool_plain
def submit_final_answer(declaration: str) -> str:
    """Submit the completed SPK declaration to the Hub API for verification.

    Args:
        declaration: The filled-out SPK declaration text.
    """
    logger.info("[bold cyan]Submitting declaration...[/]")
    try:
        result: Any = submit_answer("sendit", {"declaration": declaration})
    except httpx.HTTPStatusError as exc:
        error_body: Any = exc.response.json()
        logger.warning("[bold red]Submission rejected: %s[/]", error_body)
        return f"REJECTED: {error_body}. Review the declaration and try again."
    else:
        return f"SUCCESS: {result}"


# -- Main --------------------------------------------------------------------


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)

    from lib.tracing import langfuse_session

    # Instrument all pydantic-ai agents → Langfuse via OTel
    Agent.instrument_all()

    with langfuse_session("S01E04-sendit") as session_id:
        logger.info("[bold cyan]Session: %s[/]", session_id)

        result = agent.run_sync(
            "Please read the SPK documentation and fill out the transport declaration for "
            "the reactor fuel cassettes shipment from Gdansk to Zarnowiec. "
            "Start by downloading index.md.",
        )
        logger.info("[bold green]Agent finished: %s[/]", result.output)


if __name__ == "__main__":
    run()
