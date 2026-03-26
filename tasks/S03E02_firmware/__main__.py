"""S03E02 - firmware: Debug firmware on a restricted Linux VM via shell API."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import openai
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)

from lib.hub import submit_answer as hub_submit
from lib.logging import setup_logging
from settings import settings
from tasks.S03E02_firmware.shell import ShellClient

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / ".workspace"
MAX_ITERATIONS = 50
WARN_AT_ITERATION = 40

_TOOLS_FILE = Path(__file__).parent / "tools.json"
TOOLS: list[ChatCompletionToolParam] = json.loads(_TOOLS_FILE.read_text(encoding="utf-8"))

SYSTEM_PROMPT_TEMPLATE = """\
You are a firmware debugging specialist. You have access to a restricted Linux VM via a shell API.

## Task
A firmware binary at /opt/firmware/cooler/cooler.bin fails to run correctly. Your job:
1. Read settings.ini and fix any misconfiguration (use editline to change lines)
2. Remove any lock files that block execution (use rm)
3. Find the password required by cooler.bin (check history, /home, /tmp, find *pass*)
4. Run the binary: /opt/firmware/cooler/cooler.bin <password>
5. Extract the ECCS-formatted confirmation code from its output
6. Submit the confirmation code using submit_answer

## How to run binaries
You can execute binaries by their absolute path, e.g.: /opt/firmware/cooler/cooler.bin admin1
The binary may need a password as argument. Check history and pass.txt files for clues.

## Available shell commands
{available_commands}

## Initial reconnaissance

### Help output
{help_output}

### /opt/firmware listing
{firmware_ls}

### /opt/firmware/cooler listing
{cooler_ls}

## Critical rules
- This is a NON-STANDARD restricted shell. Each command is a SINGLE operation — NO chaining (&&, ||, ;) or pipes (|).
- Always use ABSOLUTE paths (e.g., "cat /opt/firmware/cooler/settings.ini"), not relative paths.
- To edit files use: editline <file> <line-number> <new-content> (replaces one line at a time).
- NEVER access /etc, /root, /proc, or any path listed in .gitignore — triggers an instant ban.
- The following paths are FORBIDDEN (from .gitignore) and will trigger a ban:
{forbidden_paths}
- Do NOT cat, ls, or access any of the above paths.
- NEVER cat binary files (.bin, .so, .exe, etc.) — they will corrupt the context. Use ls to inspect them.
- If banned, use sleep_seconds with the seconds_left value from the ban response, then try a DIFFERENT approach.
- The VM filesystem is read-only except /opt/firmware — only modify files there.
- When you find the ECCS confirmation code, submit it immediately using submit_answer.
- Be efficient. You have {max_iterations} iterations total.
"""


def _run_init_steps(shell: ShellClient) -> dict[str, str]:
    """Execute hardcoded initialization steps before the agent loop."""
    logger.info("[AGENT] Step 1/5: Rebooting VM...")
    shell.reboot()

    logger.info("[AGENT] Step 2/5: Fetching help...")
    help_output = shell.help()

    logger.info("[AGENT] Step 3/5: Listing /opt/firmware...")
    firmware_ls = shell.execute("ls /opt/firmware")

    logger.info("[AGENT] Step 4/5: Listing /opt/firmware/cooler...")
    cooler_ls = shell.execute("ls /opt/firmware/cooler")

    logger.info("[AGENT] Step 5/5: Scanning .gitignore files...")
    forbidden: list[str] = []
    # Check cooler dir for .gitignore (we know it has one from the listing)
    if ".gitignore" in cooler_ls:
        forbidden.extend(shell.scan_gitignore("/opt/firmware/cooler"))

    available_commands = "\n".join(sorted(shell.allowed_commands))
    forbidden_paths = "\n".join(forbidden) if forbidden else "(none)"

    return {
        "help_output": help_output,
        "firmware_ls": firmware_ls,
        "cooler_ls": cooler_ls,
        "available_commands": available_commands,
        "forbidden_paths": forbidden_paths,
    }


def _build_system_prompt(init_context: dict[str, str]) -> str:
    """Build the system prompt from template and init context."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        **init_context,
        max_iterations=MAX_ITERATIONS,
    )


