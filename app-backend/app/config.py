from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    mongodb_uri: str
    mongodb_db_name: str
    sqs_queue_url: str
    aws_region: str
    cognito_region: str
    cognito_user_pool_id: str
    cognito_app_client_id: str
    anthropic_api_key: str

    class Config:
        env_file = ".env"


settings = Settings()
