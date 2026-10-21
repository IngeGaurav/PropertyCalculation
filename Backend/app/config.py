"""Runtime configuration, read once from environment variables."""
import os
from dataclasses import dataclass
from typing import List, Optional


def _csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Comma-separated list of allowed browser origins. "*" allows any origin.
    cors_origins: List[str]
    # If set, every calculation request must send this value in `X-API-Key`.
    api_key: Optional[str]
    # Hard limit (seconds) for one calculation before the API answers 504.
    calc_timeout_seconds: float
    # Upper bound on components per request. 0 = unlimited (the default).
    max_components: int  # 0 means no limit
    log_level: str


def load_settings() -> Settings:
    return Settings(
        cors_origins=_csv(os.getenv("CORS_ORIGINS", "*")),
        api_key=os.getenv("API_KEY") or None,
        calc_timeout_seconds=float(os.getenv("CALC_TIMEOUT_SECONDS", "30")),
        max_components=int(os.getenv("MAX_COMPONENTS", "0")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


settings = load_settings()
