# LangChain API Patterns Reference

## Table of Contents
1. [Migration: Old vs New](#migration-old-vs-new)
2. [create_agent API](#create_agent-api)
3. [Middleware System](#middleware-system)
4. [Structured Output Strategies](#structured-output-strategies)
5. [Tool Calling Details](#tool-calling-details)
6. [Pydantic v2 Patterns](#pydantic-v2-patterns)

---

## Migration: Old vs New

| Old (deprecated) | New (v1.2+) | Notes |
|---|---|---|
| `from langgraph.prebuilt import create_react_agent` | `from langchain.agents import create_agent` | Unified API |
| `prompt=SystemMessage(...)` | `system_prompt="string"` | String only, no message objects |
| `pre_model_hook` / `post_model_hook` | `@wrap_model_call` middleware | Class or decorator |
| Pydantic models for agent state | `TypedDict` via `AgentState` | Mandatory change |
| `config={"configurable": {...}}` | `context=MyContext(...)` with `context_schema` | Typed context |
| `handle_tool_errors` on `ToolNode` | `@wrap_tool_call` middleware | More flexible |
| `response.text()` (method call) | `response.text` (property) | Breaking change |
| `AIMessage(content="...", example=True)` | `AIMessage(content="...", additional_kwargs={"example": True})` | |
| `PydanticOutputParser` | `with_structured_output()` or `response_format=` | Native enforcement |
| `LLMChain`, `ConversationChain` | `create_agent` or direct `model.invoke()` | |
| `model.bind_tools([...])` then pass to agent | Pass `tools=` directly to `create_agent` | |

---

## create_agent API

```python
from langchain.agents import create_agent

agent = create_agent(
    model="openai:gpt-4o",          # provider:model or ChatModel instance
    tools=[search, get_weather],      # plain list of @tool functions
    system_prompt="You are helpful.", # string only
    name="my_agent",                  # optional identifier
    response_format=MySchema,         # optional Pydantic model for structured output
    context_schema=UserContext,        # optional TypedDict for typed context
    middleware=[error_handler],        # optional middleware list
)

# Invoke
result = agent.invoke(
    {"messages": [{"role": "user", "content": "..."}]},
    context=UserContext(user_id="user123"),
)

# Stream
for step in agent.stream({"messages": [...]}, stream_mode="values"):
    print(step)
```

---

## Middleware System

Replaces callbacks for cross-cutting concerns in agent workflows.

**Execution order:**
1. `before_agent` — load memory, validate input
2. `before_model` — update prompts, trim messages
3. `wrap_model_call` — intercept/modify model I/O
4. `wrap_tool_call` — intercept tool execution
5. `after_model` — validate output, guardrails
6. `after_agent` — save results, cleanup

**Decorator style:**
```python
from langchain.agents import wrap_model_call, wrap_tool_call

@wrap_model_call
def log_calls(call, messages, config):
    print(f"Calling model with {len(messages)} messages")
    return call(messages)

@wrap_tool_call
def handle_errors(call, tool_input, config):
    try:
        return call(tool_input)
    except Exception as e:
        return f"Tool error: {e}"
```

**Built-in middleware:**
- `PIIMiddleware` — redact sensitive information
- `SummarizationMiddleware` — condense long conversations
- `HumanInTheLoopMiddleware` — require approval for sensitive actions

---

## Structured Output Strategies

### ProviderStrategy (recommended for OpenAI, Anthropic, Gemini)

Automatically selected when the model natively supports structured output:

```python
agent = create_agent(model="gpt-4o", response_format=ContactInfo)
result = agent.invoke({"messages": [...]})
parsed = result["structured_response"]  # ContactInfo instance
```

### ToolStrategy (fallback, or for Union types)

```python
from langchain.agents.structured_output import ToolStrategy

agent = create_agent(
    model="gpt-4o",
    response_format=ToolStrategy(
        schema=Union[ProductReview, CustomerComplaint],
        handle_errors=True,
    ),
)
```

### Model-level (without agents)

```python
# Method 1: with_structured_output (cleanest)
structured_llm = llm.with_structured_output(MyModel)
result = structured_llm.invoke(messages)

# Method 2: with_structured_output + include_raw
result = llm.with_structured_output(MyModel, include_raw=True).invoke(messages)
# result["parsed"], result["raw"], result["parsing_error"]

# Method 3: JSON mode + manual validation (best for pyright strict)
response = llm.invoke(messages, response_format={"type": "json_object"})
result = MyModel.model_validate_json(response.content)
```

**Supported schema types:** Pydantic models (returns instance), dataclasses (returns dict), TypedDict (returns dict), JSON Schema dict (returns dict).

---

## Tool Calling Details

```python
from langchain.tools import tool, ToolRuntime
from pydantic import BaseModel, Field

class WeatherInput(BaseModel):
    location: str = Field(description="City name")
    units: Literal["celsius", "fahrenheit"] = Field(default="celsius")

@tool(args_schema=WeatherInput)
def get_weather(location: str, units: str = "celsius") -> str:
    """Get current weather for a location."""
    return f"22 degrees in {location}"
```

**ToolRuntime** for execution context:
```python
@tool
def my_tool(query: str, runtime: ToolRuntime) -> str:
    """Tool with runtime access."""
    user_id = runtime.context.user_id
    store = runtime.store
    writer = runtime.stream_writer
    return "result"
```

**Reserved parameter names:** `config`, `runtime` — never use as tool argument names.

**Return types:** `str` (text for model), `dict` (structured data), `Command` (LangGraph state update).

---

## Pydantic v2 Patterns

### Always use v2 API

```python
from pydantic import BaseModel, Field

class MyModel(BaseModel):
    name: str = Field(description="The name")
    count: int = Field(default=0, ge=0)

# Validation
obj = MyModel.model_validate({"name": "test", "count": 5})
obj = MyModel.model_validate_json('{"name": "test"}')

# Serialization
data = obj.model_dump()
json_str = obj.model_dump_json()

# Schema
schema = MyModel.model_json_schema()
```

### Never use v1 methods

| v1 (never use) | v2 (always use) |
|---|---|
| `.dict()` | `.model_dump()` |
| `.json()` | `.model_dump_json()` |
| `.parse_obj()` | `.model_validate()` |
| `.parse_raw()` | `.model_validate_json()` |
| `.schema()` | `.model_json_schema()` |
| `.update_forward_refs()` | `.model_rebuild()` |
| `from pydantic.v1 import ...` | `from pydantic import ...` |
| `@validator` | `@field_validator` |
| `@root_validator` | `@model_validator` |
| `class Config:` | `model_config = ConfigDict(...)` |
