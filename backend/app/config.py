from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_publishable_key: str = ""
    supabase_database_url: str = ""
    neo4j_uri: str = ""
    neo4j_username: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    app_env: str = "development"
    auth_enabled: bool = False
    admin_user_ids: str = ""
    # When true, every API call needs a signed-in session (password login); the demo header and the
    # local no-login developer access are switched off.
    login_required: bool = False

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / '.env'),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
