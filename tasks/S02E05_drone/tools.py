"""Tools for the drone operator agent."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from settings import settings

if TYPE_CHECKING:
    from tasks.S02E05_drone.tracking import TokenTracker

logger = logging.getLogger(__name__)

type ToolBundle = dict[str, Any]


def _send_instructions(instructions: list[str], tracker: TokenTracker) -> str:
    """Send instruction array to the drone API and capture flags."""
    payload: dict[str, Any] = {
        "apikey": settings.aidevs_key,
        "task": "drone",
        "answer": {"instructions": instructions},
    }
    logger.info("[yellow]Sending drone instructions:[/] %s", instructions)
    resp = httpx.post(settings.aidevs_verify_address, json=payload, timeout=30)
    data: dict[str, Any] = resp.json()
    response_str = json.dumps(data, ensure_ascii=False)
    logger.info("[cyan]Drone API response:[/] %s", response_str[:500])
    tracker.capture_flags(response_str)
    return response_str


def make_reset_drone(tracker: TokenTracker) -> ToolBundle:
    """Create the reset_drone tool -- sends hardReset to clear previous state."""

    def handler() -> str:
        return _send_instructions(["hardReset"], tracker)

    definition: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "reset_drone",
            "description": "Reset the drone to factory defaults. Call before starting a new mission attempt.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    return {"definition": definition, "handler": handler}


def make_send_mission(tracker: TokenTracker) -> ToolBundle:
    """Create the send_mission tool -- builds and sends the full instruction sequence.

    The LLM controls configuration parameters. The handler appends the
    mission objective and flight command internally.
    """

    def handler(
        *,
        destination: str,
        x: int,
        y: int,
        altitude: str = "10m",
        engine: bool = True,
        power: str = "100%",
        auto_return: bool = False,
    ) -> str:
        instructions = [
            f"setDestinationObject({destination})",
            f"set({x},{y})",
            f"set({altitude})",
        ]
        if engine:
            instructions.append("set(engineON)")
        if power:
            instructions.append(f"set({power})")
        if auto_return:
            instructions.append("set(return)")
        instructions += ["set(destroy)", "flyToLocation"]
        return _send_instructions(instructions, tracker)

    definition: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "send_mission",
            "description": (
                "Configure and launch a drone mission. Builds the full instruction "
                "sequence from your parameters and sends it to the game API. "
                "Read the server response carefully -- errors are hints about what to adjust."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "description": "Target object ID matching [A-Z]{3}[0-9]+[A-Z]{2}, e.g. PWR6132PL",
                    },
                    "x": {
                        "type": "integer",
                        "description": "Grid column (1-indexed, left to right)",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Grid row (1-indexed, top to bottom)",
                    },
                    "altitude": {
                        "type": "string",
                        "description": "Flight altitude with 'm' suffix, e.g. '10m', '50m'. Range 1-100m.",
                    },
                    "engine": {
                        "type": "boolean",
                        "description": "Whether to enable the engine (set(engineON)). Default true.",
                    },
                    "power": {
                        "type": "string",
                        "description": "Engine power with '%' suffix, e.g. '100%'. Range 0-100%.",
                    },
                    "auto_return": {
                        "type": "boolean",
                        "description": "Whether to add set(return) for automatic return after mission. Default false.",
                    },
                },
                "required": ["destination", "x", "y"],
            },
        },
    }
    return {"definition": definition, "handler": handler}
