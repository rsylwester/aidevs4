"""FastAPI proxy server with LLM agent loop and MCP SSE client."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from pydantic import BaseModel

from lib.hub import submit_answer
from lib.llm import get_llm
from tasks.S01E03_proxy.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Session store: sessionID -> message history
_sessions: dict[str, list[Any]] = {}

MAX_ITERATIONS = 5
MCP_SSE_URL = "http://localhost:8001/sse"
PUBLIC_URL: str = ""  # set by __main__ before uvicorn starts


class ChatRequest(BaseModel):
    sessionID: str  # noqa: N815
    msg: str


class ChatResponse(BaseModel):
    msg: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Connect to MCP tools server over SSE during app lifetime."""
    async with (
        sse_client(MCP_SSE_URL) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools_result = await session.list_tools()

        # Convert MCP tools to OpenAI function-calling format for bind_tools
        openai_tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
            for t in tools_result.tools
        ]

        app.state.mcp_session = session
        app.state.openai_tools = openai_tools
        logger.info("MCP tools loaded: %s", [t["function"]["name"] for t in openai_tools])

        # Submit to hub now that server is ready to receive requests
        if PUBLIC_URL:
            result = submit_answer("proxy", {"url": PUBLIC_URL, "sessionID": "proxy"})
            logger.info("[bold green]Hub response: %s[/]", result)

        yield


app = FastAPI(lifespan=lifespan)


@app.post("/")
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Handle chat messages with agent loop."""
    logger.info("[bold cyan]Session %s | msg: %s[/]", body.sessionID, body.msg)

    from langfuse import propagate_attributes  # pyright: ignore[reportMissingImports, reportUnknownVariableType]

    session: ClientSession = request.app.state.mcp_session
    openai_tools: list[dict[str, Any]] = request.app.state.openai_tools

    sid = body.sessionID

    with propagate_attributes(session_id=sid, trace_name="proxy-chat"):  # pyright: ignore[reportUnknownMemberType]
        llm = get_llm("openai/gpt-4.1-mini")
        llm_with_tools = llm.bind_tools(openai_tools)  # pyright: ignore[reportUnknownMemberType]

        # Get or create session history
        if sid not in _sessions:
            _sessions[sid] = [SystemMessage(content=SYSTEM_PROMPT)]

        history = _sessions[sid]
        history.append(HumanMessage(content=body.msg))

        # Agent loop
        for i in range(MAX_ITERATIONS):
            logger.info("[dim][%s] Iteration %d/%d[/]", sid, i + 1, MAX_ITERATIONS)
            response: AIMessage = await llm_with_tools.ainvoke(history)  # type: ignore[assignment]
            history.append(response)

            tool_calls = cast("list[dict[str, Any]]", response.tool_calls)
            if not tool_calls:
                content = str(response.content)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                logger.info("[bold green][%s] Response: %s[/]", sid, content)
                return ChatResponse(msg=content)

            for tc in tool_calls:
                tool_name: str = tc["name"]
                tool_args: dict[str, Any] = tc["args"]
                logger.info("[yellow][%s] Tool call: %s(%s)[/]", sid, tool_name, tool_args)

                # Call MCP tool via SSE session
                result = await session.call_tool(tool_name, tool_args)
                result_text = str(result.content[0].text) if result.content else "No result"  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
                logger.info("[dim][%s] Tool result: %s[/]", sid, result_text[:200])
                history.append(ToolMessage(content=result_text, tool_call_id=tc["id"]))

    # Fallback if max iterations hit
    logger.warning("[%s] Max iterations reached", sid)
    return ChatResponse(msg="Przepraszam, wystąpił problem z przetwarzaniem zapytania.")
