---
name: pydantic-ai
description: >
  Guide for building AI agents, LLM-powered tools, and structured AI output with pydantic-ai v1.x.
  Use this skill whenever writing or modifying Python code that imports from pydantic_ai — including
  agent creation, tool registration, structured output, dependency injection, MCP integration,
  multi-agent orchestration, streaming, and graph workflows. Also trigger when the user asks to build
  AI agents with type safety, create LLM tools with Pydantic validation, implement agent delegation,
  connect MCP servers, or wants structured/validated LLM responses — even if they don't explicitly
  mention "pydantic-ai". Trigger when you see imports like `from pydantic_ai import Agent` or
  `from pydantic_ai.mcp import MCPServerStdio`. DO NOT trigger for plain pydantic (validation only),
  LangChain, or Anthropic SDK code.
---

# Pydantic AI Skill

Build production-grade AI agents the Pydantic way — type-safe, model-agnostic, with first-class
dependency injection and structured output validation.

**Version**: v1.x (stable API since September 2025, no breaking changes until v2 — April 2026 earliest)

**Install**: `uv add pydantic-ai` (full) or `uv add pydantic-ai-slim` (minimal, pick extras)

## Quick Reference

### Agent Creation

```python
from pydantic_ai import Agent

# Minimal agent — returns str by default
agent = Agent('openai:gpt-5.2', instructions='You are helpful.')

# Typed agent with structured output
agent = Agent(
    'anthropic:claude-sonnet-4-6',
    deps_type=MyDeps,
    output_type=MyOutput,
    instructions='Extract structured data from user queries.',
    retries=3,
)
```

**Key constructor parameters**: `model`, `deps_type`, `output_type`, `instructions`, `system_prompt`,
`model_settings`, `retries`, `end_strategy`, `tools`, `toolsets`, `max_concurrency`, `metadata`, `instrument`.

### Run Methods

| Method | Use case |
|---|---|
| `agent.run(prompt)` | Async, returns `AgentRunResult` |
| `agent.run_sync(prompt)` | Sync wrapper |
| `agent.run_stream(prompt)` | Async streaming context manager |
| `agent.run_stream_events(prompt)` | Async iterable of all events |
| `agent.iter(prompt)` | Node-by-node graph iteration |

All accept: `deps`, `message_history`, `instructions`, `model_settings`, `usage_limits`, `metadata`.

### Model Identifiers

Format: `provider:model-name`. Examples:
- `'openai:gpt-5.2'`, `'openai:gpt-5-mini'`
- `'anthropic:claude-sonnet-4-6'`, `'anthropic:claude-opus-4-6'`
- `'google:gemini-3-flash-preview'`
- `'deepseek:deepseek-chat'`
- `'groq:llama-4-scout-17b-16e-instruct'`
- `'ollama:llama3.2'`

Also supported: Azure AI Foundry, Bedrock, Vertex AI, Mistral, Cohere, OpenRouter, Together, Fireworks, etc.

### Tools

```python
# Tool with agent context (dependencies, usage tracking)
@agent.tool
async def get_balance(ctx: RunContext[MyDeps], account_id: int) -> float:
    """Get account balance. Args: account_id: The account to look up."""
    return await ctx.deps.db.get_balance(account_id)

# Plain tool without context
@agent.tool_plain
def roll_dice() -> str:
    """Roll a six-sided die."""
    return str(random.randint(1, 6))
```

- Docstrings become LLM tool descriptions; parameter docs extracted for schema
- Supports Google, NumPy, Sphinx docstring formats
- Raise `ModelRetry('message')` to ask LLM to retry with feedback
- Use `retries=N` parameter on decorator for per-tool retry limits

### Structured Output

```python
from pydantic import BaseModel, Field
from pydantic_ai import Agent

class CityLocation(BaseModel):
    city: str
    country: str = Field(description='ISO country code')

agent = Agent('openai:gpt-5.2', output_type=CityLocation)
result = agent.run_sync('Where were the 2012 Olympics?')
print(result.output)  # CityLocation(city='London', country='GB')
```

Multiple output types — use a list (better type checking than unions):
```python
agent = Agent('openai:gpt-5.2', output_type=[SuccessResult, ErrorResult])
```

### Dependencies

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class AppDeps:
    db: DatabaseConn
    api_key: str

agent = Agent('openai:gpt-5.2', deps_type=AppDeps)

