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
from pydantic import BaseModel

from lib.hub import fetch_data, submit_answer
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


# -- Main --------------------------------------------------------------------


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)

    # 1. Load suspects from S01E01 data
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

    # 2. Fetch power plant data
    logger.info("[bold cyan]Fetching power plant locations...[/]")
    raw_plants = fetch_data("findhim_locations.json")
    (ARTIFACTS / "findhim_locations.json").write_text(raw_plants, encoding="utf-8")

    plants = _parse_plants(raw_plants)
    active_plants = [p for p in plants if p.active]
    logger.info("[green]Active power plants: %d[/]", len(active_plants))

    # 3. Geocode plant cities
    city_names = [p.city for p in active_plants]
    logger.info("[bold cyan]Geocoding %d cities...[/]", len(city_names))
    coords = _geocode_cities(city_names)
    for city, (lat, lon) in coords.items():
        logger.info("  %s: %.4f, %.4f", city, lat, lon)
    (ARTIFACTS / "plant_coords.json").write_text(
        json.dumps({c: {"lat": la, "lon": lo} for c, (la, lo) in coords.items()}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 4. Query each suspect's locations and find closest to any plant
    all_suspect_locations: dict[str, list[dict[str, float]]] = {}
    best_distance = float("inf")
    best_suspect: dict[str, str] | None = None
    best_plant: PowerPlant | None = None

    for suspect in suspects:
        name = suspect[COL_NAME]
        surname = suspect[COL_SURNAME]
        locations = _get_suspect_locations(name, surname)
        all_suspect_locations[f"{name} {surname}"] = [{"lat": pt.lat, "lon": pt.lon} for pt in locations]
        logger.info("[cyan]%s %s: %d locations[/]", name, surname, len(locations))

        for loc in locations:
            for plant in active_plants:
                plant_coord = coords.get(plant.city)
                if not plant_coord:
                    continue
                dist = _haversine(loc.lat, loc.lon, plant_coord[0], plant_coord[1])
                if dist < best_distance:
                    best_distance = dist
                    best_suspect = suspect
                    best_plant = plant
                    logger.info(
                        "  [yellow]New best: %.1f km from %s (%s)[/]",
                        dist,
                        plant.city,
                        plant.code,
                    )

    (ARTIFACTS / "suspect_locations.json").write_text(
        json.dumps(all_suspect_locations, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if best_suspect is None or best_plant is None:
        logger.error("[bold red]No suspect found near any power plant![/]")
        return

    name = best_suspect[COL_NAME]
    surname = best_suspect[COL_SURNAME]
    birth_year = int(best_suspect[COL_BIRTH_DATE][:4])
    logger.info(
        "[bold green]Closest suspect: %s %s — %.1f km from %s (%s)[/]",
        name,
        surname,
        best_distance,
        best_plant.city,
        best_plant.code,
    )

    # 5. Get access level
    access_level = _get_access_level(name, surname, birth_year)
    logger.info("[bold magenta]Access level: %s[/]", access_level)

    # 6. Submit answer
    answer = {
        "name": name,
        "surname": surname,
        "accessLevel": access_level,
        "powerPlant": best_plant.code,
    }
    logger.info("[bold cyan]Submitting: %s[/]", answer)
    submit_answer("findhim", answer)


if __name__ == "__main__":
    run()
