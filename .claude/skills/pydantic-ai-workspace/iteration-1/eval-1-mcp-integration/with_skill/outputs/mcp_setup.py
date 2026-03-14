"""Connect a pydantic-ai agent to two MCP servers with tool-prefix namespacing."""

import asyncio
import logging

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStdio, MCPServerStreamableHTTP

logger = logging.getLogger(__name__)


def build_agent() -> Agent[None, str]:
    """Create an agent wired to both an HTTP and a stdio MCP server.

    Tool prefixes prevent name collisions: tools from the HTTP server are
    prefixed with ``http_`` and tools from the calculator are prefixed with
    ``calc_``.
    """
    http_server = MCPServerStreamableHTTP(
        "http://localhost:8000/mcp",
        tool_prefix="http",
    )

    stdio_server = MCPServerStdio(
        "python",
        args=["./tools/calculator.py"],
        tool_prefix="calc",
    )

    agent = Agent(
        "openai:gpt-5.2",
        toolsets=[http_server, stdio_server],
        instructions="You have access to remote HTTP tools (prefixed http_) and a local calculator (prefixed calc_). Use them to answer questions.",
    )
    return agent


async def main() -> None:
    agent = build_agent()

    # async-with ensures both MCP connections are properly started and torn down
    async with agent:
        result = await agent.run("What is 42 * 17?")
        logger.info("Agent response: %s", result.output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
