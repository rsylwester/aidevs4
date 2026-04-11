"""Daytona sandbox lifecycle for S04E05 foodwarehouse task.

Spins up a Daytona-managed container with `curl` + `jq` + `$HUB_URL` +
`$AIDEVS_KEY`, then exposes a ``run_bash`` method the LangChain agent can
call as a tool. Unlike S04E04, nothing is uploaded into the sandbox \u2014
all state this task cares about lives behind the Centrala /verify API.

The Daytona OSS bring-up helpers are intentionally duplicated from
``S04E04_filesystem.sandbox`` to keep each task self-contained and to avoid
cross-task imports.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import httpx
from daytona_sdk import (
    CreateSandboxFromImageParams,
    Daytona,
    DaytonaConfig,
)

from settings import settings

if TYPE_CHECKING:
    from types import TracebackType

    from daytona_sdk import Sandbox

logger = logging.getLogger(__name__)

_SANDBOX_IMAGE = "python:3.12-slim"
_MAX_RESULT_BYTES = 8000
_JQ_INSTALL_CMD = "apt-get update -qq && apt-get install -y -qq jq >/dev/null 2>&1 && jq --version"
_DAYTONA_REPO_URL = "https://github.com/daytonaio/daytona"
_DAYTONA_REPO_DIR = Path.home() / ".local" / "share" / "daytona"
_DAYTONA_COMPOSE_REL = Path("docker") / "docker-compose.yaml"
_DAYTONA_OVERRIDE_REL = Path("docker") / "docker-compose.override.yaml"
_DAYTONA_HEALTHCHECK_TIMEOUT_S = 60


class SandboxError(RuntimeError):
    """Raised when the Daytona sandbox cannot be prepared."""


@dataclass
class BashResult:
    """Result of a bash command executed inside the sandbox."""

    exit_code: int
    output: str
    truncated: bool


class FoodwarehouseSandbox:
    """Context manager that owns a single Daytona sandbox with jq pre-installed."""

    def __init__(self, log_file: Path) -> None:
        self._log_file = log_file
        self._daytona: Daytona | None = None
        self._sandbox: Sandbox | None = None

    # ------------------------------------------------------------------ lifecycle

    def __enter__(self) -> Self:
        self.ensure_daytona_running()
        if not settings.daytona_api_key:
            msg = (
                "DAYTONA_API_KEY is empty. Visit http://localhost:13000, login with "
                "dev@daytona.io / password, create a personal API key, add it to .env.sops "
                "(key: DAYTONA_API_KEY), regenerate .env via `just secrets-decrypt`, and re-run."
            )
            raise SandboxError(msg)

        self._daytona = Daytona(DaytonaConfig(api_url=settings.daytona_api_url, api_key=settings.daytona_api_key))
        logger.info("[cyan]Creating Daytona sandbox from image %s...[/]", _SANDBOX_IMAGE)
        self._sandbox = self._daytona.create(
            CreateSandboxFromImageParams(
                image=_SANDBOX_IMAGE,
                env_vars={
                    "AIDEVS_KEY": settings.aidevs_key,
                    "HUB_URL": settings.aidevs_verify_address,
                },
            ),
        )
        self._init_log()
        self._install_jq()
        logger.info("[bold green]Sandbox ready \u2014 jq installed, $HUB_URL and $AIDEVS_KEY exported[/]")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._sandbox is not None:
            try:
                self._sandbox.delete()
                logger.info("[dim]Sandbox deleted[/]")
            except Exception:
                logger.warning("Failed to delete sandbox cleanly", exc_info=True)
        self._sandbox = None
        self._daytona = None

    # -------------------------------------------------------------- daytona infra

    @classmethod
    def ensure_daytona_running(cls) -> None:
        """Probe the Daytona API and attempt to bring it up if unreachable."""
        if cls._daytona_healthy():
            logger.info("[bold green]Daytona healthy at %s[/]", settings.daytona_api_url)
            return

        logger.warning("[yellow]Daytona unreachable at %s, attempting local bring-up...[/]", settings.daytona_api_url)
        cls._clone_daytona_if_missing()
        cls._write_compose_override()
        cls._docker_compose_up()

        deadline = time.monotonic() + _DAYTONA_HEALTHCHECK_TIMEOUT_S
        while time.monotonic() < deadline:
            if cls._daytona_healthy():
                logger.info("[bold green]Daytona came up[/]")
                return
            time.sleep(2)
        msg = (
            f"Daytona did not become healthy at {settings.daytona_api_url} within "
            f"{_DAYTONA_HEALTHCHECK_TIMEOUT_S}s. Check `docker compose logs` under {_DAYTONA_REPO_DIR}."
        )
        raise SandboxError(msg)

    @staticmethod
    def _daytona_healthy() -> bool:
        try:
            resp = httpx.get(f"{settings.daytona_api_url.rstrip('/')}/health", timeout=2)
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    @classmethod
    def _clone_daytona_if_missing(cls) -> None:
        if _DAYTONA_REPO_DIR.exists():
            return
        _DAYTONA_REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
        logger.info("[cyan]Cloning %s to %s...[/]", _DAYTONA_REPO_URL, _DAYTONA_REPO_DIR)
        subprocess.run(
            ["git", "clone", "--depth", "1", _DAYTONA_REPO_URL, str(_DAYTONA_REPO_DIR)],
            check=True,
        )

    @classmethod
    def _write_compose_override(cls) -> None:
        override_path = _DAYTONA_REPO_DIR / _DAYTONA_OVERRIDE_REL
        if override_path.exists():
            return
        compose_path = _DAYTONA_REPO_DIR / _DAYTONA_COMPOSE_REL
        if not compose_path.exists():
            msg = f"Expected Daytona compose file at {compose_path}"
            raise SandboxError(msg)
        dashboard_service = cls._find_dashboard_service(compose_path)
        override_yaml = f'services:\n  {dashboard_service}:\n    ports: !override ["13000:3000"]\n'
        override_path.write_text(override_yaml)
        logger.info("[cyan]Wrote compose override for service %r \u2192 :13000[/]", dashboard_service)

    @staticmethod
    def _find_dashboard_service(compose_path: Path) -> str:
        """Naively locate the compose service that publishes port 3000."""
        text = compose_path.read_text()
        current_service: str | None = None
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if raw_line.startswith("  ") and not raw_line.startswith("    ") and stripped.endswith(":"):
                current_service = stripped[:-1]
            if current_service and ("3000:3000" in stripped or "'3000:3000'" in stripped or '"3000:3000"' in stripped):
                return current_service
        msg = (
            f"Could not locate a service publishing :3000 in {compose_path}. "
            "Create docker-compose.override.yaml manually and re-run."
        )
        raise SandboxError(msg)

    @classmethod
    def _docker_compose_up(cls) -> None:
        compose_path = _DAYTONA_REPO_DIR / _DAYTONA_COMPOSE_REL
        override_path = _DAYTONA_REPO_DIR / _DAYTONA_OVERRIDE_REL
        logger.info("[cyan]Running docker compose up -d...[/]")
        subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(compose_path),
                "-f",
                str(override_path),
                "up",
                "-d",
            ],
            check=True,
            cwd=_DAYTONA_REPO_DIR,
        )

    # ------------------------------------------------------------------ bootstrap

    def _install_jq(self) -> None:
        """Install jq inside the sandbox so the agent can parse JSON responses."""
        logger.info("[cyan]Installing jq in sandbox...[/]")
        result = self.run_bash(_JQ_INSTALL_CMD, timeout=120)
        if result.exit_code != 0:
            msg = f"Failed to install jq in sandbox (exit={result.exit_code}): {result.output[:500]}"
            raise SandboxError(msg)
        logger.info("[green]jq installed: %s[/]", result.output.strip().splitlines()[-1] if result.output else "ok")

    # ------------------------------------------------------------------ run_bash

    def run_bash(self, cmd: str, timeout: int = 60) -> BashResult:
        """Execute a bash command inside the sandbox and return truncated output."""
        sandbox = self._require_sandbox()
        logger.info("[yellow]$ %s[/]", cmd[:300])
        try:
            response: Any = sandbox.process.exec(cmd, timeout=timeout)
        except Exception as exc:
            logger.warning("[red]exec error: %s[/]", exc)
            self.append_log(f"$ {cmd}", f"[exec error] {exc}")
            return BashResult(exit_code=-1, output=f"exec error: {exc}", truncated=False)

        result_text: str = getattr(response, "result", "") or ""
        exit_code: int = int(getattr(response, "exit_code", -1))
        truncated = len(result_text.encode("utf-8")) > _MAX_RESULT_BYTES
        if truncated:
            result_text = result_text.encode("utf-8")[:_MAX_RESULT_BYTES].decode("utf-8", errors="replace")
            result_text += "\n... [output truncated]"

        logger.info("[dim]-> exit=%d bytes=%d[/]", exit_code, len(result_text))
        self.append_log(f"$ {cmd}", f"exit={exit_code}\n{result_text}")
        return BashResult(exit_code=exit_code, output=result_text, truncated=truncated)

    # -------------------------------------------------------------------- logging

    def _init_log(self) -> None:
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        header = f"# S04E05 foodwarehouse session\n\nStarted: {datetime.now(UTC).isoformat()}\n\n"
        self._log_file.write_text(header)

    def append_log(self, heading: str, body: str) -> None:
        """Append a heading + body block to the session markdown log."""
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        with self._log_file.open("a") as f:
            f.write(f"## {ts} \u2014 {heading}\n\n```\n{body}\n```\n\n")

    # ---------------------------------------------------------------------- util

    def _require_sandbox(self) -> Sandbox:
        if self._sandbox is None:
            msg = "FoodwarehouseSandbox used outside of its `with` block"
            raise SandboxError(msg)
        return self._sandbox


def docker_available() -> bool:
    """Return True if the docker CLI is on PATH \u2014 used for a nicer error if not."""
    return shutil.which("docker") is not None
