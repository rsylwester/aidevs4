from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

@contextmanager
def propagate_attributes(*, session_id: str, trace_name: str) -> Iterator[None]: ...
def get_client() -> Any: ...
