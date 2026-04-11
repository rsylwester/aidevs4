"""LangChain agent loop for S04E05 foodwarehouse \u2014 bash-only in sandbox.

The agent has a single tool: ``run_bash``. Everything it needs to do
(inspect SQLite, generate signatures, build orders, call ``done``) is
reached via ``curl`` from inside the sandbox. The host watches bash
output for a Centrala flag (``{{FLG:...}}``) to detect success and exit
the loop cleanly.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.llm import get_llm
from tasks.S04E05_foodwarehouse.submit import (
    download_food4cities,
    prefetch_help,
    reset_orders,
)
from tasks.S04E05_foodwarehouse.tools import ALL_TOOL_SCHEMAS

if TYPE_CHECKING:
    from pathlib import Path

    from tasks.S04E05_foodwarehouse.sandbox import FoodwarehouseSandbox

logger = logging.getLogger(__name__)

_MODEL = "openai/gpt-5.3-chat"
_MAX_STEPS = 100
_MAX_RESULT_LOG_BYTES = 4000

_FLAG_PATTERN = re.compile(r"\{\{FLG:[^}]+\}\}")


_SYSTEM_PROMPT = """\
You are a capable, curious autonomous agent. You work in a loop: you think,
you act through tools, you observe the result, you adjust, and you try again.
You are not a one-shot answer generator \u2014 you are expected to explore, fail,
learn, and persist until the goal is achieved.

## Reasoning out loud (required)
Every time you act, think first \u2014 and make that thinking visible in your
message content, not hidden. Before each tool call (or batch of tool calls),
write a short reasoning block in your response content with these four parts:

1. **Observation** \u2014 what the most recent tool result (or the initial task)
   actually tells you. Quote specific values when it matters.
2. **Interpretation** \u2014 what you now believe about the problem, and what new
   questions this raises.
3. **Plan** \u2014 the next concrete step (or small sequence of steps) you will
   take, and *why this step in particular* will move you forward.
4. **Expected outcome** \u2014 what you expect to see if your hypothesis is right,
   and what you will conclude if you see something else instead.

Keep each block brief (a few bullets, not an essay). Think step by step, but
write efficient steps. Rewriting the same reasoning over and over is noise;
show only the delta \u2014 what changed since your last block.

When you make a decision, say *why* \u2014 name the evidence (e.g. a row from
SQLite, a field from food4cities) and where it came from. Name your
uncertainties too: if you are guessing, mark it as a guess and plan a way to
verify it before committing.

## How you work
- **Explore first, commit later.** Before you trust a hypothesis, look at the
  evidence. Use bash to inspect schemas, list rows, check field names, confirm
  details you are unsure about.
- **Iterate on feedback.** When Centrala says your order is wrong, treat that
  response as a gift: it tells you exactly what to fix. Read it carefully, form
  a specific hypothesis about the cause, and try again with a concrete
  correction. Do not repeat the same failing call unchanged.
- **Be creative with your shell.** You have a real bash \u2014 `curl`, `jq`,
  pipelines, `grep`, `awk`, variable substitution. Combine commands. Build
  small one-liners that answer your question directly.
- **Think before you finalize.** Cross-check your conclusions against the
  raw data one more time before you call `done`. It is cheaper to look than
  to fail a submission.
- **Never give up silently.** If something is blocking you, articulate what
  you believe the obstacle is, then design the next experiment to unblock it.
  Keep calling tools until you have genuinely solved the problem or
  demonstrably exhausted reasonable avenues.

## Your tool
- `run_bash(cmd)` \u2014 execute any bash command inside an isolated sandbox.
  `curl` and `jq` are installed. The env vars `$HUB_URL` (Centrala's /verify
  endpoint) and `$AIDEVS_KEY` (your apikey) are already exported \u2014 use them
  literally in your commands; never print the key to stdout. Output is
  truncated to 8KB; prefer targeted queries.

## Discipline
- Never call a tool without first writing the reasoning block described above.
- When a call fails, state your diagnosis (Observation + Interpretation) before
  proposing your next move (Plan).
- If you notice you are spinning (calling similar commands without new
  information), stop and write a fresh reasoning block: what are you actually
  trying to learn, and what is the smallest experiment that would answer it?
- You are done only when Centrala's `{tool: done}` response contains a flag
  of the form `{{FLG:...}}`. Keep iterating until you see that flag.
