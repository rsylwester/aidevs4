import logging

from settings import settings

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    key_preview = settings.openrouter_api_key[:4] + "..."
    logger.info("OpenRouter API key loaded: %s", key_preview)


if __name__ == "__main__":
    main()
