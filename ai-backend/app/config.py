from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    mongodb_uri: str
    mongodb_db_name: str
    anthropic_api_key: str
    aws_region: str
    ai_backend_url: str = "http://localhost:8001"

    # JWT settings for custom auth validation
    jwt_public_key: str
    jwt_algorithm: str = "RS256"

    class Config:
        env_file = ".env"


settings = Settings()
