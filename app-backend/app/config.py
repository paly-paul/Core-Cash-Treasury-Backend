from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    mongodb_uri: str
    mongodb_db_name: str
    sqs_queue_url: str
    aws_region: str
    anthropic_api_key: str
    ai_backend_url: str = "http://localhost:8001"

    # JWT settings for custom auth
    jwt_private_key: str
    jwt_public_key: str
    jwt_algorithm: str = "RS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    class Config:
        env_file = ".env"


settings = Settings()
