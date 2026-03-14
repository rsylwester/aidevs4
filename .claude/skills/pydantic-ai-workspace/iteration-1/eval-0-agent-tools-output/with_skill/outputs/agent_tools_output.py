"""Product search agent using pydantic-ai with structured output and tool usage."""

from pydantic import BaseModel, Field
from pydantic_ai import Agent

# Mock product database
PRODUCT_DB: dict[str, dict[str, float]] = {
    "wireless mouse": {"price": 29.99},
    "mechanical keyboard": {"price": 89.99},
    "usb-c hub": {"price": 45.00},
    "monitor stand": {"price": 34.50},
    "webcam hd": {"price": 59.99},
    "noise cancelling headphones": {"price": 199.99},
    "laptop stand": {"price": 42.00},
    "desk lamp": {"price": 27.50},
}


class ProductResult(BaseModel):
    """Structured response for a product search query."""

    product_name: str = Field(description="The name of the matched product")
    price: float = Field(description="The price of the product in USD")
    confidence_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence that this product matches the user query (0-1)",
    )


agent = Agent(
    "openai:gpt-4o",
    output_type=ProductResult,
    instructions=(
        "You are a product search assistant. Use the search_products tool to find "
        "products matching the user's query, then return the best match as a structured "
        "result with an appropriate confidence score."
    ),
)


@agent.tool_plain
def search_products(query: str) -> str:
    """Search the product database for items matching a query.

    Args:
        query: A search term or phrase describing the desired product.

    Returns:
        A formatted string listing matching products and their prices,
        or a message indicating no matches were found.
    """
    query_lower = query.lower()
    matches: list[str] = []

    for name, info in PRODUCT_DB.items():
        if any(word in name for word in query_lower.split()):
            matches.append(f"{name}: ${info['price']:.2f}")

    if matches:
        return "Found products:\n" + "\n".join(matches)
    return "No products found matching the query."


async def main() -> None:
    """Run the product search agent with a sample query."""
    result = await agent.run("I need a good keyboard for programming")
    print(result.output)  # noqa: T201


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
