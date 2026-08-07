"""Object storage for document bytes (tech rec §8).

Postgres holds metadata and references; S3 holds the bytes. Three artifact
classes are kept apart because they have different lifecycles: ``raw`` is
immutable evidence, ``normalized`` is reproducible from raw by a known parser
version, and ``derived`` is regenerable output.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic_settings import BaseSettings, SettingsConfigDict

from econiq_ingestion.errors import StorageError


class Artifact(StrEnum):
    RAW = "raw"
    NORMALIZED = "normalized"
    DERIVED = "derived"


@dataclass(frozen=True, slots=True)
class StoredObject:
    uri: str
    bucket: str
    key: str
    size_bytes: int


@runtime_checkable
class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


def object_key(artifact: Artifact, content_hash: str, *, extension: str = "") -> str:
    """Content-addressed key with a two-level prefix.

    Addressing by content hash makes re-ingesting the same bytes a no-op, and
    the prefix keeps a single flat listing from becoming unusable at volume.
    """
    return f"{artifact.value}/{content_hash[:2]}/{content_hash[2:4]}/{content_hash}{extension}"


class InMemoryObjectStore:
    """Test double. Same interface, no network."""

    def __init__(self, bucket: str = "econiq-documents") -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        self.objects[key] = data
        self.content_types[key] = content_type
        return StoredObject(
            uri=f"s3://{self.bucket}/{key}", bucket=self.bucket, key=key, size_bytes=len(data)
        )

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError as exc:
            raise StorageError(f"no object at {key!r}") from exc

    def exists(self, key: str) -> bool:
        return key in self.objects


class S3Settings(BaseSettings):
    """S3/MinIO configuration (``ECONIQ_S3_*``)."""

    model_config = SettingsConfigDict(env_prefix="ECONIQ_S3_", env_file=".env", extra="ignore")

    bucket: str = "econiq-documents"
    endpoint_url: str | None = None
    region_name: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None


class S3ObjectStore:
    """S3 in AWS, MinIO locally — the same client either way."""

    def __init__(self, settings: S3Settings | None = None, client: Any | None = None) -> None:
        self.settings = settings or S3Settings()
        self.bucket = self.settings.bucket
        self._client = client or self._build_client()

    def _build_client(self) -> Any:
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=self.settings.endpoint_url,
            region_name=self.settings.region_name,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.secret_access_key,
        )

    def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return StoredObject(
            uri=f"s3://{self.bucket}/{key}", bucket=self.bucket, key=key, size_bytes=len(data)
        )

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # botocore raises a client-specific error type
            raise StorageError(f"could not read s3://{self.bucket}/{key}") from exc
        body: bytes = response["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return False
        return True
