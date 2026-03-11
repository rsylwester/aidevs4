---
name: python-langchain
description: >
  Guide for writing Python code with LangChain v1.2+ and langchain-openai.
  Use this skill whenever writing or modifying code that imports from langchain,
  langchain_openai, langchain_core, or langchain_community — including LLM calls,
  structured output, tool calling, agents, streaming, and LCEL chains. Also trigger
  when the user asks about LangChain patterns, migration from older versions, or
  best practices for chat models, output parsing, or agent creation.
---

# LangChain v1.2+ — Python Patterns & Best Practices

This skill covers LangChain v1.2 with langchain-openai v1.1, Pydantic v2.12+, and Python 3.14.
Read `references/api-patterns.md` for detailed API examples and migration tables.

## Architecture at a Glance

```
langchain          — agents, high-level create_agent API
langchain-core     — Runnable interface, messages, base classes
langchain-openai   — ChatOpenAI, OpenAI embeddings
langchain-classic  — legacy only (LLMChain, ConversationChain, etc.) — never use in new code
```

## Core Rules

1. **Chat models only.** Never use the legacy `LLM` class (text completion). Always use `BaseChatModel` subclasses like `ChatOpenAI`.
2. **Pydantic v2 exclusively.** Never import from `pydantic.v1`. Use `BaseModel`, `Field`, `model_validate`, `model_validate_json`, `model_dump`. Never use `.dict()`, `.parse_obj()`, `.parse_raw()` — those are Pydantic v1 methods.
3. **`with_structured_output()` or `response_format` for typed responses.** Never use `PydanticOutputParser`, `JsonOutputParser`, or prompt-based format instructions for structured output.
4. **`init_chat_model()` for provider-agnostic code.** Use `from langchain.chat_models import init_chat_model` when you need to support multiple providers. Use `ChatOpenAI` directly only when OpenRouter/OpenAI-specific features are needed.
5. **`create_agent` for agentic workflows.** Never manually loop tool calls. Use `from langchain.agents import create_agent`.
6. **TypedDict for agent state.** Never use Pydantic models or dataclasses for LangGraph/agent state schemas.
7. **Snake_case tool names.** Some providers reject spaces and special characters in tool names.

## Structured Output

Prefer `with_structured_output()` on chat models for simple extraction tasks:

```python
from pydantic import BaseModel, Field

class Person(BaseModel):
    name: str = Field(description="Full name")
    age: int = Field(description="Age in years")

llm = get_llm()
structured_llm = llm.with_structured_output(Person)
result: Person = structured_llm.invoke("Extract: John is 30 years old")
```

Always add `Field(description=...)` to every field — it significantly improves extraction accuracy.

For agent-level structured output, use `response_format`:

```python
from langchain.agents import create_agent

agent = create_agent(model="openai:gpt-4o", response_format=Person, tools=[...])
result = agent.invoke({"messages": [...]})
parsed = result["structured_response"]  # Person instance
```

**Strategy selection:**
- **ProviderStrategy** (auto-selected for OpenAI, Anthropic, Gemini) — uses native JSON schema enforcement, highest reliability
- **ToolStrategy** — fallback for other models, also required for `Union` types

### JSON mode fallback

When `with_structured_output` has typing issues (e.g., partially unknown return types from pyright), use JSON mode + Pydantic validation:

```python
response = llm.invoke(messages, response_format={"type": "json_object"})
result = MyModel.model_validate_json(response.content)  # type: ignore[arg-type]
```

The `type: ignore[arg-type]` is acceptable here because `response.content` is typed as `str | list` but JSON mode always returns `str`. This is a known LangChain typing limitation.

## Message Formats

```python
# Dict format (preferred for simplicity)
messages = [
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello"},
]

# Object format (when you need metadata)
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
messages = [SystemMessage(content="..."), HumanMessage(content="...")]
```

## Tool Calling

Define tools with the `@tool` decorator:

```python
from langchain.tools import tool
from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(description="Search query")
    max_results: int = Field(default=5, description="Max results to return")

@tool(args_schema=SearchInput)
def search(query: str, max_results: int = 5) -> str:
    """Search the web for information."""
    ...
```

**Reserved parameter names** — never use `config` or `runtime` as tool argument names.

**Bind tools to models** (low-level):
```python
model = get_llm().bind_tools([search])
response = model.invoke("Find info about LangChain")
for tc in response.tool_calls:
    print(tc["name"], tc["args"])
```

## Streaming

```python
# Sync streaming
for chunk in llm.stream(messages):
    print(chunk.content, end="", flush=True)

# Async streaming
async for chunk in llm.astream(messages):
    print(chunk.content, end="", flush=True)
```

## Batch Processing

```python
# Process multiple inputs in parallel
results = llm.batch([messages_1, messages_2, messages_3])

# With concurrency limit
results = llm.batch(inputs, config={"max_concurrency": 5})
```

## Rate Limiting

```python
from langchain_core.rate_limiters import InMemoryRateLimiter

rate_limiter = InMemoryRateLimiter(requests_per_second=0.5)
llm = ChatOpenAI(model="gpt-4o", rate_limiter=rate_limiter)
```

## Token Usage Tracking

```python
from langchain_core.callbacks import UsageMetadataCallbackHandler

callback = UsageMetadataCallbackHandler()
llm.invoke(messages, config={"callbacks": [callback]})
print(callback.usage_metadata)  # input_tokens, output_tokens
```

## Pyright Strict Mode Compatibility

LangChain's type stubs are incomplete. Use these patterns to stay at 0 warnings:

| Problem | Solution |
|---------|----------|
| `with_structured_output()` returns partially unknown type | Add `# pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]` |
| `invoke()` on structured runnable returns unknown | Use `cast("MyModel", raw)` or JSON mode + `model_validate_json` |
| `ChatOpenAI` constructor arg types | `# type: ignore[arg-type]` for `api_key` (SecretStr vs str) |
| `response.content` is `str | list[str | dict]` | `# type: ignore[arg-type]` when passing to `model_validate_json` |

Prefer runtime validation (Pydantic `model_validate_json`) over `cast` when possible — it provides actual type safety, not just type checker silence.

## Project-Specific Conventions

This project uses OpenRouter as the LLM provider. The shared factory is in `lib/llm.py`:

```python
from lib.llm import get_llm

llm = get_llm()                          # default: openai/gpt-4o-mini via OpenRouter
llm = get_llm("anthropic/claude-sonnet-4-20250514")  # specific model
```

Never instantiate `ChatOpenAI` directly in task code — always use `get_llm()`.
