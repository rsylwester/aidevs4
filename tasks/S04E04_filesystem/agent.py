"""LangChain agent loop for S04E04 filesystem — bash in sandbox + finalize.

The ``finalize`` tool submits the plan to Centrala *inside* the loop, so the
hub's verdict (batch errors, missing people, wrong goods, etc.) comes back as
a tool response. The agent can then run more bash to disambiguate and call
finalize again with the fix. The loop only exits when Centrala accepts
``{{action: done}}``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

from lib.llm import get_llm
from tasks.S04E04_filesystem.submit import prefetch_help, reset_filesystem, submit_plan
from tasks.S04E04_filesystem.tools import ALL_TOOL_SCHEMAS, Plan

if TYPE_CHECKING:
    from pathlib import Path

    from tasks.S04E04_filesystem.sandbox import NotesSandbox

logger = logging.getLogger(__name__)

_MODEL = "openai/gpt-5.3-chat"
_MAX_STEPS = 100
_MAX_RESULT_LOG_BYTES = 4000


_SYSTEM_PROMPT = """\
You are a capable, curious autonomous agent. You work in a loop: you think,
you act through tools, you observe the result, you adjust, and you try again.
You are not a one-shot answer generator — you are expected to explore, fail,
learn, and persist until the goal is achieved.

## Reasoning out loud (required)
Every time you act, think first — and make that thinking visible in your
message content, not hidden. Before each tool call (or batch of tool calls),
write a short reasoning block in your response content with these four parts:

1. **Observation** — what the most recent tool result (or the initial task)
   actually tells you. Quote specific values when it matters.
2. **Interpretation** — what you now believe about the problem, and what new
   questions this raises.
3. **Plan** — the next concrete step (or small sequence of steps) you will
   take, and *why this step in particular* will move you forward.
4. **Expected outcome** — what you expect to see if your hypothesis is right,
   and what you will conclude if you see something else instead.

Keep each block brief (a few bullets, not an essay). Think step by step, but
write efficient steps. Rewriting the same reasoning over and over is noise;
show only the delta — what changed since your last block.

When you make a decision (e.g. "this person is Rafał Kisiel, not Kisiel"),
say *why* — name the evidence and the file/line it came from. Name your
uncertainties too: if you are guessing, mark it as a guess and plan a way to
verify it before committing.

## How you work
- **Explore first, commit later.** Before you trust a hypothesis, look at the
  evidence. Use your tools to inspect the environment, check your assumptions,
  and confirm details you are unsure about.
- **Iterate on feedback.** When a tool or external system tells you something
  is wrong, treat that response as a gift: it tells you exactly what to fix.
  Read it carefully, form a specific hypothesis about the cause, and try again
  with a concrete correction. Do not repeat the same failing call unchanged.
- **Be creative with your shell.** You have a real bash — pipelines, grep,
  awk, find, comparisons, even curl. Use them. Combine commands. Build small
  one-liners that answer your question directly instead of dumping large
  files and re-reading them.
- **Think before you finalize.** Cross-check your conclusions against the
  raw data one more time before you commit. It is cheaper to look than to
  fail a submission.
- **Never give up silently.** If something is blocking you, articulate what
  you believe the obstacle is, then design the next experiment to unblock it.
  Keep calling tools until you have genuinely solved the problem or
  demonstrably exhausted reasonable avenues.

## Your tools
1. `run_bash(cmd)` — execute any bash command inside an isolated sandbox.
   Use it to explore, measure, cross-check, and reason about the data you
   are given. Output is truncated for you; prefer targeted queries.
2. `finalize(...)` — submit your final structured answer. This is the
   commit point. Its response will either confirm success or tell you what
   is wrong so you can iterate. You may call it as many times as you need —
   each call supersedes the previous one.

## Discipline
- Never call a tool without first writing the reasoning block described above.
- When a call fails, state your diagnosis (Observation + Interpretation) before
  proposing your next move (Plan).
- When you think you are done, call `finalize`. When `finalize` reports an
  error, go back to exploring — do not just call finalize again with the
  same arguments.
- If you notice you are spinning (calling similar commands without new
  information), stop and write a fresh reasoning block: what are you actually
  trying to learn, and what is the smallest experiment that would answer it?
