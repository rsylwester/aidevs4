"""Multi-agent orchestrator with research delegation and token usage tracking."""

import asyncio
import logging

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, RunUsage

logger = logging.getLogger(__name__)


# --- Output models ---


class Report(BaseModel):
    """Final structured report produced by the orchestrator."""

    title: str = Field(description="Title of the report")
    findings: list[str] = Field(description="Key findings from research")
    summary: str = Field(description="Executive summary of all findings")


# --- Specialist research agent (cheaper model) ---

research_agent = Agent(
    "openai:gpt-5-mini",
    output_type=list[str],
    instructions=(
        "You are a research specialist. Given a research task, return a list of "
        "concise, factual findings. Each finding should be a single clear sentence."
    ),
)

# --- Main orchestrator agent ---

orchestrator_agent = Agent(
    "anthropic:claude-sonnet-4-6",
    output_type=Report,
    instructions=(
        "You are a report orchestrator. When given a topic, use the research tool "
        "to gather findings, then produce a structured Report with a title, the "
        "research findings, and a concise summary."
    ),
)


@orchestrator_agent.tool
async def research(ctx: RunContext[None], topic: str) -> list[str]:
    """Delegate a research task to the specialist research agent.

    Args:
        topic: The topic or question to research.
    """
    result = await research_agent.run(
        f"Research the following topic and return key findings: {topic}",
        usage=ctx.usage,  # Aggregate token counts across agents
    )
    return result.output


async def main() -> None:
    """Run the orchestrator and print the report with token usage."""
    usage = RunUsage()

    result = await orchestrator_agent.run(
        "Investigate the current state of quantum computing and its practical applications.",
        usage=usage,
    )

    report = result.output
    logger.info("=== Report ===")
    logger.info("Title: %s", report.title)
    logger.info("Findings:")
    for i, finding in enumerate(report.findings, 1):
        logger.info("  %d. %s", i, finding)
    logger.info("Summary: %s", report.summary)

    logger.info("\n=== Token Usage (across both agents) ===")
    logger.info("Request count: %d", usage.request_count)
    logger.info("Input tokens:  %d", usage.input_tokens)
    logger.info("Output tokens: %d", usage.output_tokens)
    logger.info("Total tokens:  %d", usage.total_tokens)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
