"""Minimal type stubs for daytona_sdk — only the surface S04E04 uses.

The upstream package ships without py.typed, so pyright in strict mode rejects
it. We declare just enough here to type-check our sandbox wrapper without
pulling in the full SDK surface.
"""

from collections.abc import Callable
from dataclasses import dataclass

class DaytonaConfig:
    def __init__(
        self,
        *,
        api_key: str | None = ...,
        api_url: str | None = ...,
        target: str | None = ...,
        jwt_token: str | None = ...,
        organization_id: str | None = ...,
        connection_pool_maxsize: int | None = ...,
    ) -> None: ...

@dataclass
class FileUpload:
    source: bytes | str
    destination: str

class CreateSandboxFromImageParams:
    def __init__(
        self,
        *,
        image: str,
        env_vars: dict[str, str] | None = ...,
        labels: dict[str, str] | None = ...,
        public: bool | None = ...,
        network_block_all: bool | None = ...,
        network_allow_list: str | None = ...,
        ephemeral: bool | None = ...,
    ) -> None: ...

class ExecuteResponse:
    exit_code: int
    result: str

class _Process:
    def exec(
        self,
        command: str,
        cwd: str | None = ...,
        env: dict[str, str] | None = ...,
        timeout: int | None = ...,
    ) -> ExecuteResponse: ...

class _FileSystem:
    def create_folder(self, path: str, mode: str) -> None: ...
    def upload_file(self, src: str | bytes, dst: str, timeout: int = ...) -> None: ...
    def upload_files(self, files: list[FileUpload], timeout: int = ...) -> None: ...
    def set_file_permissions(
        self,
        path: str,
        mode: str | None = ...,
        owner: str | None = ...,
        group: str | None = ...,
    ) -> None: ...

class Sandbox:
    fs: _FileSystem
    process: _Process
    def delete(self) -> None: ...

class Daytona:
    def __init__(self, config: DaytonaConfig | None = ...) -> None: ...
    def create(
        self,
        params: CreateSandboxFromImageParams | None = ...,
        *,
        timeout: float = ...,
        on_snapshot_create_logs: Callable[[str], None] | None = ...,
    ) -> Sandbox: ...

__all__ = [
    "CreateSandboxFromImageParams",
    "Daytona",
    "DaytonaConfig",
    "ExecuteResponse",
    "FileUpload",
    "Sandbox",
]