"""


def _build_system_prompt() -> str:
    return _SYSTEM_PROMPT


def _build_user_message(help_data: dict[str, Any]) -> str:
    help_block = json.dumps(help_data, ensure_ascii=False, indent=2)
    return f"""\
## Zadanie

Twoje zadanie polega na logicznym uporządkowaniu notatek Natana w naszym
wirtualnym file systemie. Potrzebujemy dowiedzieć się, które miasta brały
udział w handlu, jakie osoby odpowiadały za ten handel w konkretnych miastach
oraz które towary były przez kogo sprzedawane.

Nazwa zadania to: `filesystem`. Wszystkie operacje wykonujesz przez
`/verify/`. Notatki Natana znajdują się w sandboxie w katalogu `/notes`
(tylko do odczytu). Podgląd utworzonego systemu plików znajduje się pod
adresem https://hub.ag3nts.org/filesystem_preview.html — możesz go pobrać
przez `curl` jeśli uznasz to za przydatne.

## Wymagania (verbatim od Centrali)

Potrzebujemy trzech katalogów: `/miasta`, `/osoby` oraz `/towary`.

- **`/miasta`** — pliki o nazwach (w mianowniku) takich jak miasta opisywane
  przez Natana. W środku tych plików powinna być struktura JSON z towarami,
  jakie potrzebuje to miasto i ile tego potrzebuje (bez jednostek).
- **`/osoby`** — pliki z notatkami na temat osób, które odpowiadają za handel
  w miastach. Każdy plik powinien zawierać imię i nazwisko jednej osoby i
  link (w formacie markdown) do miasta, którym ta osoba zarządza. Nazwa pliku
  w `/osoby` nie ma znaczenia, ale jeśli nazwiesz plik tak jak dana osoba
  (z podkreśleniem zamiast spacji), a w środku dasz wymagany link, to system
  też rozpozna, o co chodzi.
- **`/towary/`** — pliki określające, które przedmioty są wystawione na
  sprzedaż. We wnętrzu każdego pliku powinny znajdować się linki (w formacie
  markdown) do **wszystkich** miast, które oferują ten towar — jeden towar
  może być sprzedawany przez wiele miast i walidator tego wymaga. Nazwa
  towaru to mianownik w liczbie pojedynczej, więc "koparka", a nie "koparki".

**Uwaga:** w nazwach plików nie używamy polskich znaków. Podobnie w tekstach
w JSON. Wszystkie nazwy powinny być w mianowniku (cities/people) lub
mianowniku liczby pojedynczej (goods).

## API reference (verbatim response from `{{action: help}}` on /verify/)

```json
{help_block}
```

## Jak `finalize` mapuje się na to API

Gdy wołasz `finalize(cities, people, goods)`, host buduje i wysyła:

1. `{{action: reset}}` — czyści cały filesystem (każda próba zaczyna od
   czystego stanu, więc retry jest idempotentny)
2. `{{action: createDirectory, path: /miasta}}` + `/osoby` + `/towary`
3. `createFile` dla każdego miasta, potem dla każdej osoby, potem dla
   każdego towaru (w tej kolejności, żeby linki markdown wskazywały na
   pliki które już istnieją w batchu)
4. `{{action: done}}` — uruchamia pełną walidację po stronie Centrali

Odpowiedź z `done` wraca do Ciebie jako wynik `finalize`. Jeśli `code < 0`,
Centrala powie Ci dokładnie co jest nie tak (np. `missing: ['Rafał Kisiel']`
albo `invalid good name`). Przeczytaj to, uruchom kolejne komendy bash żeby
zweryfikować notatki, i zawołaj `finalize` ponownie z poprawionym planem.

## Dodatkowe ograniczenia wynikające z help API

- `allowed_name_pattern: ^[a-z0-9_]+$` — host stosuje `unidecode` +
  lowercase + podkreślnik za spacje, ale Ty też powinieneś przekazywać
  nazwy bez polskich znaków.
- `max_file_name_length: 20` — trzymaj slug-i krótkie.
- `max_directory_depth: 3` — używamy tylko głębokości 2.
- `global_unique_names: true` — nazwa pliku w `/miasta` nie może pokrywać
  się z nazwą pliku w `/osoby` ani `/towary`. Jeśli miasto i towar dałyby
  ten sam slug, rozstrzygnij to PRZED wywołaniem `finalize`.

