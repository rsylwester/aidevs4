# MCP Integration — Deep Reference

## Installation

```bash
uv add "pydantic-ai-slim[mcp]"
# or for FastMCP client
uv add "pydantic-ai-slim[fastmcp]"
```

## Connection Methods

### MCPServerStdio — Subprocess Transport

Runs the MCP server as a subprocess, communicates via stdin/stdout:

```python
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio

server = MCPServerStdio(
    'python',
    args=['my_mcp_server.py'],
    timeout=10,
)
agent = Agent('openai:gpt-5.2', toolsets=[server])

async with agent:
    result = await agent.run('Use the calculator to add 7 and 5.')
```

### MCPServerStreamableHTTP — HTTP Transport

Connects to an already-running MCP server via Streamable HTTP:

```python
from pydantic_ai.mcp import MCPServerStreamableHTTP

server = MCPServerStreamableHTTP('http://localhost:8000/mcp')
agent = Agent('openai:gpt-5.2', toolsets=[server])
```

The server must be running before the agent starts.

### MCPServerSSE — Server-Sent Events (Deprecated)

```python
from pydantic_ai.mcp import MCPServerSSE

server = MCPServerSSE('http://localhost:3001/sse')
```

Deprecated in favor of Streamable HTTP. Use MCPServerStreamableHTTP for new code.

## Lifecycle Management

Always use async context managers for proper connection handling:

```python
async with agent:
    result = await agent.run('prompt')
    # Server connections are properly managed
```

Without explicit context management, connections are opened/closed automatically per run (less efficient for multiple runs).

## Loading from Configuration

```python
from pydantic_ai.mcp import load_mcp_servers

servers = load_mcp_servers('mcp_config.json')
agent = Agent('openai:gpt-5.2', toolsets=servers)
```

Configuration format:
```json
{
  "mcpServers": {
    "calculator": {
      "command": "python",
      "args": ["calc_server.py"]
    },
    "weather": {
      "url": "http://localhost:3001/mcp"
    }
  }
}
```

Environment variable expansion: `${VAR}` and `${VAR:-default}` syntax supported.

## Tool Prefixes

Avoid name collisions when using multiple MCP servers:

```python
weather = MCPServerStreamableHTTP('http://localhost:8001/mcp', tool_prefix='weather')
finance = MCPServerStreamableHTTP('http://localhost:8002/mcp', tool_prefix='finance')
# Tools: weather_get_data, finance_get_data (no collision)
```

## Custom Tool Call Processing

Intercept and modify tool calls (e.g., inject dependencies):

```python
from pydantic_ai import RunContext
from pydantic_ai.mcp import CallToolFunc, ToolResult

async def process_tool_call(
    ctx: RunContext[int],
    call_tool: CallToolFunc,
    name: str,
    tool_args: dict[str, Any],
) -> ToolResult:
    # Add context before calling the actual tool
    return await call_tool(name, tool_args, {'user_id': ctx.deps})

server = MCPServerStdio(
    'python', args=['server.py'],
    process_tool_call=process_tool_call,
)
```

## MCP Sampling

Allow MCP servers to make LLM calls through your agent's model:

```python
agent = Agent('openai:gpt-5.2', toolsets=[server])
agent.set_mcp_sampling_model()  # Enable sampling

async with agent:
    result = await agent.run('Generate an SVG image.')
```

Disable with `allow_sampling=False` on the server constructor.

## Elicitation (Interactive Input)

Allow MCP servers to request user input during execution:

```python
from mcp.types import ElicitRequestParams, ElicitResult

async def handle_elicitation(context, params: ElicitRequestParams) -> ElicitResult:
    print(f'\nServer asks: {params.message}')
    # Collect and return user input
    return ElicitResult(action='accept', content={'answer': user_input})

server = MCPServerStdio(
    'python', args=['server.py'],
    elicitation_callback=handle_elicitation,
)
```

## Server Instructions

Access instructions provided by MCP servers and include them in agent context:

```python
server = MCPServerStreamableHTTP('http://localhost:8000/mcp')
agent = Agent('openai:gpt-5.2', toolsets=[server])

@agent.instructions
async def include_mcp_instructions():
    return server.instructions
```

## Resources

Read resources exposed by MCP servers:

```python
async with server:
    resources = await server.list_resources()
    content = await server.read_resource('resource://config.json')
```

## Custom TLS/SSL

```python
import ssl
import httpx

ssl_ctx = ssl.create_default_context(cafile='/path/to/ca.pem')
http_client = httpx.AsyncClient(verify=ssl_ctx)

server = MCPServerStreamableHTTP('https://secure-server:8443/mcp', http_client=http_client)
```

## Exposing an Agent as A2A Server

```python
agent = Agent('openai:gpt-5.2', instructions='You are a helpful bot.')
app = agent.to_a2a()
# Run with: uvicorn app --host 0.0.0.0 --port 8000
```
