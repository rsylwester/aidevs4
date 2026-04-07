"""S04E02 tools — windpower API caller with markdown session logging."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from settings import settings

logger = logging.getLogger(__name__)

_VERIFY_URL = settings.aidevs_verify_address
_TASK = "windpower"
_MAX_RESULT_LEN = 8000

_WORKSPACE = Path(__file__).parent / ".workspace"
_LOG_FILE = _WORKSPACE / "session_log.md"

# Module-level storage (set before agent starts / during execution)
_docs_data: dict[str, Any] = {}
_last_poll_results: list[dict[str, Any]] = []
_last_analysis: dict[str, Any] = {}


def set_docs_data(docs: dict[str, Any]) -> None:
    """Store turbine documentation for use by analyze_data."""
    global _docs_data
    _docs_data = docs


def init_log() -> None:
    """Initialize the markdown session log file."""
    _WORKSPACE.mkdir(exist_ok=True)
    _LOG_FILE.write_text(f"# S04E02 Windpower Session Log\n\nStarted: {datetime.now(UTC).isoformat()}\n\n")


def _append_log(heading: str, body: str) -> None:
    """Append a section to the markdown session log."""
    ts = datetime.now(UTC).strftime("%H:%M:%S")
    with _LOG_FILE.open("a") as f:
        f.write(f"## {ts} — {heading}\n\n```json\n{body}\n```\n\n")


def _raw_api_call(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST to the /verify endpoint and return parsed JSON."""
    answer: dict[str, Any] = {"action": action}
    if params:
        answer.update(params)

    body: dict[str, Any] = {
        "apikey": settings.aidevs_key,
        "task": _TASK,
        "answer": answer,
    }

    resp = httpx.post(_VERIFY_URL, json=body, timeout=30)
    data: dict[str, Any] = resp.json()
    return data


def call_api(action: str, params: dict[str, Any] | None = None) -> str:
    """POST to the /verify endpoint with given action and optional params."""
    if action == "get" and (not params or "param" not in params):
        return json.dumps({"error": "action 'get' requires a 'param' field in params"})
    logger.info("[yellow]>> API action=%r params=%s[/]", action, json.dumps(params or {}, ensure_ascii=False)[:200])
    _append_log(f"Request: {action}", json.dumps({"action": action, **(params or {})}, ensure_ascii=False, indent=2))

    try:
        data = _raw_api_call(action, params)
        data_str = json.dumps(data, ensure_ascii=False)
        logger.info("[cyan]<< API: %s[/]", data_str[:300])
        _append_log(f"Response: {action}", json.dumps(data, ensure_ascii=False, indent=2))
        return data_str[:_MAX_RESULT_LEN]
    except Exception as exc:
        msg = f"API error: {exc}"
        logger.warning("[red]%s[/]", msg)
        _append_log(f"Error: {action}", msg)
        return json.dumps({"error": msg})


def poll_results(expected: int, timeout_seconds: float = 30.0, poll_interval: float = 0.5) -> str:
    """Poll getResult repeatedly until expected number of results collected or timeout."""
    logger.info("[yellow]>> Polling for %d results (timeout=%.0fs)[/]", expected, timeout_seconds)
    _append_log("poll_results start", json.dumps({"expected": expected, "timeout": timeout_seconds}))

    collected: list[dict[str, Any]] = []
    t0 = time.monotonic()

    while len(collected) < expected and (time.monotonic() - t0) < timeout_seconds:
        try:
            data = _raw_api_call("getResult")
            code = data.get("code", 0)
            if code == 11:
                time.sleep(poll_interval)
                continue
            source = data.get("sourceFunction", "unknown")
            logger.info("[cyan]<< polled result %d/%d: %s[/]", len(collected) + 1, expected, source)
            _append_log(f"Polled result: {source}", json.dumps(data, ensure_ascii=False, indent=2))
            collected.append(data)
        except Exception as exc:
            logger.warning("[red]Poll error: %s[/]", exc)
            time.sleep(poll_interval)

    elapsed = time.monotonic() - t0
    logger.info("[green]>> Polling done: %d/%d results in %.1fs[/]", len(collected), expected, elapsed)

    # Store full results for analyze_data (avoids truncation through LLM)
    global _last_poll_results
    _last_poll_results = collected

    result_str = json.dumps(collected, ensure_ascii=False)
    _append_log("poll_results done", result_str)
    # Return summary to LLM (not full data — analyze_data uses stored copy)
    sources = [r.get("sourceFunction", "?") for r in collected]
    summary = json.dumps({"collected": len(collected), "sources": sources})
    return summary


