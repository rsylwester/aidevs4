"""S01E03 - proxy: intelligent logistics proxy with MCP tools."""

from __future__ import annotations

import logging
from pathlib import Path

from lib.logging import setup_logging

logger = logging.getLogger(__name__)

ARTIFACTS = Path(__file__).parent / ".artifacts"


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)

    import dotenv
    import ngrok  # pyright: ignore[reportMissingImports]
    import uvicorn

    dotenv.load_dotenv()
    listener = ngrok.forward(8000, authtoken_from_env=True)
    public_url = str(listener.url())
    logger.info("[bold cyan]Public URL: %s[/]", public_url)

    # Store URL for submission after server starts (in lifespan)
    import tasks.S01E03_proxy.proxy_server as srv

    srv.PUBLIC_URL = public_url

    uvicorn.run(
        "tasks.S01E03_proxy.proxy_server:app",
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    run()
