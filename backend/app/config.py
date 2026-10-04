from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg2://attendance:attendance@localhost:5432/attendance"
    SECRET_KEY: str = "dev-only-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    QR_TOKEN_SECONDS: int = 30        # a QR code is useless this long after the teacher's screen showed it
    MAX_GPS_ACCURACY_M: int = 100     # reject scans whose GPS fix is worse than this (indoor/no-signal)
    FACE_MODEL: str = "buffalo_sc"    # small InsightFace pack (~15 MB). "buffalo_l" is more accurate but ~280 MB
    FACE_MODEL_DIR: str = "/models"
    FACE_MATCH_THRESHOLD: float = 0.40   # cosine similarity needed to count as the same person
    FACE_MIN_DET_SCORE: float = 0.50     # ignore detections the model is unsure about
    FACE_MIN_SIZE_PX: int = 80           # face must be at least this wide in the photo
    MAX_UPLOAD_BYTES: int = 5_000_000

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings() 