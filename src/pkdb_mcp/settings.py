"""Runtime configuration."""

from functools import lru_cache
from pathlib import Path
from typing import cast

from pydantic import AnyHttpUrl, Field, PositiveFloat, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for the MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="PKDB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_base_url: AnyHttpUrl = cast(AnyHttpUrl, "https://pk-db.com/api/v1")
    openapi_url: AnyHttpUrl = cast(AnyHttpUrl, "https://pk-db.com/api/v1/swagger.json")
    api_token: str | None = Field(default=None)
    use_fallback_spec: bool = Field(default=True)
    fallback_spec_path: Path = Field(
        default_factory=lambda: Path(__file__).parent / "specs" / "pkdb_swagger_fallback.json"
    )
    http_timeout_seconds: PositiveFloat = Field(default=30.0)
    proxy: str | None = Field(default=None)
    mcp_server_name: str = Field(default="pkdb-mcp")
    mcp_transport: str = Field(default="stdio")
    user_agent: str = Field(default="pkdb-mcp/0.1.0")

    @field_validator("mcp_transport")
    @classmethod
    def validate_transport(cls, value: str) -> str:
        allowed = {"stdio", "sse", "streamable-http"}
        if value not in allowed:
            msg = f"Unsupported MCP transport {value!r}; expected one of {sorted(allowed)}."
            raise ValueError(msg)
        return value

    @property
    def api_base_url_str(self) -> str:
        """Return the API base URL without a trailing slash."""

        return str(self.api_base_url).rstrip("/")

    @property
    def openapi_url_str(self) -> str:
        """Return the OpenAPI URL as a string."""

        return str(self.openapi_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once for the process."""

    return Settings()