def fire_async_gets() -> str:
    """Fire all 3 async get requests (weather, turbinecheck, powerplantcheck) in rapid succession."""
    results: list[dict[str, Any]] = []
    for param in ("weather", "turbinecheck", "powerplantcheck"):
        logger.info("[yellow]>> Firing get(%s)[/]", param)
        data = _raw_api_call("get", {"param": param})
        _append_log(f"fire_async_gets: {param}", json.dumps(data, ensure_ascii=False, indent=2))
        results.append({"param": param, "response": data})
    return json.dumps(results, ensure_ascii=False)


def fire_unlock_codes(config_points: list[dict[str, Any]]) -> str:
    """Fire unlockCodeGenerator for each config point. Returns count of queued requests."""
    count = 0
    for point in config_points:
        logger.info("[yellow]>> unlockCodeGenerator: %s[/]", json.dumps(point, ensure_ascii=False)[:150])
        data = _raw_api_call("unlockCodeGenerator", point)
        _append_log("fire_unlock_codes", json.dumps({"params": point, "response": data}, ensure_ascii=False, indent=2))
        count += 1
    logger.info("[green]>> Fired %d unlock code requests[/]", count)
    return json.dumps({"queued": count})


def analyze_data() -> str:
    """Deterministically analyze polled data and compute config points.

    Uses stored poll results (from last poll_results call) and turbine documentation
    to determine storm protection hours and production hours.
    Returns structured config points ready for fire_unlock_codes + submit_config.
    """
    results = _last_poll_results
    docs = _docs_data

    # Extract data by sourceFunction
    weather: dict[str, Any] = {}
    turbine: dict[str, Any] = {}
    powerplant: dict[str, Any] = {}
    for r in results:
        source = r.get("sourceFunction", "")
        match source:
            case "weather":
                weather = r
            case "turbinecheck":
                turbine = r
            case "powerplantcheck":
                powerplant = r
            case _:
                pass

    # Extract safety limits from docs
    safety: dict[str, Any] = docs.get("safety", {})
    cutoff_wind: float = float(safety.get("cutoffWindMs", 14))
    min_wind: float = float(safety.get("minOperationalWindMs", 4))
    rated_power: float = float(docs.get("ratedPowerKw", 14))

    # Parse power deficit
    deficit_str = str(powerplant.get("powerDeficitKw", "0"))

    # Yield lookup: wind speed -> yield fraction
    yield_table: list[dict[str, Any]] = docs.get("windPowerYieldPercent", [])

    def _estimate_yield(wind: float) -> float:
        """Estimate yield fraction for a given wind speed."""
        if wind < min_wind or wind > cutoff_wind:
            return 0.0
        best: float = 0.0
        for entry in yield_table:
            if "windMs" in entry and wind >= float(entry["windMs"]):
                y_str = str(entry["yieldPercent"])
                best = float(y_str.split("-")[0]) / 100.0
            elif "windMsRange" in entry:
                range_str = str(entry["windMsRange"])
                if "+" in range_str:
                    continue
                range_parts = range_str.split("-")
                low, high = float(range_parts[0]), float(range_parts[1])
                if low <= wind <= high:
                    best = float(str(entry["yieldPercent"]).split("-")[0]) / 100.0
        return best

    # Process forecast
    forecast: list[dict[str, Any]] = weather.get("forecast", [])
    storm_configs: list[dict[str, Any]] = []
    production_candidates: list[dict[str, Any]] = []

    for entry in forecast:
        ts = str(entry.get("timestamp", ""))
        wind = float(entry.get("windMs", 0))
        date_part, time_part = ts.split(" ", 1) if " " in ts else (ts, "00:00:00")

        if wind > cutoff_wind:
            storm_configs.append(
                {
                    "startDate": date_part,
                    "startHour": time_part,
                    "windMs": wind,
                    "pitchAngle": 90,
                    "turbineMode": "idle",
                }
            )
        elif wind >= min_wind:
            # Estimate power output
            est_yield = _estimate_yield(wind)
            est_power = rated_power * est_yield
            production_candidates.append(
                {
                    "startDate": date_part,
                    "startHour": time_part,
                    "windMs": wind,
                    "pitchAngle": 0,
                    "turbineMode": "production",
                    "estimatedPowerKw": round(est_power, 1),
                    "estimatedYield": round(est_yield, 2),
                }
            )

    # Sort production candidates by highest estimated power
    production_candidates.sort(key=lambda x: float(x.get("estimatedPowerKw", 0)), reverse=True)

    # Select the single best production hour (task asks for one "punkt")
    selected_production: list[dict[str, Any]] = production_candidates[:1]
    total_power = float(selected_production[0].get("estimatedPowerKw", 0)) if selected_production else 0.0

    # Build all config points (for unlock code generation — no unlockCode yet)
    _extract_keys = ("startDate", "startHour", "windMs", "pitchAngle")
    all_config_points: list[dict[str, Any]] = [
        {k: cfg[k] for k in _extract_keys} for cfg in [*storm_configs, *selected_production]
    ]

    result = {
        "storm_configs": storm_configs,
        "production_configs": selected_production,
        "all_config_points": all_config_points,
        "total_config_points": len(all_config_points),
        "powerplant_deficit_kw": deficit_str,
        "total_selected_production_kw": round(total_power, 1),
        "turbine_status": turbine.get("status", "unknown"),
        "summary": (
            f"{len(storm_configs)} storm hours (pitch 90, idle), "
            f"{len(selected_production)} production hours (pitch 0, production), "
            f"deficit {deficit_str} kW, selected production ~{round(total_power, 1)} kW"
        ),
    }

    global _last_analysis
    _last_analysis = result

    result_str = json.dumps(result, ensure_ascii=False, indent=2)
    logger.info("[green]>> analyze_data: %s[/]", result["summary"])
    _append_log("analyze_data", result_str)
    return result_str


