from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    telegram_api_id: int
    telegram_api_hash: str
    
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    
    gemini_api_key: str = ""
    
    # Google Drive (optional — export works without these)
    google_drive_credentials_json: str = ""    # abs path to service-account .json
    google_drive_folder_id: str = ""           # target Drive folder ID

    # Local export + download directories
    export_dir: str = "exports"
    download_dir: str = "downloads"

    cors_origins: list[str] = ["http://localhost:3000"]
    
    enable_whisper: bool = False
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
