"""S01E02 - findhim: find which transport suspect is nearest a nuclear power plant."""

from __future__ import annotations

import csv
import io
import json
import logging
import math
from pathlib import Path
from typing import Any, cast

import httpx
from geopy.geocoders import (  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]
    Nominatim,  # pyright: ignore[reportUnknownVariableType]
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool  # pyright: ignore[reportUnknownVariableType]
from pydantic import BaseModel

from lib.hub import fetch_data, submit_answer
from lib.llm import get_llm
from lib.logging import setup_logging
from settings import settings
from tasks.S01E01_people.constants import (
    COL_BIRTH_DATE,
    COL_BIRTH_PLACE,
    COL_GENDER,
    COL_JOB,
    COL_NAME,
    COL_SURNAME,
    DATA_FILE,
    FILTER_CITY,
    FILTER_GENDER,
    FILTER_YEAR_MAX,
    FILTER_YEAR_MIN,
    TARGET_TAG,
)
from tasks.S01E01_people.tagging import tag_jobs

logger = logging.getLogger(__name__)

ARTIFACTS = Path(__file__).parent / ".artifacts"

HUB_BASE = "https://***REDACTED***/api"


# -- Models ------------------------------------------------------------------


class PowerPlant(BaseModel):
    """Parsed power plant entry."""

    city: str
    code: str
    active: bool
    power_mw: int


class SuspectLocation(BaseModel):
    """A single location point returned by the hub API."""

    lat: float
    lon: float


# -- Helpers ------------------------------------------------------------------


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in km between two lat/lon points."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_csv(raw: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(raw)))


