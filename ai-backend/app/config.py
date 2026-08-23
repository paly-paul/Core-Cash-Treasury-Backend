from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    mongodb_uri: str
    mongodb_db_name: str
    anthropic_api_key: str
    aws_region: str

    class Config:
        env_file = ".env"


settings = Settings()