def _execute_tool_call(
    fn_name: str,
    args: dict[str, Any],
    shell: ShellClient,
) -> str:
    """Dispatch a tool call and return the result string."""
    logger.info("[AGENT] Tool: %s(%s)", fn_name, args)

    match fn_name:
        case "execute_shell_command":
            return shell.execute(str(args["cmd"]))
        case "sleep_seconds":
            seconds = min(int(args["seconds"]), 180)
            time.sleep(seconds)
            msg = f"Waited {seconds} seconds, ready to continue."
            logger.info("[AGENT] %s", msg)
            return msg
        case "submit_answer":
            code = str(args["confirmation_code"])
            logger.info("[SUBMIT] Submitting confirmation code: %s", code)
            try:
                result: Any = hub_submit("firmware", {"confirmation": code.strip()})
            except Exception as exc:
                logger.warning("[SUBMIT] Hub rejected: %s", exc)
                return f"REJECTED: {exc}. Review the code and try again."
            else:
                logger.info("[SUBMIT] Hub response: %s", result)
                return f"SUCCESS: {result}"
        case _:
            return f"Error: unknown tool '{fn_name}'"


def _log_token_usage(usage: Any) -> None:
    """Log token usage from an OpenAI completion response."""
    if usage is None:
        return
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    completion = getattr(usage, "completion_tokens", 0) or 0
    total = getattr(usage, "total_tokens", 0) or 0
    # Cached tokens may be nested in prompt_tokens_details
    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details:
        cached = getattr(details, "cached_tokens", 0) or 0
    logger.info(
        "[LLM] prompt=%d completion=%d cached=%d total=%d",
        prompt,
        completion,
        cached,
        total,
    )


def _run_agent(
    client: openai.OpenAI,
    shell: ShellClient,
    init_context: dict[str, str],
) -> str:
    """Run the LLM agent loop with function calling."""
    system_prompt = _build_system_prompt(init_context)
    messages: list[ChatCompletionMessageParam] = [
        ChatCompletionSystemMessageParam(role="system", content=system_prompt),
        ChatCompletionUserMessageParam(
            role="user",
            content=(
                "Debug the firmware at /opt/firmware/cooler/cooler.bin. "
                "Find the password, fix the configuration, run the binary, "
                "and submit the ECCS confirmation code. Start exploring now."
            ),
        ),
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):
        if iteration == WARN_AT_ITERATION:
            logger.warning("[AGENT] ⚠ Iteration %d/%d — running low!", iteration, MAX_ITERATIONS)

        logger.info("[AGENT] Iteration %d/%d", iteration, MAX_ITERATIONS)

        response = client.chat.completions.create(
            model="openai/gpt-5.4",
            messages=messages,
            tools=TOOLS,
        )

        choice = response.choices[0]
        assistant_msg = choice.message
        _log_token_usage(response.usage)

        # Log assistant reasoning
        if assistant_msg.content:
            logger.info("[AGENT] Reasoning: %s", assistant_msg.content[:500])

        # Build assistant message for history
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

        # No tool calls — check for completion or nudge
        if not tool_calls:
            final = assistant_msg.content or "(no content)"
            if "SUCCESS" in final:
                logger.info("[AGENT] Agent finished successfully")
                return final
            logger.warning("[AGENT] No tool calls, nudging agent to continue...")
            messages.append(
                ChatCompletionUserMessageParam(
                    role="user",
                    content=(
                        "You haven't submitted the answer yet. Keep investigating — "
                        "use execute_shell_command to explore the VM and find the solution."
                    ),
                ),
            )
            continue

        # Execute tool calls
        for tc in tool_calls:
            fn_name = tc.function.name
            try:
                args: dict[str, Any] = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            try:
                result = _execute_tool_call(fn_name, args, shell)
            except Exception as exc:
                logger.exception("[AGENT] Tool %s failed", fn_name)
                result = f"Error: {exc}"

            messages.append(
                ChatCompletionToolMessageParam(role="tool", tool_call_id=tc.id, content=result),
            )

            if result.startswith("SUCCESS:"):
                logger.info("[AGENT] Task completed: %s", result[:500])
                return result

    logger.warning("[AGENT] Max iterations (%d) reached without completion", MAX_ITERATIONS)
    return f"Max iterations ({MAX_ITERATIONS}) reached without completion."


def run() -> None:
    """Entry point for S03E02 firmware task."""
    setup_logging()
    WORKSPACE.mkdir(parents=True, exist_ok=True)

    from langfuse.openai import register_tracing as _register_tracing

    from lib.tracing import langfuse_session

    _register_tracing()
    client = openai.OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key,
    )
    shell = ShellClient()

    with langfuse_session("S03E02-firmware") as session_id:
        logger.info("[bold cyan]S03E02-firmware | session=%s[/]", session_id)

        # Phase 1: Hardcoded init
        logger.info("[bold]== Init phase ==[/]")
        init_context = _run_init_steps(shell)

        # Phase 2: Agent loop
        logger.info("[bold]== Agent loop ==[/]")
        result = _run_agent(client, shell, init_context)
        logger.info("[bold green]Result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
