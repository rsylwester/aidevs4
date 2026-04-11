"""Tool schemas and Plan validation for the S04E04 filesystem agent.

The agent sees two tools:

- ``run_bash(cmd)`` — execute a command inside the Daytona sandbox where the
  notes are mounted read-only at ``/notes``.
- ``finalize(cities, people, goods)`` — submit the final filesystem plan.

When ``finalize`` is called we parse its arguments into :class:`Plan`, which
runs cross-reference integrity checks (every person's city must be known,
every good's supplying city must be known) and rejects filenames that would
carry Polish diacritics after ASCII normalization.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator
from unidecode import unidecode

_ASCII_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def ascii_slug(name: str) -> str:
    """Normalize a Polish noun to an ASCII filename slug.

    Examples:
        ``"Kraków"`` → ``"krakow"``
        ``"Jan Kowalski"`` → ``"jan_kowalski"``
        ``"Świeża koparka"`` → ``"swieza_koparka"``
    """
    slug = unidecode(name).strip().lower()
    slug = re.sub(r"\s+", "_", slug)
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    if not slug or not _ASCII_SLUG_RE.match(slug):
        msg = f"Invalid slug produced from {name!r}: {slug!r}"
        raise ValueError(msg)
    return slug


class Person(BaseModel):
    """A merchant mentioned in Natan's notes."""

    name: str = Field(..., description="Full name in nominative, e.g. 'Jan Kowalski'")
    city: str = Field(..., description="City this person manages, nominative, matching a key in cities")


class Plan(BaseModel):
    """Validated final plan submitted by the agent via the finalize tool."""

    cities: dict[str, dict[str, int]] = Field(
        ...,
        description="city_nominative -> {good_nom_sing: quantity_int}",
    )
    people: list[Person] = Field(..., description="All merchants, each linked to exactly one city")
    goods: dict[str, list[str]] = Field(
        ...,
        description="good_nom_sing -> list of city_nominative that currently offer it for sale",
    )

    @model_validator(mode="after")
    def _cross_reference(self) -> Plan:
        if not self.cities:
            msg = "cities must not be empty"
            raise ValueError(msg)
        if not self.people:
            msg = "people must not be empty"
            raise ValueError(msg)
        if not self.goods:
            msg = "goods must not be empty"
            raise ValueError(msg)

        known = set(self.cities.keys())
        for person in self.people:
            if person.city not in known:
                msg = f"Person {person.name!r} references unknown city {person.city!r}"
                raise ValueError(msg)
        for good, seller_cities in self.goods.items():
            if not seller_cities:
                msg = f"Good {good!r} has no selling cities — list must be non-empty"
                raise ValueError(msg)
            if len(set(seller_cities)) != len(seller_cities):
                msg = f"Good {good!r} has duplicate selling cities: {seller_cities}"
                raise ValueError(msg)
            for city in seller_cities:
                if city not in known:
                    msg = f"Good {good!r} references unknown selling city {city!r}"
                    raise ValueError(msg)

        # Validate all slugs roundtrip successfully.
        for city in self.cities:
            ascii_slug(city)
        for person in self.people:
            ascii_slug(person.name)
        for good in self.goods:
            ascii_slug(good)

        return self


RUN_BASH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_bash",
        "description": (
            "Execute a bash command inside the sandbox. Natan's notes are uploaded read-only "
            "to /notes (which is also the working directory). Use ls, cat, grep, find, head, "
            "awk, wc, sort etc. You can also curl the hub preview page "
            "(https://hub.ag3nts.org/filesystem_preview.html) if you want to inspect the "
            "current virtual filesystem state. Output is truncated at 8KB — prefer targeted "
            "commands over dumping whole files repeatedly."
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


FINALIZE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finalize",
        "description": (
            "Submit the final filesystem plan. Call this when you are confident every "
            "city, person, and good has been identified and cross-referenced. Centrala "
            "validates the plan and returns either success or a specific error message — "
            "iterate based on the error if it fails. "
            "All names MUST be ASCII-only (no Polish diacritics — strip ą/ć/ę/ł/ń/ó/ś/ź/ż). "
            "Goods MUST be in nominative SINGULAR (koparka, NOT koparki; cement, NOT cementu). "
            "Cities MUST be in nominative (Krakow, NOT Krakowie). People MUST be in nominative "
            "(Jan Kowalski). Every person.city must appear in cities. Every city listed in "
            "goods[*] must appear in cities. A single good can be offered by MULTIPLE cities — "
            "pass ALL selling cities as the list, not just one."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cities": {
                    "type": "object",
                    "description": (
                        "Mapping of city name (nominative) to a dict of goods it needs "
                        "(nominative singular) and integer quantities."
                    ),
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": {"type": "integer"},
                    },
                },
                "people": {
                    "type": "array",
                    "description": "Merchants responsible for trade in a specific city.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Full name, nominative."},
                            "city": {"type": "string", "description": "City name, must be a key in cities."},
                        },
                        "required": ["name", "city"],
                    },
                },
                "goods": {
                    "type": "object",
                    "description": (
                        "Mapping of good name (nominative singular) to a LIST of cities "
                        "that currently offer it for sale. If a good is sold by exactly one "
                        "city, pass a single-element list. If multiple cities sell it, list "
                        "them all — the host will write markdown links to every one of them "
                        "inside the /towary/<good> file."
                    ),
                    "additionalProperties": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
            },
            "required": ["cities", "people", "goods"],
        },
    },
}


VIEW_HUB_TREE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "view_hub_tree",
        "description": (
            "Inspect the CURRENT state of the Centrala virtual filesystem (what you have "
            "uploaded so far, if anything). Returns a recursive tree of directories and "
            "files with names, sizes, and creation timestamps. The hub does NOT expose file "
            "contents, so you will only see filenames — not what's inside. Useful to "
            "verify after a failed finalize that your cities/people/goods files landed "
            "with the exact names you intended, and that none are missing."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


ALL_TOOL_SCHEMAS: list[dict[str, Any]] = [RUN_BASH_SCHEMA, VIEW_HUB_TREE_SCHEMA, FINALIZE_SCHEMA]
