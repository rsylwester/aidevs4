"""Connect a pydantic-ai agent to two MCP servers with namespace prefixing to avoid tool-name collisions."""

import asyncio

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerHTTP, MCPServerStdio


async def main() -> None:
    # HTTP-based MCP server (SSE transport)
    http_server = MCPServerHTTP(
        url="http://localhost:8000/mcp",
        tool_prefix="http",  # tools will be prefixed as "http_<tool_name>"
    )

    # Stdio-based MCP server (local process)
    stdio_server = MCPServerStdio(
        command="python",
        args=["./tools/calculator.py"],
        tool_prefix="calc",  # tools will be prefixed as "calc_<tool_name>"
    )

    agent = Agent(
        "openai:gpt-4o",
        mcp_servers=[http_server, stdio_server],
    )

    # Use `agent.run()` inside an `async with` that manages MCP server lifecycles
    async with agent.run_mcp_servers():
        result = await agent.run("What tools do you have available?")
        print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
