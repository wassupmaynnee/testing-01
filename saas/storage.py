"""
Object storage — Cloudflare R2 (S3-compatible, via boto3) when configured by
ENV, else the local ./data volume.

Single, clearly-marked integration point: call sites (`store_clip`, `resolve`)
never change regardless of backend. Credentials are read from environment only
(see saas/config.py R2_* settings) and boto3 is imported lazily so a deployment
without R2 never loads it.
"""
from __future__ import annotations

from .config import get_settings

R2_SCHEME = "r2://"


def r2_enabled() -> bool:
    return get_settings().r2_enabled


def _client():
    import boto3  # noqa: PLC0415  (lazy: only when R2 is configured)

    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.r2_endpoint,
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        region_name="auto",
    )


def store_clip(local_path: str, key: str) -> str:
    """Persist a rendered clip and return the reference stored on the Clip row.

    * R2 configured -> upload and return "r2://<key>".
    * otherwise     -> return the local path unchanged.

    The local file always remains on disk so the clip is immediately servable
    right after render even when R2 is the system of record.
    """
    if not r2_enabled():
        return local_path
    s = get_settings()
    _client().upload_file(local_path, s.r2_bucket, key, ExtraArgs={"ContentType": "video/mp4"})
    return f"{R2_SCHEME}{key}"


def is_r2_ref(ref: str) -> bool:
    return ref.startswith(R2_SCHEME)


def presigned_url(ref: str, expires: int = 3600) -> str:
    """Presigned GET URL for an r2://<key> reference."""
    s = get_settings()
    key = ref[len(R2_SCHEME):]
    return _client().generate_presigned_url(
        "get_object", Params={"Bucket": s.r2_bucket, "Key": key}, ExpiresIn=expires
    )
