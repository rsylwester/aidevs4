"""Multi-agent setup: orchestrator delegates research tasks to a specialist research agent.

Tracks token usage across both agents and returns a typed Report model.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.usage import Usage


class Report(BaseModel):
    """Final structured report produced by the orchestrator."""

    title: str
    findings: list[str]
    summary: str


class ResearchResult(BaseModel):
    """Structured output from the research agent."""

    finding: str
    details: str


@dataclass
class ResearchDeps:
    """Dependencies for the research agent."""

    topic: str


@dataclass
class OrchestratorDeps:
    """Dependencies for the orchestrator agent."""

    research_topic: str
    sub_questions: list[str]


# ---------------------------------------------------------------------------
# Research agent — uses a cheaper model
# ---------------------------------------------------------------------------
research_agent = Agent(
    "openai:gpt-4o-mini",
    result_type=ResearchResult,
    deps_type=ResearchDeps,
    system_prompt=(
        "You are a specialist research agent. Given a topic and a specific question, "
        "produce a concise finding and supporting details. Be factual and precise."
    ),
)


# ---------------------------------------------------------------------------
# Orchestrator agent — uses the primary model, delegates to research agent
# ---------------------------------------------------------------------------
orchestrator_agent = Agent(
    "openai:gpt-4o",
    result_type=Report,
    deps_type=OrchestratorDeps,
    system_prompt=(
        "You are a research orchestrator. You will receive findings from specialist "
        "researchers and must synthesize them into a coherent report with a title, "
        "a list of key findings, and a summary."
    ),
)


def merge_usage(a: Usage, b: Usage) -> Usage:
    """Merge two Usage objects by summing their token counts."""
    return Usage(
        requests=(a.requests or 0) + (b.requests or 0),
        request_tokens=(a.request_tokens or 0) + (b.request_tokens or 0),
        response_tokens=(a.response_tokens or 0) + (b.response_tokens or 0),
        total_tokens=(a.total_tokens or 0) + (b.total_tokens or 0),
    )


async def run_research(topic: str, question: str) -> tuple[ResearchResult, Usage]:
    """Run the research agent on a single question and return the result with usage."""
    result = await research_agent.run(
        f"Topic: {topic}\nQuestion: {question}",
        deps=ResearchDeps(topic=topic),
    )
    return result.data, result.usage()


async def run_pipeline(topic: str, sub_questions: list[str]) -> tuple[Report, Usage]:
    """Run the full multi-agent pipeline: research then orchestrate.

    Returns the final Report and the combined token usage across all agents.
    """
    # Step 1: Fan out research tasks concurrently
    research_tasks = [run_research(topic, q) for q in sub_questions]
    research_outputs = await asyncio.gather(*research_tasks)

    # Collect findings and accumulate usage
    total_usage = Usage()
    findings_text: list[str] = []
    for research_result, usage in research_outputs:
        total_usage = merge_usage(total_usage, usage)
        findings_text.append(f"- {research_result.finding}: {research_result.details}")

    compiled_findings = "\n".join(findings_text)

    # Step 2: Pass collected findings to the orchestrator for synthesis
    orchestrator_prompt = (
        f"Research topic: {topic}\n\n"
        f"The following findings were gathered by specialist researchers:\n"
        f"{compiled_findings}\n\n"
        f"Synthesize these into a final report with a clear title, "
        f"a list of key findings, and a concise summary."
    )

    deps = OrchestratorDeps(research_topic=topic, sub_questions=sub_questions)
    orchestrator_result = await orchestrator_agent.run(orchestrator_prompt, deps=deps)

    total_usage = merge_usage(total_usage, orchestrator_result.usage())

    return orchestrator_result.data, total_usage


async def main() -> None:
    """Entry point demonstrating the multi-agent pipeline."""
    topic = "Impact of artificial intelligence on healthcare"
    sub_questions = [
        "How is AI used in medical diagnostics?",
        "What are the ethical concerns of AI in healthcare?",
        "How does AI improve drug discovery timelines?",
    ]

    report, usage = await run_pipeline(topic, sub_questions)

    print(f"=== {report.title} ===\n")
    for i, finding in enumerate(report.findings, 1):
        print(f"  {i}. {finding}")
    print(f"\nSummary: {report.summary}")
    print("\n--- Token Usage (all agents) ---")
    print(f"  Requests:        {usage.requests}")
    print(f"  Request tokens:  {usage.request_tokens}")
    print(f"  Response tokens: {usage.response_tokens}")
    print(f"  Total tokens:    {usage.total_tokens}")


if __name__ == "__main__":
    asyncio.run(main())
