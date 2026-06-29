"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Clippify"
    app_secret: str = "dev-insecure-secret-change-me"
    app_base_url: str = "http://localhost:8011"
    app_port: int = 8011

    database_url: str = "postgresql+psycopg://clippify:clippify@db:5432/clippify"
    redis_url: str = "redis://redis:6379/0"

    # Frozen contract: Windows absolute paths by default; container overrides.
    ffmpeg_bin: str = r"C:\ffmpeg\bin\ffmpeg.exe"
    ffprobe_bin: str = r"C:\ffmpeg\bin\ffprobe.exe"

    video_codec: str = "x264"  # "nvenc" on GPU hosts
    asr_model: str = "tiny"
    asr_device: str = "cpu"
    yunet_model_url: str = (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx"
    )

    seed_user_email: str = "demo@clippify.dev"
    seed_user_password: str = "clippify-demo"
    seed_user_credits: int = 30

    # Deferred seams — blank in the walking skeleton.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    youtube_oauth_client_id: str = ""
    youtube_oauth_client_secret: str = ""

    @property
    def uploads_dir(self) -> Path:
        return DATA_DIR / "uploads"

    @property
    def clips_dir(self) -> Path:
        return DATA_DIR / "clips"

    @property
    def checkpoints_dir(self) -> Path:
        return DATA_DIR / "checkpoints"

    @property
    def models_dir(self) -> Path:
        return ROOT / "models"

    def ensure_dirs(self) -> None:
        for d in (self.uploads_dir, self.clips_dir, self.checkpoints_dir, self.models_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
