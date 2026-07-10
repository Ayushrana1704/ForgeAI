from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "ForgeAI"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Security
    SECRET_KEY: str = "dev-insecure-secret-key-replace-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://forgeai:forgeai@localhost:5432/forgeai"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # LLM
    # Provider name: openai | lmstudio | ollama | vllm | azure
    LLM_PROVIDER: str = "openai"
    # Override the SDK's default base URL (required for local providers and Azure)
    LLM_BASE_URL: str | None = None
    # API key; None -> falls back to the OPENAI_API_KEY env var (OpenAI SDK default)
    LLM_API_KEY: str | None = None
    # Default model sent to the provider when the caller does not specify one
    LLM_MODEL: str = "gpt-4o-mini"
    # Per-request timeout in seconds passed to the OpenAI SDK
    LLM_TIMEOUT: float = 600.0
    # Azure-only: REST API version (ignored for non-Azure providers)
    LLM_AZURE_API_VERSION: str = "2024-08-01-preview"

    # Artifact storage
    ARTIFACT_STORAGE_PATH: str = "./generated"  # Base dir for on-disk artifact writes

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalise_db_url(cls, v: str) -> str:
        if v.startswith("postgresql://") and "asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
