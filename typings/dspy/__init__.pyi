from collections.abc import Callable
from typing import Any

from dspy.utils.callback import BaseCallback

class LM:
    history: list[dict[str, Any]]
    def __init__(
        self,
        model: str,
        *,
        api_key: str = ...,
        api_base: str = ...,
        temperature: float = ...,
        max_tokens: int = ...,
        cache: bool = ...,
        **kwargs: Any,
    ) -> None: ...

class Signature:
    def __init_subclass__(cls, **kwargs: Any) -> None: ...

class Prediction:
    trajectory: dict[str, Any]
    def __getattr__(self, name: str) -> Any: ...

class ReAct:
    def __init__(
        self,
        signature: type[Signature] | str,
        tools: list[Callable[..., Any]],
        max_iters: int = ...,
    ) -> None: ...
    def __call__(self, **kwargs: Any) -> Prediction: ...

def configure(*, lm: LM | None = ..., callbacks: list[BaseCallback] | None = ..., **kwargs: Any) -> None: ...
def InputField(*, desc: str = ..., **kwargs: Any) -> Any: ...
def OutputField(*, desc: str = ..., **kwargs: Any) -> Any: ...