"""


def _build_user_message(help_data: dict[str, Any], food4cities: dict[str, Any]) -> str:
    help_block = json.dumps(help_data, ensure_ascii=False, indent=2)
    food_block = json.dumps(food4cities, ensure_ascii=False, indent=2)
    return f"""\
## Zadanie

Musisz uporz\u0105dkowa\u0107 prac\u0119 magazynu \u017cywno\u015bci i narz\u0119dzi tak, aby przygotowa\u0107
zamówienia, które zaspokoj\u0105 potrzeby wszystkich wskazanych miast. Nazwa
zadania na Centrali to `foodwarehouse`. Wszystkie wywo\u0142ania wysy\u0142asz do
`$HUB_URL` (to jest /verify), z polem `apikey=$AIDEVS_KEY`, `task=foodwarehouse`
oraz `answer={{...}}` zgodnie z help API poni\u017cej.

Twoje zadanie krok po kroku:

1. Ustal, jakie miasta bior\u0105 udzia\u0142 w operacji, na podstawie pliku
   `food4cities.json` (pe\u0142na tre\u015b\u0107 zainlinowana poni\u017cej).
2. Odczytaj z bazy SQLite (narz\u0119dzie `database`) dane potrzebne do
   wygenerowania podpisu i wyznaczenia `creatorID` oraz kodu `destination`
   dla ka\u017cdego miasta. Zacznij od `show tables`, potem sprawd\u017a schemat
   ka\u017cdej interesuj\u0105cej tabeli zanim u\u017cyjesz jej kolumn.
3. Dla ka\u017cdego miasta wygeneruj podpis narz\u0119dziem `signatureGenerator`
   (na bazie w\u0142a\u015bciwych danych u\u017cytkownika) i stwórz osobne zamówienie
   narz\u0119dziem `orders` z akcj\u0105 `create`. Wymagane pola: `title`,
   `creatorID`, `destination`, `signature`.
4. Do ka\u017cdego zamówienia dopisz \u015bci\u015ble te towary i ilo\u015bci, których
   potrzebuje miasto \u2014 bez braków i bez nadmiarów. Mo\u017cesz u\u017cy\u0107 trybu
   batch (obiekt `items` z wieloma pozycjami na raz) w akcji `append`.
5. Gdy wszystkie zamówienia s\u0105 gotowe i kompletne, wywo\u0142aj narz\u0119dzie
   `done`. Odpowied\u017a sukcesu zawiera flag\u0119 w formacie `{{{{FLG:...}}}}`.

Zasady operacyjne:

- Wszystkie curle kierujesz do `$HUB_URL`, pole `apikey` ustawiasz na
  `$AIDEVS_KEY`. Nigdy nie drukuj warto\u015bci `$AIDEVS_KEY` na stdout.
- Stan zamówie\u0144 zosta\u0142 ju\u017c zresetowany po stronie hosta przed uruchomieniem
  agenta \u2014 zaczynasz od czystego stanu. Je\u015bli co\u015b zepsujesz, wywo\u0142aj sam
  `{{tool: reset}}` i zacznij budowa\u0107 zamówienia od nowa.
- Liczba stworzonych zamówie\u0144 musi by\u0107 dok\u0142adnie równa liczbie miast w
  `food4cities.json`.
- Przed wywo\u0142aniem `done` u\u017cyj `{{tool: orders, action: get}}` \u017ceby zobaczy\u0107
  bie\u017c\u0105cy stan i zweryfikowa\u0107, \u017ce ka\u017cde miasto dosta\u0142o komplet towarów.
- Jedna dobra praktyka: najpierw zrób `help`, `database show tables`, obejrzyj
  schemat, zrób jeden pe\u0142ny przyk\u0142ad end-to-end dla jednego miasta i dopiero
  potem skaluj na pozosta\u0142e.

## API reference (verbatim response from `{{tool: help}}` on /verify)

```json
{help_block}
```

## food4cities.json (verbatim)

```json
{food_block}
```

## Przyk\u0142ad wywo\u0142ania /verify z bashem

Dwa warianty; drugi (heredoc + jq -n) pozwala unikn\u0105\u0107 cytowania piek\u0142a.

```bash
curl -s -X POST "$HUB_URL" \\
  -H "Content-Type: application/json" \\
  -d "$(jq -nc --arg k "$AIDEVS_KEY" \\
      '{{apikey:$k, task:"foodwarehouse", answer:{{tool:"database", query:"show tables"}}}}')" \\
  | jq
```

