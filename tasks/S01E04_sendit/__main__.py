"""S01E04 - sendit: fill SPK transport declaration by reading multi-file documentation."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import openai
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from lib.hub import submit_answer
from lib.logging import setup_logging
from settings import settings

logger = logging.getLogger(__name__)

ARTIFACTS = Path(__file__).parent / ".artifacts"
DOC_BASE_URL = "https://***REDACTED***/dane/doc/"

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

SYSTEM_PROMPT = """\
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

# -- Tool schemas for OpenAI function calling --------------------------------

_TOOLS_FILE = Path(__file__).parent / "tools.json"
TOOLS: list[ChatCompletionToolParam] = json.loads(_TOOLS_FILE.read_text(encoding="utf-8"))


# -- Tool implementations ---------------------------------------------------


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    before_sleep=lambda rs: logger.warning(
        "[yellow]Attempt %d failed for download — retrying...[/]",
        rs.attempt_number,
    ),
)
def _fetch_url(url: str) -> httpx.Response:
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp


def _download_doc(url: str) -> str:
    if not url.startswith("http"):
        url = DOC_BASE_URL + url

    logger.info("[bold cyan]Downloading: %s[/]", url)
    resp = _fetch_url(url)

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


def _list_artifacts() -> str:
    files = sorted(ARTIFACTS.iterdir())
    if not files:
        return "No artifacts yet."
    lines = [f"{f.name} ({f.stat().st_size} bytes)" for f in files if f.is_file()]
    return "\n".join(lines)


def _read_artifact(filename: str, client: openai.OpenAI) -> str:
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
    mime_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
    media_type = mime_map.get(suffix, "image/png")

    vision_resp = client.chat.completions.create(
        model="openai/gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Describe images in detail. If it contains a table, reproduce the table data as structured text."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Describe this image in detail. If it contains a table, reproduce the table "
                            "data as structured text. Include ALL text, numbers, route codes, and city names visible."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{b64}"},
                    },
                ],
            },
        ],
    )
    description = vision_resp.choices[0].message.content or ""
    logger.info("[green]Vision description: %s[/]", description[:200])
    return description


def _submit_final_answer(declaration: str) -> str:
    logger.info("[bold cyan]Submitting declaration...[/]")
    try:
        result: Any = submit_answer("sendit", {"declaration": declaration})
    except httpx.HTTPStatusError as exc:
        error_body: Any = exc.response.json()
        logger.warning("[bold red]Submission rejected: %s[/]", error_body)
        return f"REJECTED: {error_body}. Review the declaration and try again."
    else:
        return f"SUCCESS: {result}"


# -- Tool dispatch -----------------------------------------------------------


def _execute_tool_call(tool_call: ChatCompletionMessageFunctionToolCall, client: openai.OpenAI) -> str:
    fn_name = tool_call.function.name
    args: dict[str, Any] = json.loads(tool_call.function.arguments)
    logger.info("[bold cyan]Tool call: %s(%s)[/]", fn_name, args)

    try:
        match fn_name:
            case "download_doc":
                return _download_doc(**args)
            case "list_artifacts":
                return _list_artifacts()
            case "read_artifact":
                return _read_artifact(client=client, **args)
            case "submit_final_answer":
                return _submit_final_answer(**args)
            case _:
                return f"Error: unknown tool '{fn_name}'"
    except Exception as exc:
        logger.exception("Tool %s failed", fn_name)
        return f"Error: {exc}"


# -- Agentic loop ------------------------------------------------------------

MAX_ITERATIONS = 30


def _run_agent(client: openai.OpenAI) -> str:
    messages: list[ChatCompletionMessageParam] = [
        ChatCompletionSystemMessageParam(role="system", content=SYSTEM_PROMPT),
        ChatCompletionUserMessageParam(
            role="user",
            content=(
                "Please read the SPK documentation and fill out the transport declaration for "
                "the reactor fuel cassettes shipment from Gdansk to Zarnowiec. "
                "Start by downloading index.md."
            ),
        ),
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info("[bold]Iteration %d/%d[/]", iteration, MAX_ITERATIONS)

        response = client.chat.completions.create(
            model="openai/gpt-4o",
            messages=messages,
            tools=TOOLS,
        )

        choice = response.choices[0]
        assistant_msg = choice.message

        # Build assistant message param for history
        assistant_param: dict[str, Any] = {"role": "assistant"}
        if assistant_msg.content:
            assistant_param["content"] = assistant_msg.content
        tool_calls = [tc for tc in (assistant_msg.tool_calls or []) if tc.type == "function"]

        if tool_calls:
            assistant_param["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(ChatCompletionAssistantMessageParam(**assistant_param))

        # If no tool calls, check if the agent actually succeeded or gave up
        if not tool_calls:
            final = assistant_msg.content or "(no content)"
            if "SUCCESS" in final:
                logger.info("[bold green]Agent finished[/]")
                return final
            # Agent stopped without succeeding — nudge it to keep trying
            logger.warning("[bold yellow]Agent stopped without success, nudging to continue...[/]")
            messages.append(
                ChatCompletionUserMessageParam(
                    role="user",
                    content=(
                        "You have not succeeded yet. Use your tools to investigate further "
                        "and fix the declaration. Do NOT give up — keep trying."
                    ),
                ),
            )
            continue

        # Execute each tool call and append results
        for tc in tool_calls:
            result = _execute_tool_call(tc, client)
            messages.append(
                ChatCompletionToolMessageParam(role="tool", tool_call_id=tc.id, content=result),
            )
            if result.startswith("SUCCESS:"):
                logger.info("[bold green]Task completed: %s[/]", result)
                return result

    return "Max iterations reached without completion."


# -- Main --------------------------------------------------------------------


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)

    from langfuse.openai import register_tracing as _register_tracing

    from lib.tracing import langfuse_session

    _register_tracing()
    client = openai.OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key,
    )

    with langfuse_session("S01E04-sendit") as session_id:
        logger.info("[bold cyan]Session: %s[/]", session_id)
        result = _run_agent(client)
        logger.info("[bold green]Result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