def _filter_people(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for row in rows:
        gender = row.get(COL_GENDER, "").strip().upper()
        birth_place = row.get(COL_BIRTH_PLACE, "").strip()
        birth_date = row.get(COL_BIRTH_DATE, "").strip()
        if not birth_date:
            continue
        year = int(birth_date[:4])
        if gender == FILTER_GENDER and birth_place == FILTER_CITY and FILTER_YEAR_MIN <= year <= FILTER_YEAR_MAX:
            filtered.append(row)
    return filtered


def _get_transport_suspects(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    """Tag jobs and return only transport workers."""
    jobs: list[tuple[int, str]] = []
    for i, row in enumerate(candidates):
        job = row.get(COL_JOB, "").strip()
        if job:
            jobs.append((i, job))

    tagged = tag_jobs(jobs)
    tag_map: dict[int, list[str]] = {t.index: t.tags for t in tagged}

    suspects: list[dict[str, str]] = []
    for i, row in enumerate(candidates):
        tags = tag_map.get(i, [])
        if any(TARGET_TAG in t.lower() for t in tags):
            suspects.append(row)
    return suspects


def _parse_plants(raw_json: str) -> list[PowerPlant]:
    data: dict[str, Any] = json.loads(raw_json)
    plants_dict: dict[str, dict[str, Any]] = cast("dict[str, dict[str, Any]]", data.get("power_plants", data))
    return [
        PowerPlant(
            city=city,
            code=str(info.get("code", "")),
            active=bool(info.get("is_active", False)),
            power_mw=int(str(info.get("power", "0 MW")).split()[0]),
        )
        for city, info in plants_dict.items()
    ]


def _geocode_cities(city_names: list[str]) -> dict[str, tuple[float, float]]:
    """Use Nominatim to get lat/lon for Polish city names."""
    geolocator = Nominatim(user_agent="aidevs4-findhim")  # pyright: ignore[reportUnknownVariableType]
    coords: dict[str, tuple[float, float]] = {}
    for city in city_names:
        location = geolocator.geocode(f"{city}, Poland")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if location is not None:
            coords[city] = (float(location.latitude), float(location.longitude))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportAttributeAccessIssue]
        else:
            logger.warning("[yellow]Could not geocode: %s[/]", city)
    return coords


def _get_suspect_locations(name: str, surname: str) -> list[SuspectLocation]:
    """Query hub API for a suspect's known locations."""
    resp = httpx.post(
        f"{HUB_BASE}/location",
        json={"apikey": settings.aidevs_key, "name": name, "surname": surname},
        timeout=30,
    )
    resp.raise_for_status()
    data: Any = resp.json()
    logger.info("[dim]Location response for %s %s: %s[/]", name, surname, data)

    # API may return a list directly or a dict with a nested list
    if isinstance(data, list):
        raw_locations: list[dict[str, Any]] = cast("list[dict[str, Any]]", data)
    else:
        raw_locations: list[dict[str, Any]] = cast(  # type: ignore[no-redef]
            "list[dict[str, Any]]", data.get("locations", data.get("data", []))
        )
    return [
        SuspectLocation(
            lat=float(str(loc.get("lat", loc.get("latitude", 0)))),
            lon=float(str(loc.get("lon", loc.get("longitude", 0)))),
        )
        for loc in raw_locations
        if ("lat" in loc or "latitude" in loc) and ("lon" in loc or "longitude" in loc)
    ]


def _get_access_level(name: str, surname: str, birth_year: int) -> str:
    """Query hub API for a suspect's access level."""
    resp = httpx.post(
        f"{HUB_BASE}/accesslevel",
        json={"apikey": settings.aidevs_key, "name": name, "surname": surname, "birthYear": birth_year},
        timeout=30,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    logger.info("[dim]Access level response for %s %s: %s[/]", name, surname, data)
    return str(data.get("accessLevel", data.get("access_level", data.get("data", ""))))


# -- Agent tools --------------------------------------------------------------


@tool
def load_transport_suspects() -> str:
    """Load people CSV, filter candidates, tag jobs, return transport suspects as JSON."""
    s01e01_csv = Path(__file__).parent.parent / "S01E01_people" / ".artifacts" / DATA_FILE
    if s01e01_csv.exists():
        raw_csv = s01e01_csv.read_text(encoding="utf-8")
        logger.info("[dim]Loaded CSV from S01E01 artifacts[/]")
    else:
        logger.info("[bold cyan]Fetching %s from hub...[/]", DATA_FILE)
        raw_csv = fetch_data(DATA_FILE)

    rows = _parse_csv(raw_csv)
    candidates = _filter_people(rows)
    logger.info("[yellow]Filtered candidates: %d[/]", len(candidates))

    suspects = _get_transport_suspects(candidates)
    logger.info("[bold green]Transport suspects: %d[/]", len(suspects))
    for s in suspects:
        logger.info("  %s %s (born %s)", s[COL_NAME], s[COL_SURNAME], s[COL_BIRTH_DATE][:4])

    return json.dumps(suspects, ensure_ascii=False)


@tool
def get_power_plants() -> str:
    """Fetch power plant data from hub, geocode active plants, return with coordinates."""
    logger.info("[bold cyan]Fetching power plant locations...[/]")
    raw_plants = fetch_data("findhim_locations.json")
    (ARTIFACTS / "findhim_locations.json").write_text(raw_plants, encoding="utf-8")

    plants = _parse_plants(raw_plants)
    active_plants = [p for p in plants if p.active]
    logger.info("[green]Active power plants: %d[/]", len(active_plants))

    city_names = [p.city for p in active_plants]
    logger.info("[bold cyan]Geocoding %d cities...[/]", len(city_names))
    coords = _geocode_cities(city_names)
    for city, (lat, lon) in coords.items():
        logger.info("  %s: %.4f, %.4f", city, lat, lon)
    (ARTIFACTS / "plant_coords.json").write_text(
        json.dumps({c: {"lat": la, "lon": lo} for c, (la, lo) in coords.items()}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    result: list[dict[str, Any]] = []
    for plant in active_plants:
        entry: dict[str, Any] = {"city": plant.city, "code": plant.code, "power_mw": plant.power_mw}
        if plant.city in coords:
            entry["lat"] = coords[plant.city][0]
            entry["lon"] = coords[plant.city][1]
        result.append(entry)

    return json.dumps(result, ensure_ascii=False)


@tool
def find_nearest_suspect(suspects_json: str, plants_json: str) -> str:
    """Find which suspect is nearest to any active nuclear power plant.

    Takes the JSON output of load_transport_suspects and get_power_plants.
    Internally fetches each suspect's locations and computes all haversine distances.
    Returns the single closest suspect-plant pair with distance.
    """
    suspects: list[dict[str, str]] = json.loads(suspects_json)
    plants: list[dict[str, Any]] = json.loads(plants_json)

    best: dict[str, Any] | None = None
    best_dist = float("inf")
    all_locations: dict[str, list[dict[str, float]]] = {}

    for suspect in suspects:
        name = suspect[COL_NAME]
        surname = suspect[COL_SURNAME]
        locations = _get_suspect_locations(name, surname)
        all_locations[f"{name} {surname}"] = [{"lat": loc.lat, "lon": loc.lon} for loc in locations]
        logger.info("[cyan]%s %s: %d locations[/]", name, surname, len(locations))

        for loc in locations:
            for plant in plants:
                if "lat" not in plant or "lon" not in plant:
                    continue
                dist = _haversine(loc.lat, loc.lon, float(plant["lat"]), float(plant["lon"]))
                logger.info(
                    "[yellow]Distance: %s %s → %s = %.1f km[/]",
                    name,
                    surname,
                    plant["city"],
                    dist,
                )
                if dist < best_dist:
                    best_dist = dist
                    best = {
                        "name": name,
                        "surname": surname,
                        "birthDate": suspect.get(COL_BIRTH_DATE, ""),
                        "plant_city": plant["city"],
                        "plant_code": plant["code"],
                        "distance_km": round(dist, 2),
                    }

    # Save all suspect locations as artifact
    (ARTIFACTS / "suspect_locations.json").write_text(
        json.dumps(all_locations, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if best is None:
        return json.dumps({"error": "No valid suspect-plant pair found"})

    logger.info(
        "[bold green]Nearest: %s %s → %s (%.1f km)[/]",
        best["name"],
        best["surname"],
        best["plant_city"],
        best["distance_km"],
    )
    return json.dumps(best, ensure_ascii=False)


@tool
def get_access_level(name: str, surname: str, birth_year: int) -> str:
    """Query hub API for a suspect's access level. Requires name, surname, and birth year."""
    level = _get_access_level(name, surname, birth_year)
    return json.dumps({"access_level": level})


@tool
def submit_final_answer(name: str, surname: str, access_level: str, power_plant_code: str) -> str:
    """Submit the final answer to the hub once you've identified the closest suspect."""
    answer = {
        "name": name,
        "surname": surname,
        "accessLevel": access_level,
        "powerPlant": power_plant_code,
    }
    logger.info("[bold cyan]Submitting: %s[/]", answer)
    try:
        result = submit_answer("findhim", answer)
        return json.dumps(result, ensure_ascii=False, default=str)
    except httpx.HTTPStatusError as exc:
        error_body: Any = exc.response.json()  # pyright: ignore[reportUnknownMemberType]
        logger.exception("[bold red]Submission failed: %s[/]", error_body)
        return json.dumps({"error": True, "details": error_body}, ensure_ascii=False, default=str)


# -- Agent system prompt ------------------------------------------------------

AGENT_SYSTEM_PROMPT = """\
You are an investigator agent. Your task: find which transport suspect is nearest \
an active nuclear power plant, determine their access level, and submit the answer.

Steps:
1. Call load_transport_suspects to get the list of suspects.
2. Call get_power_plants to get active nuclear power plants with coordinates.
3. Call find_nearest_suspect with both JSON outputs — it fetches all suspect \
   locations and computes all distances internally, returning the single closest pair.
4. Call get_access_level with the closest suspect's name, surname, and birth year \
   (extract year from birthDate field, first 4 chars).
5. Call submit_final_answer with the suspect's name, surname, access level, and \
   the power plant code.

Important:
- The birthDate format is YYYY-MM-DD — extract the year as an integer.
"""


# -- Main --------------------------------------------------------------------


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)

    llm = get_llm("openai/gpt-4o-mini")
    agent_tools: list[Any] = [
        load_transport_suspects,
        get_power_plants,
        find_nearest_suspect,
        get_access_level,
        submit_final_answer,
    ]
    llm_with_tools = llm.bind_tools(agent_tools)  # pyright: ignore[reportUnknownMemberType]
    tool_map: dict[str, Any] = {t.name: t for t in agent_tools}  # pyright: ignore[reportUnknownMemberType]

    messages: list[Any] = [
        SystemMessage(content=AGENT_SYSTEM_PROMPT),
        HumanMessage(
            content="Find which transport suspect is nearest an active nuclear power plant, "
            "get their access level, and submit the answer."
        ),
    ]

    max_iterations = 10
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
