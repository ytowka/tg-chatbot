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
    trigger_phrase: str = "Цветочный лох"

    # Random reply: вероятность ответа на любое сообщение (даже без триггера)
    random_reply_chance: float = 0.03

    # Context
    context_ttl_hours: int = 6
    history_window: int = 15

    # Timezone (IANA name)
    timezone: str = "Europe/Moscow"

    # LLM Backend (HTTP → llama-server на ноуте через SSH tunnel, или облако)
    llm_mode: str = "local"
    llm_base_url: str = "http://127.0.0.1:8081/v1"
    llm_model: str = "qwen3.5-9b"
    llm_api_key: str = "not-needed"
    llm_request_timeout: int = 120

    # Generation params (передаются в каждом запросе к LLM)
    max_tokens: int = 2048
    temperature: float = 0.4
    top_p: float = 0.9
    repeat_penalty: float = 1.15

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
    def features_file(self) -> Path:
        return self.data_dir / "features.json"

    @property
    def bot_username_lower(self) -> str:
        return self.bot_username.lower().lstrip("@")


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
