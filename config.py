from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str
    bot_username: str = ""

    # Trigger
    trigger_phrase: str = "сильвер"

    # Context
    context_ttl_hours: int = 6
    history_window: int = 30

    # Timezone (IANA name)
    timezone: str = "Europe/Moscow"

    # Model
    model_path: Path = BASE_DIR / "models" / "Qwen3.5-9B-Q6_K.gguf"
    n_gpu_layers: int = -1
    n_ctx: int = 32768
    max_tokens: int = 2048
    temperature: float = 0.5
    top_p: float = 0.9

    # Storage (runtime data dir; Python package is storage/)
    data_dir: Path = BASE_DIR / "data"

    @property
    def messages_dir(self) -> Path:
        return self.data_dir / "messages"

    @property
    def context_file(self) -> Path:
        return self.data_dir / "context.json"

    @property
    def memory_file(self) -> Path:
        return self.data_dir / "memory.json"

    @property
    def summaries_dir(self) -> Path:
        return self.data_dir / "summaries"

    @property
    def bot_username_lower(self) -> str:
        return self.bot_username.lower().lstrip("@")


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
