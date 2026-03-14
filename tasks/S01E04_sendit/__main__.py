"""S01E04 - sendit: fill SPK transport declaration by reading multi-file documentation."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, cast

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool  # pyright: ignore[reportUnknownVariableType]

from lib.hub import submit_answer
from lib.llm import get_llm
from lib.logging import setup_logging

logger = logging.getLogger(__name__)

ARTIFACTS = Path(__file__).parent / ".artifacts"
DOC_BASE_URL = "https://***REDACTED***/dane/doc/"

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


# -- Agent tools --------------------------------------------------------------


@tool
def download_doc(url: str) -> str:
    """Download a document from the SPK documentation server.

    Accepts a full URL or a filename relative to the doc base URL.
    Text files are returned as content; images are saved and must be read with read_artifact.
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


@tool
def list_artifacts() -> str:
    """List all files currently saved in the artifacts directory."""
    files = sorted(ARTIFACTS.iterdir())
    if not files:
        return "No artifacts yet."
    lines = [f"{f.name} ({f.stat().st_size} bytes)" for f in files if f.is_file()]
    return "\n".join(lines)


@tool
def read_artifact(filename: str) -> str:
    """Read an artifact file. Text files return content; images are described using vision AI."""
    filepath = ARTIFACTS / filename

    if not filepath.exists():
        return f"Error: {filename} not found in artifacts."

    is_image = any(filename.lower().endswith(ext) for ext in _IMAGE_EXTENSIONS)

    if not is_image:
        return filepath.read_text(encoding="utf-8")

    # Use vision LLM to describe the image
    logger.info("[bold cyan]Analyzing image with vision: %s[/]", filename)
    img_bytes = filepath.read_bytes()
    b64 = base64.b64encode(img_bytes).decode("ascii")

    suffix = filepath.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
    media_type = mime.get(suffix, "image/png")

    vision_llm = get_llm("openai/gpt-4.1-mini")
    vision_response: Any = vision_llm.invoke(
        [
            HumanMessage(
                content=[
                    {
                        "type": "text",
                        "text": "Describe this image in detail. If it contains a table, reproduce the table "
                        "data as structured text. Include ALL text, numbers, route codes, and city names visible.",
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}"}},
                ]
            )
        ]
    )
    description: str = str(vision_response.content)
    logger.info("[green]Vision description: %s[/]", description[:200])
    return description


@tool
def submit_final_answer(declaration: str) -> str:
    """Submit the completed SPK declaration to the Hub API for verification."""
    logger.info("[bold cyan]Submitting declaration...[/]")
    try:
        result = submit_answer("sendit", {"declaration": declaration})
    except httpx.HTTPStatusError as exc:
        error_body: Any = exc.response.json()  # pyright: ignore[reportUnknownMemberType]
        logger.warning("[bold red]Submission rejected: %s[/]", error_body)
        return f"REJECTED: {error_body}. Review the declaration and try again."
    else:
        return f"SUCCESS: {result}"


# -- Agent system prompt ------------------------------------------------------

AGENT_SYSTEM_PROMPT = """\
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
"""


# -- Main --------------------------------------------------------------------


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)

    from lib.tracing import langfuse_session

    with langfuse_session("S01E04-sendit") as session_id:
        logger.info("[bold cyan]Session: %s[/]", session_id)

        llm = get_llm("openai/gpt-4o")
        agent_tools: list[Any] = [
            download_doc,
            list_artifacts,
            read_artifact,
            submit_final_answer,
        ]
        llm_with_tools = llm.bind_tools(agent_tools)  # pyright: ignore[reportUnknownMemberType]
        tool_map: dict[str, Any] = {t.name: t for t in agent_tools}  # pyright: ignore[reportUnknownMemberType]

        messages: list[Any] = [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(
                content="Please read the SPK documentation and fill out the transport declaration for "
                "the reactor fuel cassettes shipment from Gdansk to Zarnowiec. "
                "Start by downloading index.md."
            ),
        ]

        max_iterations = 20
        for i in range(max_iterations):
            logger.info("[bold blue]Agent iteration %d/%d[/]", i + 1, max_iterations)
            response: AIMessage = llm_with_tools.invoke(messages)  # pyright: ignore[reportAssignmentType, reportUnknownMemberType]
            messages.append(response)

            tool_calls = cast("list[dict[str, Any]]", response.tool_calls)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            if not tool_calls:
                logger.info("[bold green]Agent finished: %s[/]", response.content)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                break

            for tc in tool_calls:
                tool_name: str = tc["name"]
                tool_args: dict[str, Any] = tc["args"]
                logger.info("[dim]Calling tool: %s(%s)[/]", tool_name, tool_args)
                tool_fn = tool_map[tool_name]
                result: str = tool_fn.invoke(tool_args)  # pyright: ignore[reportUnknownMemberType]
                messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))
        else:
            logger.error("[bold red]Agent hit max iterations (%d)[/]", max_iterations)


if __name__ == "__main__":
    run()