## Start

Zacznij od eksploracji `/notes`: `ls -la /notes`, `wc -l /notes/*`, potem
`cat` lub `head` na konkretnych plikach. Gdy masz pełny obraz, zawołaj
`finalize`.
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


def _dispatch_run_bash(sandbox: NotesSandbox, args: dict[str, Any]) -> str:
    cmd_val = args.get("cmd", "")
    if not isinstance(cmd_val, str) or not cmd_val.strip():
        return json.dumps({"error": "run_bash requires a non-empty 'cmd' string"})
    result = sandbox.run_bash(cmd_val)
    return json.dumps(
        {"exit_code": result.exit_code, "output": result.output, "truncated": result.truncated},
        ensure_ascii=False,
    )


def _dispatch_finalize(args: dict[str, Any], workspace: Path) -> tuple[dict[str, Any] | None, str]:
    """Validate + submit the plan. Returns (final_done_body, tool_response_str).

    final_done_body is non-None only when Centrala accepted the `done` action.
    The tool_response_str is the JSON string fed back to the LLM in either case.
    """
    try:
        plan = Plan.model_validate(args)
    except ValidationError as exc:
        err = {
            "ok": False,
            "stage": "local_validation",
            "errors": exc.errors(),
            "hint": "Fix the local validation errors and call finalize again.",
        }
        logger.warning("[red]Plan local validation failed[/]")
        return None, json.dumps(err, ensure_ascii=False, default=str)

    logger.info(
        "[cyan]Plan locally validated — %d cities, %d people, %d goods — submitting[/]",
        len(plan.cities),
        len(plan.people),
        len(plan.goods),
    )
    result = submit_plan(plan, workspace)
    if result["ok"]:
        logger.info("[bold green]Centrala accepted the plan[/]")
        return result["response"], json.dumps(
            {
                "ok": True,
                "stage": result["stage"],
                "response": result["response"],
                "note": "Centrala accepted the plan. You are done.",
            },
            ensure_ascii=False,
            default=str,
        )

    logger.warning("[yellow]Centrala rejected the plan at stage=%s[/]", result["stage"])
    return None, json.dumps(
        {
            "ok": False,
            "stage": result["stage"],
            "response": result["response"],
            "hint": (
                "Centrala rejected your plan. Read the response carefully — it usually "
                "says exactly what is missing or wrong. Run bash to disambiguate, then "
                "call finalize again with the corrected plan."
            ),
        },
        ensure_ascii=False,
        default=str,
    )


def run_agent(sandbox: NotesSandbox, workspace: Path) -> dict[str, Any]:
    """Drive the LangChain tool-calling loop until Centrala accepts the plan."""
    reset_filesystem()
    help_data = prefetch_help()
    llm = get_llm(model=_MODEL)
    llm_with_tools = llm.bind(tools=ALL_TOOL_SCHEMAS)

    messages: list[Any] = [
        {"role": "system", "content": _build_system_prompt()},
        {"role": "user", "content": _build_user_message(help_data)},
    ]

    for step in range(1, _MAX_STEPS + 1):
        logger.info("[dim]  Step %d/%d[/]", step, _MAX_STEPS)
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        content = _get_content(response)
        if content:
            logger.info("[green]  Agent: %s[/]", content[:500])

        tool_calls = _extract_tool_calls(response)
        if not tool_calls:
            logger.info("[yellow]  Agent stopped calling tools at step %d, nudging...[/]", step)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Keep going. Either run more bash commands to gather evidence, or "
                        "call finalize with the complete plan if you have enough."
                    ),
                }
            )
            continue

        for tc in tool_calls:
            args_str = _short_args(tc.args)
            logger.info("[bold yellow]>> tool:[/] %s(%s)", tc.name, args_str)
            sandbox.append_log(f"tool-call: {tc.name}", args_str)

            done_body: dict[str, Any] | None = None
            if tc.name == "run_bash":
                result_str = _dispatch_run_bash(sandbox, tc.args)
            elif tc.name == "finalize":
                done_body, result_str = _dispatch_finalize(tc.args, workspace)
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
            if done_body is not None:
                return done_body

    msg = f"Agent did not get Centrala to accept the plan within {_MAX_STEPS} steps"
    raise RuntimeError(msg)
