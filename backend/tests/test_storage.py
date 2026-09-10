"""Storage backend tests (§5 KVKK, §7).

The R2 cases run against `moto`, which implements real S3 semantics in-process
— errors, missing keys and all — rather than a hand-written stub that would
only ever confirm my own assumptions about the API. R2 is S3-compatible, so
this exercises the same calls the real service receives.

Not covered: real Cloudflare R2. No credentials exist in this environment, so
the network round trip itself is unverified.
"""

from __future__ import annotations

import io

import boto3
import pytest
from moto import mock_aws

from app import storage
from app.config import Settings, settings

BUCKET = "sigma-test-bucket"
#: moto intercepts botocore at the client layer, so an AWS-shaped endpoint is
#: what it can stand in for. Real deployments point this at R2.
MOTO_ENDPOINT = "https://s3.amazonaws.com"


@pytest.fixture(autouse=True)
def _reset_backend():
    storage.reset_backend()
    yield
    storage.reset_backend()


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "r2_bucket", None)
    monkeypatch.setattr(settings, "r2_access_key_id", None)
    monkeypatch.setattr(settings, "r2_secret_access_key", None)
    monkeypatch.setattr(settings, "r2_account_id", None)
    monkeypatch.setattr(settings, "r2_endpoint_url", None)
    storage.reset_backend()
    return storage


@pytest.fixture
def r2_storage(monkeypatch):
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(settings, "r2_access_key_id", "test-key")
        monkeypatch.setattr(settings, "r2_secret_access_key", "test-secret")
        monkeypatch.setattr(settings, "r2_bucket", BUCKET)
        monkeypatch.setattr(settings, "r2_endpoint_url", MOTO_ENDPOINT)
        storage.reset_backend()
        yield storage


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def test_local_backend_is_the_default(local_storage):
    assert local_storage.get_backend().name == "local"


def test_r2_is_selected_once_configured(r2_storage):
    assert r2_storage.get_backend().name == "r2"


def test_endpoint_is_derived_from_the_account_id():
    config = Settings(r2_account_id="abc123", _env_file=None)
    assert config.resolved_r2_endpoint == "https://abc123.r2.cloudflarestorage.com"


def test_an_explicit_endpoint_wins():
    config = Settings(r2_account_id="abc123",
                      r2_endpoint_url="https://minio.local:9000", _env_file=None)
    assert config.resolved_r2_endpoint == "https://minio.local:9000"


@pytest.mark.parametrize("partial", [
    {"r2_bucket": "sigma"},
    {"r2_access_key_id": "k", "r2_secret_access_key": "s"},
    {"r2_account_id": "abc", "r2_bucket": "sigma"},
])
def test_partial_r2_configuration_is_not_treated_as_configured(partial):
    """Half-configured R2 must not silently fall back to a filesystem that
    loses data on redeploy — the production guardrail catches it instead."""
    config = Settings(_env_file=None, **partial)
    assert config.r2_configured is False
    assert config.r2_partially_configured is True


# ---------------------------------------------------------------------------
# Behaviour that must hold identically on both backends
# ---------------------------------------------------------------------------

@pytest.fixture(params=["local", "r2"])
def any_backend(request, local_storage, r2_storage):
    return local_storage if request.param == "local" else r2_storage


def test_roundtrip(any_backend):
    key = any_backend.save("ds-1", "veri.csv", "ölçüm,puan\n1,72".encode())
    assert any_backend.load(key) == "ölçüm,puan\n1,72".encode()


def test_stored_bytes_are_ciphertext(any_backend):
    """§5 KVKK: respondent data must not be readable at rest, on any backend."""
    plaintext = "katilimci_no,cinsiyet\n1,Kadın".encode()
    key = any_backend.save("ds-2", "veri.csv", plaintext)

    raw = any_backend.get_backend().get(key)
    assert raw != plaintext
    assert b"Kad" not in raw
    assert b"katilimci_no" not in raw
    assert raw.startswith(b"gAAAA")  # Fernet token


def test_delete_is_idempotent(any_backend):
    key = any_backend.save("ds-3", "veri.csv", b"data")
    assert any_backend.delete(key) is True
    assert any_backend.delete(key) is False


def test_loading_a_missing_key_raises_object_not_found(any_backend):
    with pytest.raises(storage.ObjectNotFound):
        any_backend.load("datasets/does-not-exist.csv.enc")


