"""Encrypted-at-rest dataset storage (§5, KVKK).

Uploaded files may contain survey respondent identifiers, so §5 requires they
be encrypted at rest and deletable on request. Bytes are encrypted with Fernet
(AES-128-CBC + HMAC) before touching the disk and decrypted only in memory when
an analysis runs.

The local filesystem stands in for Cloudflare R2 (§7). The interface here —
`save`, `load`, `delete` — is what an R2 backend would implement, so swapping
it is a single-module change.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


class StorageError(RuntimeError):
    pass


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


_EPHEMERAL_KEY: Optional[bytes] = None


def storage_root() -> Path:
    root = Path(settings.storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save(dataset_id: str, filename: str, data: bytes) -> str:
    """Encrypt and write. Returns the storage path recorded on `Dataset`."""
    suffix = Path(filename).suffix.lower()
    target = storage_root() / f"{dataset_id}{suffix}.enc"
    target.write_bytes(_fernet().encrypt(data))
    return str(target)


def load(storage_path: str) -> bytes:
    """Decrypt and return the original bytes."""
    path = Path(storage_path)
    if not path.exists():
        raise StorageError(f"Veri dosyası bulunamadı: {storage_path}")
    try:
        return _fernet().decrypt(path.read_bytes())
    except InvalidToken as exc:
        raise StorageError(
            "Veri dosyası çözülemedi. Şifreleme anahtarı değişmiş olabilir."
        ) from exc


def delete(storage_path: str) -> bool:
    """§5: the data-deletion endpoint's primitive. Idempotent."""
    path = Path(storage_path)
    if path.exists():
        path.unlink()
        return True
    return False


def save_artifact(name: str, data: bytes) -> str:
    """Write a generated report artifact (docx/pdf).

    Reports contain only aggregate results — no respondent-level data — so they
    are stored unencrypted and can be served directly for download.
    """
    target = storage_root() / "reports"
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    path.write_bytes(data)
    return str(path)
