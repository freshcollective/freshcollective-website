from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    frontend_origin: str = "http://localhost:3000"
    app_env: str = "development"

    # Stripe — set both values in .env before accepting real payments.
    # Leave blank/unset in development to disable Stripe endpoints gracefully.
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)


settings = Settings()
