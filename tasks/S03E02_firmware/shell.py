"""Shell API client for the restricted Linux VM."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from settings import settings

logger = logging.getLogger(__name__)

SHELL_API_URL = "***REMOVED***/api/shell"
WORKSPACE = Path(__file__).parent / ".workspace"

_FORBIDDEN_PREFIXES = ("/etc", "/root", "/proc")
_BINARY_EXTENSIONS = (".bin", ".so", ".o", ".exe", ".dat", ".gz", ".tar", ".zip", ".png", ".jpg", ".gif")
_MIN_INTERVAL = 2.0  # seconds between API calls


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient errors that should be retried."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {503, 429}


def _extract_http_error(exc: BaseException) -> httpx.HTTPStatusError | None:
    """Unwrap an exception chain to find an HTTPStatusError (e.g. inside RetryError)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc
    # tenacity.RetryError stores the last attempt
    if hasattr(exc, "last_attempt"):
        inner = exc.last_attempt.exception()  # type: ignore[union-attr]
        if isinstance(inner, httpx.HTTPStatusError):
            return inner
    # Walk __cause__ chain
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, httpx.HTTPStatusError):
            return cause
        cause = cause.__cause__
    return None


class ShellClient:
    """Encapsulates all HTTP communication with the shell API."""

    def __init__(self) -> None:
        self._api_key: str = settings.aidevs_key
        self._http = httpx.Client(timeout=30)
        self._allowed_commands: set[str] = set()
        self._forbidden_paths: set[str] = set()
        self._last_call: float = 0.0

    def _throttle(self) -> None:
        """Enforce minimum interval between API calls."""
        elapsed = time.monotonic() - self._last_call
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=3, min=3, max=30),
        before_sleep=lambda rs: logger.warning(
            "[SHELL] Attempt %d failed — retrying...",
            rs.attempt_number,
        ),
    )
    def _post_raw(self, command: str) -> httpx.Response:
        """POST a command to the shell API with retry logic. Returns raw response."""
        self._throttle()
        resp = self._http.post(
            SHELL_API_URL,
            json={"apikey": self._api_key, "cmd": command},
            timeout=30,
        )
        self._last_call = time.monotonic()
        resp.raise_for_status()
        return resp

    def _post(self, command: str) -> str:
        """Execute a command and return the response body as string. Errors returned as text."""
        t0 = time.monotonic()
        try:
            resp = self._post_raw(command)
        except Exception as exc:
            elapsed = time.monotonic() - t0
            # Unwrap to find the HTTPStatusError (tenacity wraps in RetryError)
            http_err = _extract_http_error(exc)
            if http_err:
                body = http_err.response.text
                status = http_err.response.status_code
                logger.warning("[SHELL] CMD=%r | HTTP=%d | %.3fs | %s", command, status, elapsed, body[:300])
            else:
                body = f'{{"error": "{exc}"}}'
                logger.warning("[SHELL] CMD=%r | FAILED | %.3fs | %s", command, elapsed, body[:300])
            return body

        body = resp.text
        elapsed = time.monotonic() - t0
        logger.info(
            "[SHELL] CMD=%r | HTTP=%d | %.3fs | %s",
            command,
            resp.status_code,
            elapsed,
            body[:300],
        )
        return body

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Try to parse JSON response, return raw string in 'message' if not JSON."""
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            data = {"message": raw}
        return data

    def scan_gitignore(self, directory: str) -> list[str]:
        """Read .gitignore in a directory, register forbidden paths, save to CSV. Returns forbidden paths."""
        raw = self._post(f"cat {directory}/.gitignore")
        parsed = self._parse_response(raw)
        gi_data: str = parsed.get("data", raw) if isinstance(parsed.get("data"), str) else raw

        new_paths: list[str] = []
        dir_clean = directory.rstrip("/")
        for line in gi_data.splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            full_path = f"{dir_clean}/{entry}"
            self._forbidden_paths.add(full_path)
            new_paths.append(full_path)

        # Save/update the CSV
        csv_path = WORKSPACE / "forbidden_paths.csv"
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(
            "path\n" + "\n".join(sorted(self._forbidden_paths)) + "\n",
            encoding="utf-8",
        )
        logger.info("[AGENT] Forbidden paths from %s/.gitignore: %s", directory, new_paths)
        return new_paths

    def execute(self, cmd: str) -> str:
        """Execute a command on the VM with safety checks."""
        # Block system-level forbidden paths
        for token in cmd.split():
            for prefix in _FORBIDDEN_PREFIXES:
                if token.startswith(prefix) or f"'{prefix}" in token or f'"{prefix}' in token:
                    hint = f"BLOCKED: Path '{prefix}' is forbidden. Avoid /etc, /root, /proc."
                    logger.warning("[SHELL] %s (cmd=%r)", hint, cmd)
                    return hint

        # Block .gitignore-derived forbidden paths
        for token in cmd.split():
            for forbidden in self._forbidden_paths:
                if token.startswith(forbidden) or token.rstrip("/") == forbidden.rstrip("/"):
                    hint = f"BLOCKED: Path '{forbidden}' is listed in .gitignore. Do NOT access it."
                    logger.warning("[SHELL] %s (cmd=%r)", hint, cmd)
                    return hint

        # Block reading binary files
        first_token = cmd.split()[0] if cmd.strip() else ""
        if first_token == "cat":
            for token in cmd.split()[1:]:
                if any(token.endswith(ext) for ext in _BINARY_EXTENSIONS):
                    hint = f"BLOCKED: '{token}' is a binary file. Use 'ls' to inspect, not 'cat'."
                    logger.warning("[SHELL] %s (cmd=%r)", hint, cmd)
                    return hint

        # Validate command against allowed list (if populated)
        # Allow absolute paths (e.g. /opt/firmware/cooler/cooler.bin) — the shell supports running binaries
        if self._allowed_commands and first_token not in self._allowed_commands and not first_token.startswith("/"):
            available = ", ".join(sorted(self._allowed_commands))
            hint = f"BLOCKED: Unknown command '{first_token}'. Available commands: {available}"
            logger.warning("[SHELL] %s", hint)
            return hint

        output = self._post(cmd)

        # Truncate huge responses (e.g. binary files) to avoid context blowup
        if len(output) > 4000:
            output = (
                output[:4000] + f"\n\n... [TRUNCATED — response was {len(output)} chars. This is likely a binary file.]"
            )

        return output

    def help(self) -> str:
        """Fetch help output, parse commands, save to workspace."""
        output = self._post("help")
        WORKSPACE.mkdir(parents=True, exist_ok=True)

        # Parse JSON response to extract command names from data array
        parsed = self._parse_response(output)
        data_list: list[str] = parsed.get("data", [])

        commands: set[str] = set()
        for entry in data_list:
            # Each entry like "ls  - list files and directories."
            m = re.match(r"^\s*(\w[\w.-]*)", entry)
            if m:
                commands.add(m.group(1))

        self._allowed_commands = commands
        commands_text = "\n".join(sorted(commands))
        help_text = "\n".join(data_list) if data_list else output
        (WORKSPACE / "shell.md").write_text(
            f"# Available Shell Commands\n\n{help_text}\n\n## Parsed commands\n\n{commands_text}\n",
            encoding="utf-8",
        )
        logger.info("[AGENT] Parsed %d commands from help: %s", len(commands), sorted(commands))
        return output

    def reboot(self) -> str:
        """Reboot the VM to clean state."""
        logger.info("[AGENT] Rebooting VM...")
        return self._post("reboot")

    @property
    def allowed_commands(self) -> set[str]:
        """Return the set of allowed commands (populated after help())."""
        return self._allowed_commands
