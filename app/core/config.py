from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    # Project Info
    PROJECT_NAME: str = "Lirana Gallery Bot"
    PROJECT_VERSION: str = "1.0.0"

    # Bale Bot Settings
    BALE_BOT_TOKEN: str
    BALE_API_URL: str = "https://tapi.bale.ai/bot"

    # Admin Settings
    ADMIN_IDS: List[int] = []
    ADMIN_BALE_ID: Optional[str] = None  # اضافه شد تا ارور pydantic برطرف شود

    # Database Settings (PostgreSQL)
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_SERVER: str
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str
    # از آنجا که این آدرس داخل فایل .env شما وجود دارد، آن را به عنوان یک متغیر مستقیم تعریف کردیم
    DATABASE_URL: str

    # Redis Settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"

    # OpenAI Settings
    OPENAI_API_KEY: str
    AI_MODEL: str = "gpt-4o-mini"

    # Bahoosh Sync API (برای فاز ۲)
    BAHOOSH_API_KEY: str = ""
    BAHOOSH_STORE_URL: str = ""

    # Backup Settings
    BACKUP_ENCRYPTION_KEY: str

    # ----- تغییرات اصلی برای Pydantic نسخه ۲ -----
    # به جای class Config از SettingsConfigDict استفاده میکنیم
    # و با extra="ignore" به برنامه میگوییم متغیرهای اضافه در .env را نادیده بگیرد تا ارور ندهد
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


# نمونه‌سازی از تنظیمات برای استفاده در کل پروژه
settings = Settings()
