from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str
    aidevs_key: str
    aidevs_verify_address: str
    aidevs_hub_url: str

    # Langfuse
    langfuse_public_key: str = "pk-lf-local"
    langfuse_secret_key: str = "sk-lf-local"
    langfuse_base_url: str = "http://localhost:3000"


settings: Settings = Settings.model_validate({})
