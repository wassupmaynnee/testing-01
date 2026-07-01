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
    app_env: str = "development"  # "production" in deploy; gates secure-cookie + Sentry env

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

    # --- Stripe billing ---
    # Lazy-loaded only when stripe_secret_key is set (frozen contract). The three
    # paid tiers map to Stripe Price IDs; blank price IDs fall back to inline
    # price_data built from the frozen catalog so checkout still works in test mode.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""       # annual Price IDs (blank -> inline price_data)
    stripe_price_pro: str = ""
    stripe_price_scale: str = ""
    # Optional MONTHLY Price IDs. Blank -> inline monthly price_data is built from
    # the frozen catalog (see saas/billing_core.py pricing_table()).
    stripe_price_starter_monthly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_scale_monthly: str = ""
    # Where Stripe returns the buyer after hosted Checkout / Portal. Default to
    # the dashboard so a completed purchase lands the user straight in the app.
    billing_success_url: str = ""  # default derived from app_base_url below
    billing_cancel_url: str = ""

    # --- Observability ---
    sentry_dsn: str = ""              # blank = monitoring disabled (no-op)
    sentry_traces_sample_rate: float = 0.1

    # --- Privacy-friendly analytics (Plausible). Blank = no script injected. ---
    plausible_domain: str = ""

    # --- OAuth publishing (YouTube). OAuth 2.0 ONLY; uploads are FORCED private.
    # The Google client libs are lazy-loaded only when a client id is configured
    # (see saas/publish_core.py), so the app boots fine with these blank. ---
    youtube_oauth_client_id: str = ""
    youtube_oauth_client_secret: str = ""
    youtube_oauth_redirect_uri: str = "http://localhost:8011/api/publish/youtube/callback"

    # --- Clip pipeline: how many clips to cut from one source video. Reuses the
    # FROZEN engagement scoring to pick the top-N non-overlapping windows. Clamped
    # to clips_per_video_max so one URL can't spawn an unbounded render job. ---
    clips_per_video: int = 3
    clips_per_video_max: int = 10

    # --- Object storage (Cloudflare R2, S3-compatible via boto3). ENV-ONLY, never
    # hard-coded. If any of bucket / access key / secret / (endpoint or account id)
    # is blank, storage falls back to the local ./data volume and R2 stays a
    # documented seam (see saas/storage.py). ---
    r2_account_id: str = ""
    r2_bucket: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_endpoint_url: str = ""  # derived from account id below when blank

    @property
    def r2_endpoint(self) -> str:
        if self.r2_endpoint_url:
            return self.r2_endpoint_url
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com" if self.r2_account_id else ""

    @property
    def r2_enabled(self) -> bool:
        return bool(
            self.r2_bucket and self.r2_access_key_id
            and self.r2_secret_access_key and self.r2_endpoint
        )

    def clips_per_video_clamped(self) -> int:
        return max(1, min(self.clips_per_video, self.clips_per_video_max))

    @property
    def success_url(self) -> str:
        return self.billing_success_url or f"{self.app_base_url}/dashboard?checkout=success"

    @property
    def cancel_url(self) -> str:
        return self.billing_cancel_url or f"{self.app_base_url}/dashboard?checkout=cancelled"

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
