# Agents — Deep Reference

## Constructor Parameters (Full List)

```python
Agent[DepsType, OutputType](
    model: str | Model | None = None,
    *,
    deps_type: type[DepsType] = type(None),
    output_type: OutputType | list[OutputType] = str,
    instructions: str | None = None,
    system_prompt: str | Sequence[str] = (),
    tools: Sequence[Tool | Callable] = (),
    toolsets: Sequence[Toolset] = (),
    model_settings: ModelSettings | None = None,
    retries: int = 1,
    end_strategy: Literal['early', 'exhaustive'] = 'early',
    max_concurrency: int | ConcurrencyLimit | None = None,
    metadata: dict[str, Any] | Callable[..., dict[str, Any]] | None = None,
    instrument: bool | InstrumentationSettings = False,
)
```

### `instructions` vs `system_prompt`

Both provide guidance to the LLM, but they differ in message history behavior:

- **`instructions`**: Always re-evaluated on each run. When `message_history` is provided, instructions
  are still included (re-computed if dynamic). Use for guidance that should persist across continued conversations.
- **`system_prompt`**: Preserved in message history. When `message_history` is provided, system prompts
  from history are used and agent-level system prompts are NOT re-added. Use for initial context that
  doesn't need updating.

### `end_strategy`

Controls behavior when the LLM makes tool calls alongside an output response:
- `'early'` (default): Stop after first valid output, skip remaining tool calls
- `'exhaustive'`: Execute all tool calls before using the output

### `retries`

Default retry count for tools and output validation. When validation fails, the agent sends the error
back to the LLM as a reflection prompt, giving it a chance to self-correct. Individual tools can
override with `@agent.tool(retries=N)`.

## Dynamic Prompts

### `@agent.system_prompt`

```python
@agent.system_prompt
def static_prompt() -> str:
    return 'You are a helpful assistant.'

@agent.system_prompt
async def dynamic_prompt(ctx: RunContext[MyDeps]) -> str:
    user = await ctx.deps.db.get_user(ctx.deps.user_id)
    return f'The user is {user.name}, role: {user.role}.'
```

Multiple system prompts are concatenated. Static (no `RunContext`) prompts are evaluated once.

### `@agent.instructions`

```python
@agent.instructions
async def dynamic_instructions(ctx: RunContext[MyDeps]) -> str:
    return f'Current time: {datetime.now()}. User timezone: {ctx.deps.timezone}.'
```

Instructions are re-evaluated on every run, even when `message_history` is provided.

### Runtime Instructions Override

```python
result = await agent.run('prompt', instructions='Override instructions for this run only.')
```

## Model Settings Hierarchy

Settings merge with later values taking priority:

1. **Model-level defaults**: `OpenAIChatModel(settings=ModelSettings(temperature=0.5))`
2. **Agent-level defaults**: `Agent(model_settings=ModelSettings(temperature=0.3))`
3. **Run-time overrides**: `agent.run('p', model_settings=ModelSettings(temperature=0.0))`

Common settings: `temperature`, `max_tokens`, `timeout`, `top_p`.

Provider-specific subclasses add extra options:
- `GoogleModelSettings`: `gemini_safety_settings`
- `AnthropicModelSettings`: provider-specific params
- etc.

## Run Methods — Details

### `agent.run()`

```python
result: AgentRunResult[OutputType] = await agent.run(
    user_prompt='Your question',
    deps=MyDeps(...),
    message_history=previous_messages,
    instructions='Optional override',
    model_settings=ModelSettings(temperature=0),
    usage_limits=UsageLimits(request_limit=10),
    metadata={'session': 'abc123'},
)

result.output        # OutputType — validated result
result.usage()       # RunUsage — token counts
result.new_messages()  # Messages from this run only
result.all_messages()  # All messages including history
result.metadata      # Merged metadata dict
```

### `agent.iter()` — Graph Iteration

Gives fine-grained control over execution. Each node represents an execution step:

```python
from pydantic_ai.agent import End

async with agent.iter('prompt', deps=deps) as run:
    node = run.next_node
    while not isinstance(node, End):
        # Inspect node type
        if Agent.is_model_request_node(node):
            print('About to call LLM')
        elif Agent.is_call_tools_node(node):
            print(f'About to call tools')
        node = await run.next(node)

    print(run.result.output)
```

Node types: `UserPromptNode`, `ModelRequestNode`, `CallToolsNode`, `End`.

## Concurrency Control

```python
from pydantic_ai import ConcurrencyLimit

# Simple limit
agent = Agent('model', max_concurrency=10)

# Advanced: separate running vs queued limits
agent = Agent('model', max_concurrency=ConcurrencyLimit(max_running=10, max_queued=100))
```

## Metadata

```python
# Static
agent = Agent('model', metadata={'app': 'myapp'})

# Dynamic (called each run)
agent = Agent('model', metadata=lambda: {'timestamp': datetime.now().isoformat()})

# Runtime override (merged with agent-level)
result = await agent.run('prompt', metadata={'request_id': 'abc'})
```

## Durable Execution

Preserve agent progress across transient failures:

```python
# With DBOS
uv add "pydantic-ai[dbos]"

# With Prefect
uv add "pydantic-ai[prefect]"
```

Enables resumption after API failures, application restarts, etc.
