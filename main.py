from settings import settings


def main() -> None:
    key_preview = settings.openrouter_api_key[:4] + "..."
    print(f"OpenRouter API key loaded: {key_preview}")


if __name__ == "__main__":
    main()
