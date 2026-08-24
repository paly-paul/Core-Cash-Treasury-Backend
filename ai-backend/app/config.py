from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    mongodb_uri: str
    mongodb_db_name: str
    anthropic_api_key: str
    aws_region: str
    cognito_region: str
    cognito_user_pool_id: str
    cognito_app_client_id: str
    ai_backend_url: str = "http://localhost:8001"

    class Config:
        env_file = ".env"


settings = Settings()