def test_keys_are_namespaced_by_kind(any_backend):
    dataset_key = any_backend.save("ds-4", "veri.xlsx", b"x")
    artifact_key = any_backend.save_artifact("rapor.pdf", b"%PDF-")

    assert dataset_key.startswith("datasets/")
    assert dataset_key.endswith(".xlsx.enc")
    assert artifact_key.startswith("reports/")


def test_artifacts_are_stored_unencrypted(any_backend):
    """Reports hold only aggregates, and the download endpoint checks
    ownership — so they are readable at rest by design."""
    pdf = b"%PDF-1.7 rapor"
    key = any_backend.save_artifact("rapor.pdf", pdf)
    assert any_backend.get_backend().get(key) == pdf
    assert any_backend.load_artifact(key) == pdf


def test_a_wrong_encryption_key_is_reported_not_swallowed(any_backend, monkeypatch):
    from cryptography.fernet import Fernet

    key = any_backend.save("ds-5", "veri.csv", b"gizli")
    monkeypatch.setattr(settings, "storage_encryption_key",
                        Fernet.generate_key().decode())
    with pytest.raises(storage.StorageError) as excinfo:
        any_backend.load(key)
    assert "anahtar" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# Local-only behaviour
# ---------------------------------------------------------------------------

def test_absolute_paths_from_before_the_r2_migration_still_load(local_storage, tmp_path):
    """Rows written when storage_path held a filesystem path must keep working."""
    legacy = tmp_path / "legacy.csv.enc"
    legacy.write_bytes(local_storage._fernet().encrypt(b"eski veri"))
    assert local_storage.load(str(legacy)) == b"eski veri"


# ---------------------------------------------------------------------------
# The whole pipeline over R2
# ---------------------------------------------------------------------------

def test_full_flow_over_r2(r2_storage, tmp_path, monkeypatch):
    """Upload, analyse, report and download with R2 as the only store.

    This is the case the change exists for: nothing touches the container
    filesystem, so a redeploy cannot take the data with it.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models  # noqa: F401  — registers tables on Base.metadata
    from app.db import Base, get_db
    # Aliased: `import app.models` above rebinds the name `app` to the package.
    from app.main import app as fastapi_app

    from tests.conftest import FIXTURES

    monkeypatch.setattr(settings, "allow_insecure_header_auth", True)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    headers = {"X-User-Email": "r2@universite.edu.tr"}
    try:
        with TestClient(fastapi_app) as client:
            data = (FIXTURES / "ttest_independent.csv").read_bytes()
            dataset = client.post(
                "/api/datasets",
                files={"file": ("veri.csv", io.BytesIO(data), "text/csv")},
                headers=headers,
            ).json()

            client.patch(f"/api/datasets/{dataset['id']}/variables", headers=headers, json={
                "variables": [
                    {"column_name": "basari_puani", "measurement_level": "ratio"},
                    {"column_name": "yontem", "measurement_level": "nominal"},
                ]})

            analysis = client.post("/api/analyses", headers=headers, json={
                "dataset_id": dataset["id"],
                "dependent_variable": "basari_puani",
                "independent_variables": ["yontem"]}).json()
            assert analysis["analysis_type"] == "independent_t_test"
            assert analysis["raw_result"]["statistics"]["t"] == pytest.approx(
                7.197247, abs=1e-4)

            report = client.post(
                f"/api/analyses/{analysis['id']}/report?use_llm=false", headers=headers
            )
            assert report.status_code == 201, report.text

            download = client.get(
                f"/api/analyses/{analysis['id']}/report/download/docx", headers=headers)
            assert download.status_code == 200
            assert download.content.startswith(b"PK")
            assert "attachment" in download.headers["content-disposition"]

            # Everything really is in the bucket, and nothing on local disk.
            keys = [o["Key"] for o in boto3.client("s3").list_objects_v2(
                Bucket=BUCKET).get("Contents", [])]
            assert any(k.startswith("datasets/") for k in keys)
            assert any(k.startswith("reports/") for k in keys)
            assert not (tmp_path / "storage").exists()
    finally:
        fastapi_app.dependency_overrides.clear()


def test_a_report_row_pointing_at_a_deleted_object_raises_not_found(r2_storage):
    """The download endpoint turns this into a 404 rather than a 500."""
    key = r2_storage.save_artifact("kayip.docx", b"PK")
    assert r2_storage.load_artifact(key) == b"PK"

    boto3.client("s3").delete_object(Bucket=BUCKET, Key=key)

    with pytest.raises(storage.ObjectNotFound):
        r2_storage.load_artifact(key)
