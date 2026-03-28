from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _to_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default

@dataclass(frozen=True)
class Settings:
    app_env: str
    host: str
    port: int
    database_url: str
    http_user_agent: str
    openinsider_poll_seconds: int
    due_snapshot_poll_seconds: int
    quote_retry_seconds: int
    max_discovery_rows: int
    twelvedata_api_key: str | None
    fmp_api_key: str | None
    project_root: Path
    data_dir: Path
    cache_dir: Path


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    _load_env_file(project_root / ".env")

    data_dir_raw = os.getenv("DATA_DIR", "./data")
    data_dir = Path(data_dir_raw)
    if not data_dir.is_absolute():
        data_dir = project_root / data_dir
    cache_dir = data_dir / "cache"
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/insider_tracker.db")

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        host=os.getenv("HOST", "127.0.0.1"),
        port=_to_int("PORT", 8000),
        database_url=database_url,
        http_user_agent=os.getenv(
            "HTTP_USER_AGENT",
            "InsiderTradingTracker/0.1 your-email@example.com",
        ),
        openinsider_poll_seconds=_to_int("OPENINSIDER_POLL_SECONDS", 60),
        due_snapshot_poll_seconds=_to_int("DUE_SNAPSHOT_POLL_SECONDS", 30),
        quote_retry_seconds=_to_int("QUOTE_RETRY_SECONDS", 300),
        max_discovery_rows=_to_int("MAX_DISCOVERY_ROWS", 100),
        twelvedata_api_key=os.getenv("TWELVEDATA_API_KEY") or None,
        fmp_api_key=os.getenv("FMP_API_KEY") or None,
        project_root=project_root,
        data_dir=data_dir,
        cache_dir=cache_dir,
    )