def generate_codes_and_submit() -> str:
    """Fire unlock codes for all config points, poll results, match, and submit config.

    Uses stored analysis data from analyze_data(). Combines steps 5-7 into one call:
    1. Fire unlockCodeGenerator for each config point
    2. Poll until all codes collected
    3. Match codes to config points by startDate+startHour
    4. Submit batch config
    """
    analysis = _last_analysis
    all_points: list[dict[str, Any]] = analysis.get("all_config_points", [])
    storm_configs: list[dict[str, Any]] = analysis.get("storm_configs", [])
    prod_configs: list[dict[str, Any]] = analysis.get("production_configs", [])

    if not all_points:
        return json.dumps({"error": "No config points from analyze_data"})

    # Step 1: Fire all unlock code requests
    for point in all_points:
        logger.info("[yellow]>> unlockCodeGenerator: %s[/]", json.dumps(point, ensure_ascii=False)[:150])
        data = _raw_api_call("unlockCodeGenerator", point)
        _append_log(
            "unlock_code_request",
            json.dumps({"params": point, "response": data}, ensure_ascii=False, indent=2),
        )
    logger.info("[green]>> Fired %d unlock code requests[/]", len(all_points))

    # Step 2: Poll for all codes
    codes: list[dict[str, Any]] = []
    t0 = time.monotonic()
    timeout = 15.0
    while len(codes) < len(all_points) and (time.monotonic() - t0) < timeout:
        try:
            data = _raw_api_call("getResult")
            if data.get("code") == 11:
                time.sleep(0.5)
                continue
            logger.info("[cyan]<< unlock code %d/%d[/]", len(codes) + 1, len(all_points))
            _append_log("unlock_code_result", json.dumps(data, ensure_ascii=False, indent=2))
            codes.append(data)
        except Exception as exc:
            logger.warning("[red]Poll error: %s[/]", exc)
            time.sleep(0.5)

    logger.info(
        "[green]>> Collected %d/%d unlock codes in %.1fs[/]", len(codes), len(all_points), time.monotonic() - t0
    )

    # Step 3: Match codes to config points by startDate+startHour
    code_map: dict[str, str] = {}
    for code_result in codes:
        signed: dict[str, Any] = code_result.get("signedParams", {})
        key = f"{signed.get('startDate', '')} {signed.get('startHour', '')}"
        code_map[key] = str(code_result.get("unlockCode", ""))

    # Step 4: Build and submit config
    all_cfgs = [*storm_configs, *prod_configs]
    configs: dict[str, dict[str, Any]] = {}
    for cfg in all_cfgs:
        dt = f"{cfg['startDate']} {cfg['startHour']}"
        unlock_code = code_map.get(dt, "")
        configs[dt] = {
            "pitchAngle": cfg["pitchAngle"],
            "turbineMode": cfg["turbineMode"],
            "unlockCode": unlock_code,
        }

    logger.info("[yellow]>> Submitting config with %d entries[/]", len(configs))
    _append_log("submit_config", json.dumps(configs, ensure_ascii=False, indent=2))
    return call_api("config", {"configs": configs})