@agent.tool
async def lookup(ctx: RunContext[AppDeps], query: str) -> str:
    return await ctx.deps.db.search(query)

result = await agent.run('Find users', deps=AppDeps(db=conn, api_key='...'))
```

### Message History (Multi-turn)

```python
result1 = agent.run_sync('Who was Einstein?')
result2 = agent.run_sync(
    'What was his most famous equation?',
    message_history=result1.new_messages(),
)
```

### Streaming

```python
# Text streaming
async with agent.run_stream('Tell me a story') as response:
    async for text in response.stream_text():
        print(text, end='', flush=True)

# Structured output streaming
async with agent.run_stream('Extract data', deps=deps) as response:
    async for chunk in response.stream_output():
        print(chunk)  # Partial validated output
```

## When to Consult Reference Files

For deeper coverage, read the appropriate reference file:

| Topic | File | When to read |
|---|---|---|
| Agent config details | `references/agents.md` | Dynamic prompts, model settings hierarchy, iteration, overrides |
| Tools in depth | `references/tools.md` | Tool registration patterns, prepare functions, deferred tools, human-in-the-loop |
| Output types | `references/output.md` | Union outputs, output functions, TextOutput, ToolOutput, NativeOutput, PromptedOutput, validators, streaming caveats |
| MCP integration | `references/mcp.md` | Connecting MCP servers, MCPServerStdio/HTTP, toolsets, sampling, elicitation |
| Multi-agent | `references/multi-agent.md` | Agent delegation, programmatic hand-off, graphs, deep agents |
| Models | `references/models.md` | All providers, model-specific settings, custom models |

## Key Patterns

### Dynamic System Prompts

```python
@agent.instructions
async def custom_instructions(ctx: RunContext[MyDeps]) -> str:
    user = await ctx.deps.db.get_user(ctx.deps.user_id)
    return f'You are helping {user.name}, a {user.role}.'
```

### Output Validators

```python
from pydantic_ai import Agent, RunContext, ModelRetry

@agent.output_validator
async def validate(ctx: RunContext[MyDeps], output: MyOutput) -> MyOutput:
    if not await ctx.deps.db.verify(output.query):
        raise ModelRetry(f'Invalid query, try again.')
    return output
```

### Usage Limits

```python
from pydantic_ai import UsageLimits

result = await agent.run(
    'prompt',
    usage_limits=UsageLimits(response_tokens_limit=500, request_limit=5),
)
```

### MCP Server Connection

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio, MCPServerStreamableHTTP

# Subprocess-based
server = MCPServerStdio('python', args=['my_server.py'])
# HTTP-based
server = MCPServerStreamableHTTP('http://localhost:8000/mcp')

agent = Agent('openai:gpt-5.2', toolsets=[server])
async with agent:
    result = await agent.run('Use the tools to help me.')
```

### Agent Delegation

```python
specialist = Agent('openai:gpt-5.2', output_type=list[str])

@main_agent.tool
async def delegate(ctx: RunContext[None], task: str) -> list[str]:
    """Delegate specialized work."""
    r = await specialist.run(task, usage=ctx.usage)
    return r.output
```

### Graph Iteration (Advanced Control Flow)

```python
async with agent.iter('complex task', deps=deps) as run:
    async for node in run:
        if Agent.is_call_tools_node(node):
            # Inspect or modify tool calls before execution
            pass
```

## Common Mistakes to Avoid

- **Don't pass `RunContext` manually** — it's injected automatically. Just declare it as the first parameter.
- **Don't forget `async with agent:`** when using MCP servers — connections need lifecycle management.
- **Don't use `output_type=Foo | Bar` without `# type: ignore`** — use `output_type=[Foo, Bar]` list syntax instead for proper type checking.
- **Don't ignore `ModelRetry`** — it's the primary mechanism for tools to give the LLM feedback on bad inputs.
- **Don't hardcode model strings everywhere** — pass models at construction or runtime for flexibility.
- **Don't skip `usage=ctx.usage`** when delegating to sub-agents — token counts won't aggregate.

## Observability

```python
# Logfire (official integration)
import logfire
logfire.configure()
logfire.instrument_pydantic_ai()
```

## Testing

Use dependency injection to mock external services:
```python
result = agent.run_sync('test prompt', deps=MockDeps(db=FakeDB()))
assert isinstance(result.output, ExpectedType)
```
