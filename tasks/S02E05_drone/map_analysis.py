"""Identify dam coordinates on the drone mission map using vision LLM + OpenCV grid detection."""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

if TYPE_CHECKING:
    from pathlib import Path

    from tasks.S02E05_drone.tracking import TokenTracker

logger = logging.getLogger(__name__)

_COORD_RE = re.compile(r"(\d+)\s*[,;x]\s*(\d+)")


@dataclass
class MapAnalysis:
    """Result of map analysis: dam position and grid bounds."""

    dam_x: int
    dam_y: int
    max_x: int
    max_y: int


def _detect_grid_size(image_path: Path) -> tuple[int, int]:
    """Detect grid dimensions by counting red lines using OpenCV.

    Returns (columns, rows) -- e.g. (4, 3) for a 4x3 grid.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        msg = f"Could not load image: {image_path}"
        raise FileNotFoundError(msg)

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, w = img.shape[:2]

    # Red in HSV wraps around 0/180 — detect both ranges
    mask_lo = cv2.inRange(hsv, np.array([0, 100, 100]), np.array([10, 255, 255]))
    mask_hi = cv2.inRange(hsv, np.array([170, 100, 100]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(mask_lo, mask_hi)

    # Find vertical lines: project red pixels onto x-axis
    x_proj = np.sum(red_mask > 0, axis=0).astype(np.float64)
    # A vertical red line spans most of the image height
    threshold = h * 0.4
    vertical_positions = _find_line_positions(x_proj, threshold, min_gap=w * 0.05)

    # Find horizontal lines: project red pixels onto y-axis
    y_proj = np.sum(red_mask > 0, axis=1).astype(np.float64)
    threshold_h = w * 0.4
    horizontal_positions = _find_line_positions(y_proj, threshold_h, min_gap=h * 0.05)

    # Filter out edge lines (border lines within 5% of edges)
    edge_margin_x = w * 0.05
    interior_vertical = [p for p in vertical_positions if edge_margin_x < p < w - edge_margin_x]
    edge_margin_y = h * 0.05
    interior_horizontal = [p for p in horizontal_positions if edge_margin_y < p < h - edge_margin_y]

    cols = len(interior_vertical) + 1
    rows = len(interior_horizontal) + 1

    logger.info(
        "[cyan]Grid detection:[/] %d vertical lines → %d cols, %d horizontal lines → %d rows",
        len(interior_vertical),
        cols,
        len(interior_horizontal),
        rows,
    )
    return cols, rows


def _find_line_positions(
    projection: np.ndarray[Any, np.dtype[np.float64]], threshold: float, min_gap: float
) -> list[int]:
    """Find positions where projection exceeds threshold, merging nearby peaks."""
    above = np.where(projection > threshold)[0]
    if len(above) == 0:
        return []

    positions: list[int] = []
    group_start = int(above[0])
    group_end = int(above[0])

    for idx in above[1:]:
        if idx - group_end <= 2:
            group_end = int(idx)
        else:
            positions.append((group_start + group_end) // 2)
            group_start = int(idx)
            group_end = int(idx)
    positions.append((group_start + group_end) // 2)

    # Merge positions that are too close
    merged: list[int] = [positions[0]]
    for pos in positions[1:]:
        if pos - merged[-1] >= min_gap:
            merged.append(pos)
    return merged


def _identify_dam_vision(resources_dir: Path, max_x: int, max_y: int, tracker: TokenTracker) -> tuple[int, int]:
    """Use Gemini Flash vision to identify the dam's grid sector."""
    from tasks.S02E05_drone.llm import chat

    map_path = resources_dir / "drone.png"
    img_b64 = base64.b64encode(map_path.read_bytes()).decode("ascii")

    prompt = f"""\
You are analyzing an aerial grid map of the Żarnowiec nuclear power plant area in Poland.

GRID LAYOUT:
- Red lines divide the image into a {max_x}x{max_y} grid
- Coordinates are 1-indexed: (1,1) is the TOP-LEFT sector
- X = column number (1-{max_x}, left to right)
- Y = row number (1-{max_y}, top to bottom)

YOUR TASK:
Find the DAM (zapora/tama). The dam is indicated by an area with INTENSIFIED blue/dark \
water color — it stands out visually from the rest of the map. Look for a concentrated \
area of deep blue/dark water that appears more vivid than other water features.

Respond with ONLY the coordinates in format: x,y"""

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    response = chat(model="openrouter/google/gemini-2.5-flash", messages=messages, label="map-vision")
    tracker.track(response, label="map-vision")

    raw: str = (response.content or "").strip()
    logger.info("Vision model raw response: %s", raw)

    match = _COORD_RE.search(raw)
    if not match:
        msg = f"Could not parse coordinates from vision response: {raw}"
        raise ValueError(msg)

    return int(match.group(1)), int(match.group(2))


def identify_dam_coordinates(resources_dir: Path, tracker: TokenTracker) -> MapAnalysis:
    """Detect grid size via OpenCV, then identify dam via vision LLM."""
    map_path = resources_dir / "drone.png"

    max_x, max_y = _detect_grid_size(map_path)
    dam_x, dam_y = _identify_dam_vision(resources_dir, max_x, max_y, tracker)

    # Clamp dam coords to detected grid bounds
    dam_x = max(1, min(dam_x, max_x))
    dam_y = max(1, min(dam_y, max_y))

    logger.info("[bold cyan]Dam at (%d, %d), grid %dx%d[/]", dam_x, dam_y, max_x, max_y)
    return MapAnalysis(dam_x=dam_x, dam_y=dam_y, max_x=max_x, max_y=max_y)
