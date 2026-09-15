from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_report_bitrix_webhook: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    agent_report_dept_ids: str = "60,61,62,63,65,66,67,68,41,43,45,46,52,54"
    agent_report_messenger_user_ids: str = "1,32,2311,2319"
    agent_report_tz: str = "Asia/Dubai"
    agent_report_cron_hour: int = 18
    agent_report_cron_minute: int = 0
    agent_report_owner_data_entity_type_id: int = 1042

    database_url: str = "sqlite+pysqlite:///./agent_reports.db"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./storage/reports"

    def dept_id_list(self) -> list[int]:
        return [int(x.strip()) for x in self.agent_report_dept_ids.split(",") if x.strip()]

    def messenger_user_id_list(self) -> list[int]:
        return [int(x.strip()) for x in self.agent_report_messenger_user_ids.split(",") if x.strip()]

    def webhook_base(self) -> str:
        return (self.agent_report_bitrix_webhook or "").rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
