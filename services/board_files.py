"""Картинки доски в том же R2, что и картинки заданий."""
from __future__ import annotations

import asyncio
import os

import boto3
from botocore.config import Config


def client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def public_src(key: str) -> str:
    base = (os.getenv("R2_PUBLIC_URL") or "").rstrip("/")
    return f"{base}/{key}"


async def put_bytes(key: str, body: bytes, content_type: str) -> None:
    bucket = os.getenv("R2_BUCKET_NAME")
    s3 = client()
    await asyncio.to_thread(
        s3.put_object,
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl="max-age=31536000",
    )


async def delete_keys(keys: list[str]) -> None:
    if not keys:
        return
    bucket = os.getenv("R2_BUCKET_NAME")
    s3 = client()
    for key in keys:
        await asyncio.to_thread(s3.delete_object, Bucket=bucket, Key=key)
