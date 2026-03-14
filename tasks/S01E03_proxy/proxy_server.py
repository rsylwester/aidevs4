"""FastAPI proxy server with LLM agent loop and MCP SSE client."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import FastAPI, Request  # pyright: ignore[reportMissingTypeStubs]
from langchain_core.messages import (  # pyright: ignore[reportMissingTypeStubs]
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from mcp.client.session import ClientSession  # pyright: ignore[reportMissingTypeStubs]
from mcp.client.sse import sse_client  # pyright: ignore[reportMissingTypeStubs]
from pydantic import BaseModel  # pyright: ignore[reportMissingTypeStubs]

from lib.hub import submit_answer
from lib.llm import get_llm
from tasks.S01E03_proxy.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Session store: sessionID -> message history
_sessions: dict[str, list[Any]] = {}

MAX_ITERATIONS = 5
MCP_SSE_URL = "http://localhost:8001/sse"
PUBLIC_URL: str = ""  # set by __main__ before uvicorn starts


class ChatRequest(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    sessionID: str  # noqa: N815
    msg: str


class ChatResponse(BaseModel):  # pyright: ignore[reportUntypedBaseClass]
    msg: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # pyright: ignore[reportUnknownParameterType]
    """Connect to MCP tools server over SSE during app lifetime."""
    async with (  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        sse_client(MCP_SSE_URL) as (read, write),
        ClientSession(read, write) as session,  # pyright: ignore[reportUnknownArgumentType]
    ):
        await session.initialize()  # pyright: ignore[reportUnknownMemberType]
        tools_result = await session.list_tools()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

        # Convert MCP tools to OpenAI function-calling format for bind_tools
        openai_tools: list[dict[str, Any]] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,  # pyright: ignore[reportUnknownMemberType]
                    "description": t.description or "",  # pyright: ignore[reportUnknownMemberType]
                    "parameters": t.inputSchema,  # pyright: ignore[reportUnknownMemberType]
                },
            }
            for t in tools_result.tools  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        ]

        app.state.mcp_session = session  # pyright: ignore[reportUnknownMemberType]
        app.state.openai_tools = openai_tools  # pyright: ignore[reportUnknownMemberType]
        logger.info("MCP tools loaded: %s", [t["function"]["name"] for t in openai_tools])

        # Submit to hub now that server is ready to receive requests
        if PUBLIC_URL:
            result = submit_answer("proxy", {"url": PUBLIC_URL, "sessionID": "proxy"})
            logger.info("[bold green]Hub response: %s[/]", result)

        yield


app = FastAPI(lifespan=lifespan)  # pyright: ignore[reportUnknownMemberType]


@app.post("/")  # pyright: ignore[reportUnknownMemberType, reportUntypedFunctionDecorator]
async def chat(request: Request, body: ChatRequest) -> ChatResponse:  # pyright: ignore[reportUnknownParameterType]
    """Handle chat messages with agent loop."""
    logger.info("[bold cyan]Session %s | msg: %s[/]", body.sessionID, body.msg)

    session: ClientSession = request.app.state.mcp_session  # pyright: ignore[reportUnknownMemberType]
    openai_tools: list[dict[str, Any]] = request.app.state.openai_tools  # pyright: ignore[reportUnknownMemberType]

    llm = get_llm("openai/gpt-4.1-mini")
    llm_with_tools = llm.bind_tools(openai_tools)  # pyright: ignore[reportUnknownMemberType]

    # Get or create session history
    if body.sessionID not in _sessions:
        _sessions[body.sessionID] = [SystemMessage(content=SYSTEM_PROMPT)]  # pyright: ignore[reportUnknownMemberType]

    history = _sessions[body.sessionID]
    history.append(HumanMessage(content=body.msg))  # pyright: ignore[reportUnknownMemberType]

    # Agent loop
    for i in range(MAX_ITERATIONS):
        logger.info("[dim]Iteration %d/%d[/]", i + 1, MAX_ITERATIONS)
        response: AIMessage = await llm_with_tools.ainvoke(history)  # pyright: ignore[reportAssignmentType, reportUnknownMemberType]
        history.append(response)

        tool_calls = cast("list[dict[str, Any]]", response.tool_calls)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        if not tool_calls:
            content = str(response.content)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            logger.info("[bold green]Response: %s[/]", content)
            return ChatResponse(msg=content)

        for tc in tool_calls:
            tool_name: str = tc["name"]
            tool_args: dict[str, Any] = tc["args"]
            logger.info("[yellow]Tool call: %s(%s)[/]", tool_name, tool_args)

            # Call MCP tool via SSE session
            result = await session.call_tool(tool_name, tool_args)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            result_text = result.content[0].text if result.content else "No result"  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType, reportAttributeAccessIssue]
            logger.info("[dim]Tool result: %s[/]", str(result_text)[:200])  # pyright: ignore[reportUnknownArgumentType]
            history.append(ToolMessage(content=str(result_text), tool_call_id=tc["id"]))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

    # Fallback if max iterations hit
    logger.warning("Max iterations reached for session %s", body.sessionID)
    return ChatResponse(msg="Przepraszam, wystąpił problem z przetwarzaniem zapytania.")