Zaczynaj.
"""


class _ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


def _extract_tool_calls(response_msg: Any) -> list[_ToolCall]:
    raw_calls: list[dict[str, Any]] = getattr(response_msg, "tool_calls", []) or []
    return [
        _ToolCall(
            id=str(tc.get("id", "")),
            name=str(tc.get("name", "")),
            args=tc.get("args", {}) or {},
        )
        for tc in raw_calls
    ]


def _get_content(response_msg: Any) -> str:
    content: Any = getattr(response_msg, "content", "")
    return content if isinstance(content, str) else str(content)


def _short_args(args: dict[str, Any], limit: int = 200) -> str:
    return json.dumps(args, ensure_ascii=False, default=str)[:limit]


def _short_result(result_str: str, limit: int = 200) -> str:
    return result_str[:limit].replace("\n", " ")


def _dispatch_run_bash(sandbox: FoodwarehouseSandbox, args: dict[str, Any]) -> tuple[str, str | None]:
    """Run the agent's bash command; return (tool_response_json, flag_if_seen)."""
    cmd_val = args.get("cmd", "")
    if not isinstance(cmd_val, str) or not cmd_val.strip():
        return json.dumps({"error": "run_bash requires a non-empty 'cmd' string"}), None
    result = sandbox.run_bash(cmd_val)
    flag_match = _FLAG_PATTERN.search(result.output)
    flag = flag_match.group(0) if flag_match else None
    response = json.dumps(
        {"exit_code": result.exit_code, "output": result.output, "truncated": result.truncated},
        ensure_ascii=False,
    )
    return response, flag


def run_agent(sandbox: FoodwarehouseSandbox, workspace: Path) -> dict[str, Any]:
    """Drive the LangChain tool-calling loop until Centrala returns a flag."""
    food4cities = download_food4cities(workspace)
    reset_orders()
    help_data = prefetch_help()

    llm = get_llm(model=_MODEL)
    llm_with_tools = llm.bind(tools=ALL_TOOL_SCHEMAS)

    messages: list[Any] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(help_data, food4cities)},
    ]

    for step in range(1, _MAX_STEPS + 1):
        logger.info("[dim]  Step %d/%d[/]", step, _MAX_STEPS)
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        content = _get_content(response)
        if content:
            logger.info("[green]  Agent: %s[/]", content[:500])

        # Belt-and-suspenders: the model sometimes restates the flag in its
        # own content after a successful /verify response whose raw output
        # did not contain the literal {{FLG:...}} form (e.g. jq unwrapped it
        # into a plain JSON "flag" field). If we see the flag pattern in
        # the assistant's narrative, trust it and exit.
        content_flag_match = _FLAG_PATTERN.search(content)
        if content_flag_match:
            flag_str = content_flag_match.group(0)
            logger.info("[bold green]Detected Centrala flag in agent narrative: %s[/]", flag_str)
            return {"flag": flag_str, "final_output": content}

        tool_calls = _extract_tool_calls(response)
        if not tool_calls:
            logger.info("[yellow]  Agent stopped calling tools at step %d, nudging...[/]", step)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Keep going. Either run more bash commands to gather evidence, or "
                        "call the `done` tool via curl once every order is complete. "
                        "If you believe you have already obtained the flag in a previous "
                        "tool result, state it one more time in the exact `{{FLG:...}}` "
                        "form in your next message and I will detect it and finish."
                    ),
                }
            )
            continue

        for tc in tool_calls:
            args_str = _short_args(tc.args)
            logger.info("[bold yellow]>> tool:[/] %s(%s)", tc.name, args_str)
            sandbox.append_log(f"tool-call: {tc.name}", args_str)

            flag: str | None = None
            if tc.name == "run_bash":
                result_str, flag = _dispatch_run_bash(sandbox, tc.args)
            else:
                result_str = json.dumps({"error": f"Unknown tool: {tc.name}"})

            logger.info(
                "[bold cyan]<< tool:[/] %s -> %d bytes | %s",
                tc.name,
                len(result_str),
                _short_result(result_str),
            )
            sandbox.append_log(f"tool-result: {tc.name} ({len(result_str)} bytes)", result_str[:_MAX_RESULT_LOG_BYTES])

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

            if flag is not None:
                logger.info("[bold green]Detected Centrala flag in bash output: %s[/]", flag)
                return {"flag": flag, "final_output": result_str}

    msg = f"Agent did not produce a Centrala flag within {_MAX_STEPS} steps"
    raise RuntimeError(msg)
