"""Encrypted-at-rest dataset storage (§5 KVKK, §7).

Two backends behind one interface:

- **Local filesystem** — the development default. A container filesystem does
  not survive a redeploy, so this is not viable in production and
  `validate_production_settings` refuses to start there.
- **Cloudflare R2** (§7) — S3-compatible, reached with boto3. Selected
  automatically as soon as R2 credentials are configured.

Encryption lives *above* the backend, in this module's `save`/`load`, so both
backends carry the identical §5 guarantee: bytes are Fernet-encrypted
(AES-128-CBC + HMAC) before they leave this process and decrypted only in
memory. R2's own server-side encryption is a second layer, not a substitute —
delegating to it would mean Cloudflare holds a key that can read respondent
data, which is exactly what §5 is about.

Generated reports are the exception and are stored unencrypted: they contain
only aggregate results, never respondent-level rows, and the download endpoint
already enforces ownership.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional, Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

#: Key prefixes, so one bucket can hold both without collision.
DATASET_PREFIX = "datasets"
REPORT_PREFIX = "reports"


class StorageError(RuntimeError):
    pass


class ObjectNotFound(StorageError):
    """The key does not exist in the backing store."""


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

def validate_encryption_key() -> None:
    """Fail fast on a malformed key.

    Without this the first upload dies with an opaque 500 from deep inside
    cryptography; a key is either right at boot or the deployment is broken.
    """
    key = settings.storage_encryption_key
    if not key:
        return
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:  # noqa: BLE001 — re-raised with an actionable message
        raise StorageError(
            "STORAGE_ENCRYPTION_KEY geçerli bir Fernet anahtarı değil. "
            "Şu komutla üretin: python -c \"from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


_EPHEMERAL_KEY: Optional[bytes] = None


def _fernet() -> Fernet:
    key = settings.storage_encryption_key
    if not key:
        # Development convenience only. Without a configured key, files written
        # by one process cannot be read by the next.
        global _EPHEMERAL_KEY
        if _EPHEMERAL_KEY is None:
            _EPHEMERAL_KEY = Fernet.generate_key()
            logger.warning(
                "STORAGE_ENCRYPTION_KEY is not set; using an ephemeral key. "
                "Stored datasets will be unreadable after a restart."
            )
        return Fernet(_EPHEMERAL_KEY)
    return Fernet(key.encode() if isinstance(key, str) else key)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class StorageBackend(Protocol):
    """What a place to put bytes has to do. Deliberately tiny."""

    name: str

    def put(self, key: str, data: bytes) -> str: ...
    def get(self, key: str) -> bytes: ...
    def remove(self, key: str) -> bool: ...


class LocalFilesystemBackend:
    """Development backend. Not durable across a container redeploy."""

    name = "local"

    def _path(self, key: str) -> Path:
        # Migration shim: rows written before R2 existed hold an absolute
        # filesystem path rather than a key. Honour those so an existing
        # database keeps working; new writes always use keys.
        candidate = Path(key)
        if candidate.is_absolute():
            return candidate
        return storage_root() / key

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise ObjectNotFound(f"Veri dosyası bulunamadı: {key}")
        return path.read_bytes()

    def remove(self, key: str) -> bool:
        path = self._path(key)
        if path.exists():
            path.unlink()
            return True
        return False


class R2Backend:
    """Cloudflare R2 (§7), reached over the S3 API.

    R2 charges no egress, which is why §7 picks it over S3 — reports and
    datasets are read back far more often than written.
    """

    name = "r2"

    def __init__(self) -> None:
        self._bucket = settings.r2_bucket
        self._client = None
        self._lock = threading.Lock()

    def _s3(self):
        # boto3 clients are thread-safe once built, but building one is slow,
        # so it is created once and shared.
        if self._client is None:
            with self._lock:
                if self._client is None:
                    try:
                        import boto3
                        from botocore.config import Config
                    except ImportError as exc:  # pragma: no cover — declared dep
                        raise StorageError(
                            "R2 depolama için boto3 kurulu olmalıdır."
                        ) from exc
                    self._client = boto3.client(
                        "s3",
                        endpoint_url=settings.resolved_r2_endpoint,
                        aws_access_key_id=settings.r2_access_key_id,
                        aws_secret_access_key=settings.r2_secret_access_key,
                        # R2 ignores regions but the SDK insists on one.
                        region_name="auto",
                        config=Config(
                            signature_version="s3v4",
                            retries={"max_attempts": 3, "mode": "standard"},
                        ),
                    )
        return self._client

    def put(self, key: str, data: bytes) -> str:
        try:
            self._s3().put_object(Bucket=self._bucket, Key=key, Body=data)
        except Exception as exc:  # noqa: BLE001 — surfaced as a Turkish message
            raise StorageError(f"Dosya depolama alanına yazılamadı: {exc}") from exc
        return key

    def get(self, key: str) -> bytes:
        client = self._s3()
        try:
            response = client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except client.exceptions.NoSuchKey as exc:
            raise ObjectNotFound(f"Veri dosyası bulunamadı: {key}") from exc
        except Exception as exc:  # noqa: BLE001
            # botocore raises ClientError with a 404 code rather than NoSuchKey
            # on some operations, so check the code before giving up.
            if _is_missing_key(exc):
                raise ObjectNotFound(f"Veri dosyası bulunamadı: {key}") from exc
            raise StorageError(f"Dosya depolama alanından okunamadı: {exc}") from exc

    def remove(self, key: str) -> bool:
        """§5's deletion primitive. Idempotent: S3 delete succeeds either way,
        so existence is checked first to report honestly."""
        client = self._s3()
        try:
            client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            if _is_missing_key(exc):
                return False
            raise StorageError(f"Dosya durumu okunamadı: {exc}") from exc

        try:
            client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Dosya silinemedi: {exc}") from exc
        return True


def _is_missing_key(exc: Exception) -> bool:
    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    return str(code) in ("404", "NoSuchKey", "NotFound")


_backend: Optional[StorageBackend] = None
_backend_lock = threading.Lock()


def get_backend() -> StorageBackend:
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = R2Backend() if settings.r2_configured else LocalFilesystemBackend()
                logger.info("Storage backend: %s", _backend.name)
    return _backend


def reset_backend() -> None:
    """Drop the cached backend. Used by tests that change configuration."""
    global _backend
    with _backend_lock:
        _backend = None


def storage_root() -> Path:
    root = Path(settings.storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# The interface every caller uses. Unchanged by the backend split.
# ---------------------------------------------------------------------------

def save(dataset_id: str, filename: str, data: bytes) -> str:
    """Encrypt and store. Returns the key recorded on `Dataset.storage_path`."""
    suffix = Path(filename).suffix.lower()
    key = f"{DATASET_PREFIX}/{dataset_id}{suffix}.enc"
    return get_backend().put(key, _fernet().encrypt(data))


def load(storage_path: str) -> bytes:
    """Fetch and decrypt the original bytes."""
    raw = get_backend().get(storage_path)
    try:
        return _fernet().decrypt(raw)
    except InvalidToken as exc:
        raise StorageError(
            "Veri dosyası çözülemedi. Şifreleme anahtarı değişmiş olabilir."
        ) from exc


def delete(storage_path: str) -> bool:
    """§5: the data-deletion endpoint's primitive. Idempotent."""
    return get_backend().remove(storage_path)


def save_artifact(name: str, data: bytes) -> str:
    """Store a generated report (docx/pdf).

    Reports hold only aggregate results — no respondent-level data — so they
    are stored unencrypted and served through the ownership-checked download
    endpoint.
    """
    return get_backend().put(f"{REPORT_PREFIX}/{name}", data)


def load_artifact(key: str) -> bytes:
    """Read a stored report back.

    Reports are streamed through the API rather than served from a path,
    because with R2 there is no local path to serve — and streaming keeps the
    ownership check in one place instead of handing out presigned URLs that
    bypass it.
    """
    return get_backend().get(key)