def prefetch_api(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call API and return parsed JSON dict. Used for pre-timer fetches."""
    raw = call_api(action, params)
    result: dict[str, Any] = json.loads(raw)
    return result


# ---------------------------------------------------------------------------
# Tool schemas for LLM agent
# ---------------------------------------------------------------------------

CALL_API_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "call_api",
        "description": (
            "Call the windpower API with an action and optional parameters. "
            "Actions: start, done, get (with param). "
            "For batch operations use the specialized tools instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform",
                },
                "params": {
                    "type": "object",
                    "description": "Additional parameters for the action",
                },
            },
            "required": ["action"],
        },
    },
}

FIRE_ASYNC_GETS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "fire_async_gets",
        "description": (
            "Fire all 3 async get requests (weather, turbinecheck, powerplantcheck) in one call. "
            "After calling this, use poll_results(expected=3) to collect the results."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

POLL_RESULTS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "poll_results",
        "description": (
            "Poll getResult endpoint until expected number of async results are collected. "
            "Returns JSON array of results, each with 'sourceFunction' field."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expected": {
                    "type": "integer",
                    "description": "Number of async results to wait for",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Max seconds to poll (default 30)",
                },
            },
            "required": ["expected"],
        },
    },
}

ANALYZE_DATA_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "analyze_data",
        "description": (
            "Analyze the last polled results (weather, turbinecheck, powerplantcheck) deterministically. "
            "Uses stored poll data and turbine documentation to compute config points. "
            "Returns storm_configs, production_configs, and all_config_points for fire_unlock_codes. "
            "Call this right after poll_results(3). No arguments needed."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

GENERATE_CODES_AND_SUBMIT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_codes_and_submit",
        "description": (
            "Generate unlock codes and submit config in one step. "
            "Uses config points from analyze_data(). Fires all unlockCodeGenerator requests, "
            "polls for codes, matches them, and submits the batch config. No arguments needed. "
            "Call this right after analyze_data()."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

ALL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    CALL_API_SCHEMA,
    FIRE_ASYNC_GETS_SCHEMA,
    POLL_RESULTS_SCHEMA,
    ANALYZE_DATA_SCHEMA,
    GENERATE_CODES_AND_SUBMIT_SCHEMA,
]
