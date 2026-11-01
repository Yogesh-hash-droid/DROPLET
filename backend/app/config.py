import os
import ssl
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # P2 admin authentication (PUT /api/config, see app/security.py).
    # Empty/absent = configuration updates are REJECTED with HTTP 503 (fail
    # closed). Set only via environment / .env at deployment - never commit a
    # real key to source control, and never print or log this value.
    ADMIN_API_KEY: str | None = None

    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "root"
    MYSQL_DATABASE: str = "water_quality_db"
    MYSQL_SSL: bool = False
    MYSQL_SSL_CA: str | None = None
    DATABASE_URL: str | None = None

    MODEL_PATH: str = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "models", "water_potability_model.joblib")
    METRICS_PATH: str = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "models", "model_metrics.json")

    # Default Regulatory / Safety Thresholds (WHO / EPA guidelines)
    DEFAULT_PH_MIN: float = 6.5
    DEFAULT_PH_MAX: float = 8.5
    DEFAULT_TDS_MAX: float = 500.0          # ppm
    DEFAULT_TURBIDITY_MAX: float = 5.0      # NTU
    DEFAULT_TEMP_MIN: float = 10.0          # °C
    DEFAULT_TEMP_MAX: float = 35.0          # °C

    # Phase 10 (decision R-2 = B1): two-parameter screening score bands.
    # Used only to provision a missing system_config row; the database columns
    # (NOT NULL DEFAULT 70.0 / 40.0) are authoritative once the row exists.
    DEFAULT_STATUS_GOOD_MIN: float = 70.0   # GOOD if screening score >= this
    DEFAULT_STATUS_POOR_MAX: float = 40.0   # POOR if screening score < this

    # Device offline timeout in seconds (e.g., 30s without readings = OFFLINE)
    DEVICE_OFFLINE_THRESHOLD_SECONDS: int = 30

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), "..", ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        from urllib.parse import quote_plus
        encoded_pwd = quote_plus(self.MYSQL_PASSWORD)
        return f"mysql+pymysql://{self.MYSQL_USER}:{encoded_pwd}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    @property
    def sqlalchemy_connect_args(self) -> dict:
        """Return SQLAlchemy driver arguments, including verified MySQL TLS."""
        if self.DATABASE_URL and self.DATABASE_URL.startswith("sqlite"):
            return {"check_same_thread": False}
        if not self.MYSQL_SSL:
            return {}


        try:
            context = ssl.create_default_context(cafile=self.MYSQL_SSL_CA)
        except (OSError, ssl.SSLError) as exc:
            raise ValueError(
                f"Unable to load MYSQL_SSL_CA certificate: {self.MYSQL_SSL_CA}"
            ) from exc
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return {"ssl": context}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
