"""LLM tool schema for the S04E05 foodwarehouse agent.

The agent is deliberately thin: it sees a single ``run_bash`` tool that
executes inside the Daytona sandbox. Everything else (Centrala's help doc,
food4cities.json, the SQLite database, the orders endpoint) is reached via
``curl`` from inside the sandbox using ``$HUB_URL`` and ``$AIDEVS_KEY``
environment variables.
"""

from __future__ import annotations

from typing import Any

RUN_BASH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_bash",
        "description": (
            "Execute a bash command inside the sandbox. The sandbox has `curl`, `jq`, "
            "and standard unix tools. Environment variables `$HUB_URL` (pointing at "
            "Centrala's /verify endpoint) and `$AIDEVS_KEY` (your apikey) are already "
            "exported. Use curl + jq to call the foodwarehouse API, inspect the SQLite "
            "database, generate signatures, and create/append orders. Output is "
            "truncated at 8KB \u2014 prefer targeted pipelines over dumping whole files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "A single bash command to run inside the sandbox.",
                },
            },
            "required": ["cmd"],
        },
    },
}


ALL_TOOL_SCHEMAS: list[dict[str, Any]] = [RUN_BASH_SCHEMA]
