# Multi-Agent Patterns — Deep Reference

## Complexity Levels

Pydantic AI supports five levels of multi-agent architecture, from simple to complex:

1. **Single agent** — one agent handles everything
2. **Agent delegation** — agents call other agents via tools
3. **Programmatic hand-off** — application code orchestrates agent sequence
4. **Graph-based** — state machine with typed nodes and edges
5. **Deep agents** — autonomous agents with planning, file ops, sandboxing

## 1. Agent Delegation

One agent delegates to another via a tool call. The delegate runs, returns, and the main agent continues:

```python
from pydantic_ai import Agent, RunContext

research_agent = Agent('openai:gpt-5.2', output_type=list[str])
writer_agent = Agent('anthropic:claude-sonnet-4-6')

@writer_agent.tool
async def research(ctx: RunContext[None], topic: str) -> list[str]:
    """Research a topic and return key facts."""
    result = await research_agent.run(
        f'Find key facts about: {topic}',
        usage=ctx.usage,  # Aggregate token counts
    )
    return result.output
```

Key points:
- Agents are stateless — define them at module level, not inside functions
- Always pass `usage=ctx.usage` to aggregate token/request counts
- Delegates can use different models (cost optimization)
- Use `UsageLimits` to cap total consumption across agents

### With Shared Dependencies

```python
@dataclass
class SharedDeps:
    http_client: httpx.AsyncClient
    api_key: str

main_agent = Agent('openai:gpt-5.2', deps_type=SharedDeps)
helper_agent = Agent('google:gemini-3-flash-preview', deps_type=SharedDeps)

@main_agent.tool
async def delegate(ctx: RunContext[SharedDeps], task: str) -> str:
    result = await helper_agent.run(task, deps=ctx.deps, usage=ctx.usage)
    return result.output
```

## 2. Programmatic Hand-off

Application code decides which agent runs next. Useful for multi-step workflows with
human-in-the-loop between steps:

```python
from pydantic_ai import RunUsage, UsageLimits

async def workflow():
    usage = RunUsage()
    limits = UsageLimits(request_limit=30)

    # Step 1: Research
    research_result = await research_agent.run(
        'Analyze market trends',
        usage=usage,
        usage_limits=limits,
    )

    # Step 2: Human review
    approved = await get_human_approval(research_result.output)
    if not approved:
        return

    # Step 3: Write report using research
    report = await writer_agent.run(
        f'Write report based on: {research_result.output}',
        usage=usage,
        usage_limits=limits,
    )
    return report.output
```

### Message History Sharing

Continue conversations across agents:

```python
result1 = await agent_a.run('Initial question')
result2 = await agent_b.run(
    'Follow-up using context from agent A',
    message_history=result1.all_messages(),
)
```

## 3. Graph-Based Orchestration

For complex workflows where standard control flow becomes unwieldy. Uses `pydantic-graph`:

```python
from dataclasses import dataclass
from pydantic_ai import Agent
from pydantic_graph import BaseNode, End, Graph, GraphRunContext

@dataclass
class WorkflowState:
    topic: str
    research: list[str] | None = None
    draft: str | None = None

@dataclass
class ResearchNode(BaseNode[WorkflowState]):
    async def run(self, ctx: GraphRunContext[WorkflowState]) -> 'WriteNode':
        result = await research_agent.run(f'Research: {ctx.state.topic}')
        ctx.state.research = result.output
        return WriteNode()

@dataclass
class WriteNode(BaseNode[WorkflowState]):
    async def run(self, ctx: GraphRunContext[WorkflowState]) -> 'ReviewNode | End[str]':
        result = await writer_agent.run(
            f'Write about: {ctx.state.research}'
        )
        ctx.state.draft = result.output
        return ReviewNode()

@dataclass
class ReviewNode(BaseNode[WorkflowState]):
    async def run(self, ctx: GraphRunContext[WorkflowState]) -> 'WriteNode | End[str]':
        result = await reviewer_agent.run(f'Review: {ctx.state.draft}')
        if result.output.needs_revision:
            return WriteNode()  # Loop back
        return End(ctx.state.draft)

graph = Graph(nodes=[ResearchNode, WriteNode, ReviewNode])
result = await graph.run(
    ResearchNode(),
    state=WorkflowState(topic='AI safety'),
)
```

### Graph Features

- **Type-safe edges**: Return type annotations define valid transitions
- **State persistence**: `SimpleStatePersistence`, `FullStatePersistence`, `FileStatePersistence`
- **Visualization**: `graph.mermaid_code()`, `graph.mermaid_image()`
- **Manual iteration**: `async with graph.iter(...) as run: ...`
- **Resume from checkpoint**: `graph.iter_from_persistence(persistence)`

## 4. Deep Agents

Community package `pydantic-deep` for autonomous agents with:
- Planning and step tracking
- File system abstraction
- Sub-agent delegation with isolated context
- Sandboxed code execution
- Conversation summarization for token management
- Human-in-the-loop approval workflows
- Durable execution across failures

## Observability

```python
import logfire
logfire.configure()
logfire.instrument_pydantic_ai()
```

Traces show: which agent handled each part, delegation decisions, per-agent latency and tokens,
tool call internals. Supports cross-language tracing via OpenTelemetry.
