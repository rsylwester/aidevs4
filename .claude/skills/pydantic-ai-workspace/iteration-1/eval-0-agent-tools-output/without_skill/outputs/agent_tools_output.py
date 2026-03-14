"""Pydantic-AI agent that searches a mock product database and returns structured results."""

from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

# ---------------------------------------------------------------------------
# Structured response model
# ---------------------------------------------------------------------------


class ProductResult(BaseModel):
    """Structured response returned by the product-search agent."""

    product_name: str = Field(description="Name of the matching product")
    price: float = Field(description="Price of the product in USD")
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence that this product matches the user query (0-1)",
    )


# ---------------------------------------------------------------------------
# Dependencies (injected into tool via RunContext)
# ---------------------------------------------------------------------------


@dataclass
class ProductDeps:
    """Dependencies available to every tool call."""

    db: dict[str, float]


# ---------------------------------------------------------------------------
# Mock product database
# ---------------------------------------------------------------------------

PRODUCT_DB: dict[str, float] = {
    "wireless mouse": 29.99,
    "mechanical keyboard": 89.99,
    "usb-c hub": 49.99,
    "monitor stand": 39.99,
    "webcam hd": 59.99,
    "noise-cancelling headphones": 199.99,
    "laptop sleeve": 24.99,
    "ergonomic chair": 349.99,
}

# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

agent = Agent(
    "openai:gpt-4o-mini",
    deps_type=ProductDeps,
    result_type=ProductResult,
    system_prompt=(
        "You are a helpful product search assistant. "
        "When the user asks about a product, use the search_products tool to look it up "
        "in the database, then return a structured result with the best matching product, "
        "its price, and your confidence that it matches the query."
    ),
)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@agent.tool
async def search_products(ctx: RunContext[ProductDeps], query: str) -> str:
    """Search the product database for items matching the query.

    Args:
        ctx: The run context carrying injected dependencies (product DB).
        query: A search string describing the product the user is looking for.

    Returns:
        A formatted string listing matching products and their prices,
        or a message indicating no matches were found.
    """
    query_lower = query.lower()
    matches: list[tuple[str, float]] = [(name, price) for name, price in ctx.deps.db.items() if query_lower in name]

    if not matches:
        return f"No products found matching '{query}'."

    lines = [f"- {name}: ${price:.2f}" for name, price in matches]
    return "Found products:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the agent with a sample question."""
    deps = ProductDeps(db=PRODUCT_DB)
    result = await agent.run("Do you have any keyboards available?", deps=deps)
    print(result.data)  # noqa: T201


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
