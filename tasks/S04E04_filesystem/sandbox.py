"""Daytona sandbox lifecycle for S04E04 filesystem task.

Spins up a Daytona-managed container, uploads the extracted notes read-only,
and exposes a ``run_bash`` method the LangChain agent can call as a tool.

Daytona OSS self-hosted bring-up
--------------------------------
- Expects Daytona's docker-compose stack to be running at ``settings.daytona_api_url``
  (default ``http://localhost:13000/api``) to avoid Langfuse's :3000 port.
- If unreachable, :meth:`NotesSandbox.ensure_daytona_running` clones
  ``daytonaio/daytona`` into ``~/.local/share/daytona`` (once), writes a
  compose override that remaps the dashboard to :13000, and runs
  ``docker compose up -d``. After the stack is healthy the user must visit the
  dashboard once to create an API key and store it in ``.env.sops``.
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
    FileUpload,
)

from settings import settings

if TYPE_CHECKING:
    from types import TracebackType

    from daytona_sdk import Sandbox

logger = logging.getLogger(__name__)

_SANDBOX_IMAGE = "python:3.12-slim"
_NOTES_MOUNT = "/notes"
_MAX_RESULT_BYTES = 8000
# Extra apt packages installed into the sandbox at startup so the agent has a
# useful shell (the base slim image ships almost nothing beyond Python + coreutils).
_SANDBOX_APT_PACKAGES = ("curl", "ca-certificates", "jq", "ripgrep", "file", "less")
_TOOL_INSTALL_TIMEOUT_S = 180
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


class NotesSandbox:
    """Context manager that owns a single Daytona sandbox with the notes uploaded."""

    def __init__(self, notes_dir: Path, log_file: Path) -> None:
        self._notes_dir = notes_dir
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
                env_vars={"AIDEVS_KEY": settings.aidevs_key},
            ),
        )
        self._init_log()
        self._install_tools()
        self._prepare_notes_dir()
        self._upload_notes()
        logger.info("[bold green]Sandbox ready — notes uploaded to %s[/]", _NOTES_MOUNT)
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
        logger.info("[cyan]Wrote compose override for service %r → :13000[/]", dashboard_service)

    @staticmethod
    def _find_dashboard_service(compose_path: Path) -> str:
        """Naively locate the compose service that publishes port 3000.

        Kept dependency-free (no PyYAML) because the compose schema is stable
        enough for a line-wise scan. If Daytona upstream changes indentation,
        this will raise and prompt the user to fix the override manually.
        """
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

    # ------------------------------------------------------------- tool install

    def _install_tools(self) -> None:
        """Install a small set of useful CLI tools into the sandbox.

        Base image is ``python:3.12-slim`` which has almost nothing beyond
        Python and coreutils. We install curl/jq/ripgrep/etc so the agent's
        bash shell is actually useful.
        """
        sandbox = self._require_sandbox()
        packages = " ".join(_SANDBOX_APT_PACKAGES)
        cmd = (
            "set -e; export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update -qq && "
            f"apt-get install -y --no-install-recommends -qq {packages} && "
            "rm -rf /var/lib/apt/lists/*"
        )
        logger.info("[cyan]Installing sandbox tools: %s[/]", packages)
        response: Any = sandbox.process.exec(cmd, timeout=_TOOL_INSTALL_TIMEOUT_S)
        exit_code: int = int(getattr(response, "exit_code", -1))
        if exit_code != 0:
            tail: str = (getattr(response, "result", "") or "")[-500:]
            msg = f"Failed to install sandbox tools (exit={exit_code}): {tail}"
            raise SandboxError(msg)
        logger.info("[green]Sandbox tools installed[/]")
        self._append_log("sandbox tool install", f"packages: {packages}\nexit=0")

    # --------------------------------------------------------------- notes upload

    def _prepare_notes_dir(self) -> None:
        sandbox = self._require_sandbox()
        try:
            sandbox.fs.create_folder(_NOTES_MOUNT, "755")
        except Exception:
            # folder may already exist from a previous upload; acceptable
            logger.debug("create_folder(%s) ignored", _NOTES_MOUNT, exc_info=True)

    def _upload_notes(self) -> None:
        sandbox = self._require_sandbox()
        files = sorted(p for p in self._notes_dir.rglob("*") if p.is_file())
        if not files:
            msg = f"No files found under {self._notes_dir}"
            raise SandboxError(msg)

        uploads: list[FileUpload] = []
        for path in files:
            rel = path.relative_to(self._notes_dir).as_posix()
            uploads.append(FileUpload(source=path.read_bytes(), destination=f"{_NOTES_MOUNT}/{rel}"))
        sandbox.fs.upload_files(uploads)
        logger.info("[green]Uploaded %d files to sandbox[/]", len(uploads))

        for upload in uploads:
            try:
                sandbox.fs.set_file_permissions(upload.destination, mode="444")
            except Exception:
                logger.debug("set_file_permissions(%s) failed", upload.destination, exc_info=True)

    # ------------------------------------------------------------------ run_bash

    def run_bash(self, cmd: str, timeout: int = 30) -> BashResult:
        """Execute a bash command inside the sandbox and return truncated output."""
        sandbox = self._require_sandbox()
        logger.info("[yellow]$ %s[/]", cmd[:300])
        try:
            response: Any = sandbox.process.exec(cmd, cwd=_NOTES_MOUNT, timeout=timeout)
        except Exception as exc:
            logger.warning("[red]exec error: %s[/]", exc)
            self._append_log(f"$ {cmd}", f"[exec error] {exc}")
            return BashResult(exit_code=-1, output=f"exec error: {exc}", truncated=False)

        result_text: str = getattr(response, "result", "") or ""
        exit_code: int = int(getattr(response, "exit_code", -1))
        truncated = len(result_text.encode("utf-8")) > _MAX_RESULT_BYTES
        if truncated:
            result_text = result_text.encode("utf-8")[:_MAX_RESULT_BYTES].decode("utf-8", errors="replace")
            result_text += "\n... [output truncated]"

        logger.info("[dim]-> exit=%d bytes=%d[/]", exit_code, len(result_text))
        self._append_log(f"$ {cmd}", f"exit={exit_code}\n{result_text}")
        return BashResult(exit_code=exit_code, output=result_text, truncated=truncated)

    # -------------------------------------------------------------------- logging

    def _init_log(self) -> None:
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        header = f"# S04E04 filesystem session\n\nStarted: {datetime.now(UTC).isoformat()}\n\n"
        self._log_file.write_text(header)

    def _append_log(self, heading: str, body: str) -> None:
        self.append_log(heading, body)

    def append_log(self, heading: str, body: str) -> None:
        """Append a heading + body block to the session markdown log."""
        ts = datetime.now(UTC).strftime("%H:%M:%S")
        with self._log_file.open("a") as f:
            f.write(f"## {ts} — {heading}\n\n```\n{body}\n```\n\n")

    # ---------------------------------------------------------------------- util

    def _require_sandbox(self) -> Sandbox:
        if self._sandbox is None:
            msg = "NotesSandbox used outside of its `with` block"
            raise SandboxError(msg)
        return self._sandbox


def docker_available() -> bool:
    """Return True if the docker CLI is on PATH — used for a nicer error if not."""
    return shutil.which("docker") is not None
