from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://attendance:attendance@localhost:5432/attendance"
    SECRET_KEY: str = "dev-only-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    QR_TOKEN_SECONDS: int = 30        # a QR code is useless this long after the teacher's screen showed it
    MAX_GPS_ACCURACY_M: int = 100     # reject scans whose GPS fix is worse than this (indoor/no-signal)

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
