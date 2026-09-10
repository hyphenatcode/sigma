"""§6 API tests — the full pipeline exercised over HTTP.

These run against SQLite rather than PostgreSQL so the suite needs no server.
The models use JSON-with-JSONB-variant columns precisely so that works; the
migration and the deployed app still target PostgreSQL (§7).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.conftest import FIXTURES

USER = {"X-User-Email": "arastirmaci@universite.edu.tr"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client authenticated through the development header.

    These tests are about the API's behaviour, not about authentication, so
    they take the X-User-Email path rather than minting Supabase tokens for
    every request — real token verification is covered in test_auth.py, and the
    Bearer path through the API is covered at the bottom of this file. The flag
    has to be set explicitly here, which is the point: it is off by default and
    production refuses to start with it on.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "allow_insecure_header_auth", True)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    from app.db import Base, get_db
    import app.models  # noqa: F401 — registers tables

    Base.metadata.create_all(engine)

    from app.main import app

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload(client: TestClient, filename: str) -> dict:
    data = (FIXTURES / filename).read_bytes()
    response = client.post(
        "/api/datasets",
        files={"file": (filename, io.BytesIO(data), "text/csv")},
        headers=USER,
    )
    assert response.status_code == 201, response.text
    return response.json()


def confirm(client: TestClient, dataset_id: str, variables: list[dict]) -> dict:
    response = client.patch(
        f"/api/datasets/{dataset_id}/variables",
        json={"variables": variables},
        headers=USER,
    )
    assert response.status_code == 200, response.text
    return response.json()


def grant_credits(client: TestClient, count: int) -> None:
    """Top up directly through the ledger — the purchase flow is not wired."""
    from app.api.credits import _grant_credits
    from app.db import get_db
    from app.models import User

    session = next(client.app.dependency_overrides[get_db]())
    user = session.query(User).filter(User.email == USER["X-User-Email"]).one()
    for index in range(count):
        _grant_credits(session, user, "single_analysis", f"test-{index}")


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_analysis_type_registry_is_exposed(client):
    payload = client.get("/api/analysis-types").json()
    keys = {item["key"] for item in payload["supported"]}
    assert "independent_t_test" in keys
    assert "one_way_anova" in keys
    # variants reachable only through §3.4 are not offered as choices
    assert "welch_t_test" not in keys
    unsupported = {item["key"] for item in payload["not_supported_in_v1"]}
    assert "repeated_measures_anova" in unsupported


# ---------------------------------------------------------------------------
# §3.1 / §3.2 — upload and variable confirmation
# ---------------------------------------------------------------------------

def test_upload_returns_detected_variables(client):
    payload = upload(client, "ttest_independent.csv")

    assert payload["row_count"] == 20
    assert payload["column_count"] == 3
    by_name = {v["column_name"]: v for v in payload["detection"]}
    assert by_name["yontem"]["detected_type"] == "categorical"
    assert by_name["yontem"]["distinct_value_count"] == 2
    assert by_name["basari_puani"]["detected_type"] == "numeric"
    assert by_name["basari_puani"]["sample_values"][:3] == [78, 85, 82]


def test_upload_requires_authentication(client):
    data = (FIXTURES / "ttest_independent.csv").read_bytes()
    response = client.post(
        "/api/datasets", files={"file": ("x.csv", io.BytesIO(data), "text/csv")}
    )
    assert response.status_code == 401


def test_upload_rejects_unsupported_extension(client):
    response = client.post(
        "/api/datasets",
        files={"file": ("data.sav", io.BytesIO(b"rubbish"), "application/octet-stream")},
        headers=USER,
    )
    assert response.status_code == 400
    # §9 puts SPSS .sav import out of v1 scope — the refusal must be explicit
    assert "csv" in response.json()["detail"].lower()


def test_uploaded_file_is_encrypted_at_rest(client, tmp_path):
    """§5 KVKK: the plaintext must not be readable on disk."""
    payload = upload(client, "ttest_independent.csv")

    from app.db import get_db
    from app.models import Dataset

    session = next(client.app.dependency_overrides[get_db]())
    dataset = session.get(Dataset, payload["id"])
    stored = Path(dataset.storage_path).read_bytes()

    assert b"basari_puani" not in stored
    assert b"Deney" not in stored
    assert stored.startswith(b"gAAAA")  # Fernet token prefix


def test_confirm_variables_overrides_detection(client):
    payload = upload(client, "ttest_independent.csv")
    updated = confirm(client, payload["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio",
         "role": "dependent"},
        {"column_name": "yontem", "measurement_level": "nominal", "role": "grouping"},
    ])
    by_name = {v["column_name"]: v for v in updated["variables"]}
    assert by_name["basari_puani"]["role"] == "dependent"
    assert by_name["yontem"]["measurement_level"] == "nominal"


def test_confirm_rejects_unknown_column(client):
    payload = upload(client, "ttest_independent.csv")
    response = client.patch(
        f"/api/datasets/{payload['id']}/variables",
        json={"variables": [{"column_name": "yok_boyle_sutun", "role": "dependent"}]},
        headers=USER,
    )
    assert response.status_code == 400


def test_dataset_is_scoped_to_its_owner(client):
    payload = upload(client, "ttest_independent.csv")
    response = client.get(
        f"/api/datasets/{payload['id']}", headers={"X-User-Email": "baskasi@edu.tr"}
    )
    assert response.status_code == 404


def test_delete_dataset_removes_the_stored_file(client):
    """§5 KVKK: the data-deletion endpoint."""
    payload = upload(client, "ttest_independent.csv")

    from app.db import get_db
    from app.models import Dataset

    session = next(client.app.dependency_overrides[get_db]())
    stored = Path(session.get(Dataset, payload["id"]).storage_path)
    assert stored.exists()

    assert client.delete(f"/api/datasets/{payload['id']}", headers=USER).status_code == 204
    assert not stored.exists()
    assert client.get(f"/api/datasets/{payload['id']}", headers=USER).status_code == 404


# ---------------------------------------------------------------------------
# §6 — analyses
# ---------------------------------------------------------------------------

def test_full_pipeline_upload_to_report(client):
    """Upload -> confirm -> analyse -> report, the flow the frontend drives."""
    dataset = upload(client, "ttest_independent.csv")
    confirm(client, dataset["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio", "role": "dependent"},
        {"column_name": "yontem", "measurement_level": "nominal", "role": "grouping"},
    ])

    response = client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"],
        "task": "comparison",
        "dependent_variable": "basari_puani",
        "independent_variables": ["yontem"],
    })
    assert response.status_code == 201, response.text
    analysis = response.json()

    assert analysis["analysis_type"] == "independent_t_test"
    assert analysis["recommended_analysis_type"] == "independent_t_test"
    assert analysis["status"] == "completed"
    assert analysis["raw_result"]["statistics"]["t"] == pytest.approx(7.197247, abs=1e-4)
    assert analysis["effect_size"]["band"] == "large"
    assert len(analysis["assumption_results"]) == 3

    fetched = client.get(f"/api/analyses/{analysis['id']}", headers=USER)
    assert fetched.status_code == 200
    assert fetched.json()["raw_result"]["p_value"] == pytest.approx(1.0678e-06, rel=1e-3)

    report = client.post(
        f"/api/analyses/{analysis['id']}/report?use_llm=false", headers=USER
    )
    assert report.status_code == 201, report.text
    body = report.json()

    assert "t(18) = 7.20" in body["interpretation_text_tr"]
    assert body["interpretation_source"] == "template"
    assert "Tablo 1" in body["apa_table_html"]
    assert body["docx_url"] and body["pdf_url"]

    for fmt, magic in (("docx", b"PK"), ("pdf", b"%PDF")):
        download = client.get(
            f"/api/analyses/{analysis['id']}/report/download/{fmt}", headers=USER
        )
        assert download.status_code == 200
        assert download.content.startswith(magic)


def test_analysis_reports_a_section_3_4_substitution(client):
    dataset = upload(client, "nonparametric_skewed.csv")
    confirm(client, dataset["id"], [
        {"column_name": "tepki_suresi", "measurement_level": "ratio", "role": "dependent"},
        {"column_name": "grup", "measurement_level": "nominal", "role": "grouping"},
    ])
    grant_credits(client, 1)

    analysis = client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"],
        "dependent_variable": "tepki_suresi",
        "independent_variables": ["grup"],
    }).json()

    assert analysis["recommended_analysis_type"] == "independent_t_test"
    assert analysis["analysis_type"] == "mann_whitney_u"
    assert analysis["substituted"] is True
    assert "Mann-Whitney" in analysis["substitution_reason_tr"]


def test_unsupported_combination_returns_422_with_turkish_reason(client):
    """§3.3: never a best-guess fallback."""
    dataset = upload(client, "ttest_independent.csv")
    confirm(client, dataset["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio"},
        {"column_name": "yontem", "measurement_level": "nominal"},
    ])

    response = client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"],
        "dependent_variable": "yontem",         # categorical DV
        "independent_variables": ["basari_puani"],  # continuous IV
    })
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "analysis_not_supported"
    assert "desteklenmiyor" in detail["detail"]


def test_pinned_analysis_type_that_contradicts_the_rules_is_refused(client):
    dataset = upload(client, "ttest_independent.csv")
    confirm(client, dataset["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio"},
        {"column_name": "yontem", "measurement_level": "nominal"},
    ])

    response = client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"],
        "analysis_type": "one_way_anova",  # two groups, so ANOVA is wrong
        "dependent_variable": "basari_puani",
        "independent_variables": ["yontem"],
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "analysis_type_mismatch"


def test_analysis_on_someone_elses_dataset_is_404(client):
    dataset = upload(client, "ttest_independent.csv")
    response = client.post(
        "/api/analyses",
        headers={"X-User-Email": "baskasi@edu.tr"},
        json={"dataset_id": dataset["id"], "dependent_variable": "basari_puani",
              "independent_variables": ["yontem"]},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# §3.10 — credits
# ---------------------------------------------------------------------------

def test_new_user_gets_one_free_trial_credit(client):
    payload = client.get("/api/credits", headers=USER).json()
    assert payload["credits_remaining"] == 1
    assert payload["entries"][0]["package_type"] == "free_trial"


def test_running_an_analysis_consumes_a_credit(client):
    dataset = upload(client, "ttest_independent.csv")
    confirm(client, dataset["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio"},
        {"column_name": "yontem", "measurement_level": "nominal"},
    ])
    assert client.get("/api/credits", headers=USER).json()["credits_remaining"] == 1

    client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"], "dependent_variable": "basari_puani",
        "independent_variables": ["yontem"]})

    assert client.get("/api/credits", headers=USER).json()["credits_remaining"] == 0


def test_analysis_without_credits_returns_402(client):
    dataset = upload(client, "ttest_independent.csv")
    confirm(client, dataset["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio"},
        {"column_name": "yontem", "measurement_level": "nominal"},
    ])
    body = {"dataset_id": dataset["id"], "dependent_variable": "basari_puani",
            "independent_variables": ["yontem"]}

    assert client.post("/api/analyses", headers=USER, json=body).status_code == 201
    second = client.post("/api/analyses", headers=USER, json=body)
    assert second.status_code == 402
    assert "kredi" in second.json()["detail"].lower()


def test_a_failed_analysis_refunds_its_credit(client):
    """A refusal must not cost the user their one free trial."""
    dataset = upload(client, "ttest_independent.csv")
    confirm(client, dataset["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio"},
        {"column_name": "yontem", "measurement_level": "nominal"},
    ])

    response = client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"], "dependent_variable": "yontem",
        "independent_variables": ["basari_puani"]})
    assert response.status_code == 422
    assert client.get("/api/credits", headers=USER).json()["credits_remaining"] == 1


def test_purchase_does_not_grant_credits_while_iyzico_is_unwired(client):
    """The endpoint must not pretend a payment succeeded."""
    before = client.get("/api/credits", headers=USER).json()["credits_remaining"]
    response = client.post("/api/credits/purchase", headers=USER,
                           json={"package_type": "thesis_bundle"})

    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert client.get("/api/credits", headers=USER).json()["credits_remaining"] == before


def test_purchase_rejects_an_unknown_package(client):
    response = client.post("/api/credits/purchase", headers=USER,
                           json={"package_type": "sonsuz_paket"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def test_report_for_an_unknown_analysis_is_404(client):
    response = client.post("/api/analyses/does-not-exist/report", headers=USER)
    assert response.status_code == 404


def test_report_can_be_regenerated_and_refetched(client):
    dataset = upload(client, "anova_three_groups.csv")
    confirm(client, dataset["id"], [
        {"column_name": "kaygi_puani", "measurement_level": "ratio"},
        {"column_name": "sinif_duzeyi", "measurement_level": "nominal"},
    ])
    analysis = client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"], "dependent_variable": "kaygi_puani",
        "independent_variables": ["sinif_duzeyi"]}).json()

    first = client.post(f"/api/analyses/{analysis['id']}/report?use_llm=false",
                        headers=USER).json()
    second = client.post(f"/api/analyses/{analysis['id']}/report?use_llm=false",
                         headers=USER).json()
    # regenerating updates the same Report row rather than creating a second
    assert first["id"] == second["id"]

    fetched = client.get(f"/api/analyses/{analysis['id']}/report", headers=USER).json()
    assert fetched["interpretation_text_tr"] == second["interpretation_text_tr"]
    assert "F(2, 15) = 71.55" in fetched["interpretation_text_tr"]


def test_a_malformed_encryption_key_is_rejected_at_startup(monkeypatch):
    """§5 KVKK: misconfiguration must fail loudly at boot, not on first upload."""
    from app.config import settings
    from app.storage import StorageError, validate_encryption_key

    monkeypatch.setattr(settings, "storage_encryption_key", "not-a-fernet-key")
    with pytest.raises(StorageError) as excinfo:
        validate_encryption_key()
    assert "Fernet" in str(excinfo.value)

    monkeypatch.setattr(settings, "storage_encryption_key", None)
    validate_encryption_key()  # unset is allowed (ephemeral dev key)


def test_env_file_is_found_regardless_of_working_directory():
    """A relative env_file resolves against the CWD, so a repo-root .env was
    silently ignored when the app was started from backend/ — which is how the
    README says to start it. The configured paths must be absolute."""
    from pathlib import Path

    from app.config import BACKEND_ROOT, REPO_ROOT, Settings

    configured = Settings.model_config["env_file"]
    paths = [Path(p) for p in configured]

    assert all(p.is_absolute() for p in paths), configured
    assert REPO_ROOT / ".env" in paths
    assert BACKEND_ROOT / ".env" in paths


def test_report_still_delivered_when_pdf_backend_is_unavailable(client):
    """WeasyPrint needs a native pango/cairo stack that a fresh machine may
    lack. The Word file is the primary deliverable and must survive that."""
    from unittest.mock import patch

    from app.export.pdf import PdfExportError

    dataset = upload(client, "ttest_independent.csv")
    confirm(client, dataset["id"], [
        {"column_name": "basari_puani", "measurement_level": "ratio"},
        {"column_name": "yontem", "measurement_level": "nominal"},
    ])
    analysis = client.post("/api/analyses", headers=USER, json={
        "dataset_id": dataset["id"], "dependent_variable": "basari_puani",
        "independent_variables": ["yontem"]}).json()

    with patch("app.api.reports.render_pdf",
               side_effect=PdfExportError("pango yok")):
        response = client.post(
            f"/api/analyses/{analysis['id']}/report?use_llm=false", headers=USER
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["docx_url"], "the Word export must still be produced"
    assert body["pdf_url"] is None
    assert body["interpretation_text_tr"]

    download = client.get(
        f"/api/analyses/{analysis['id']}/report/download/pdf", headers=USER
    )
    assert download.status_code == 404


# ---------------------------------------------------------------------------
# §3.1 — Turkish Excel exports (semicolon, cp1254, comma decimal separator)
# ---------------------------------------------------------------------------

def test_turkish_excel_csv_export_is_usable():
    """A Turkish-locale Excel writes "68,52", not "68.52".

    Left as text, the column is classified as categorical and can never be
    chosen as a dependent variable — making the most likely upload from the
    target user unusable.
    """
    from app.ingestion import detect_variables, parse_upload

    # Enough distinct values that the coded-category heuristic (which suggests
    # "ordinal" for a numeric column with few levels) does not apply.
    scores = [60 + i * 1.37 for i in range(24)]
    rows = "\n".join(
        f"{i + 1};{'Çevrimiçi' if i < 12 else 'Yüz yüze'};{score:.2f}".replace(
            f"{score:.2f}", f"{score:.2f}".replace(".", ",")
        )
        for i, score in enumerate(scores)
    )
    body = f"katilimci_no;grup;sinav_puani\n{rows}\n".encode("cp1254")

    frame = parse_upload("veri.csv", body)
    assert list(frame.columns) == ["katilimci_no", "grup", "sinav_puani"]
    assert frame["sinav_puani"].tolist() == [round(s, 2) for s in scores]

    detected = {v.column_name: v for v in detect_variables(frame)}
    assert detected["sinav_puani"].detected_type.value == "numeric"
    assert detected["sinav_puani"].suggested_measurement_level.value == "ratio"
    assert detected["grup"].detected_type.value == "categorical"


def test_decimal_conversion_leaves_genuine_text_alone():
    from app.ingestion import parse_upload

    body = (
        "ad,not\n"
        "Ayşe,çok iyi\n"
        "Mehmet,orta\n"
        "Zeynep,iyi\n"
    ).encode("utf-8")
    frame = parse_upload("veri.csv", body)
    assert frame["not"].tolist() == ["çok iyi", "orta", "iyi"]


def test_ambiguous_thousands_separators_are_not_guessed():
    """"1.234,56" and "1,234.56" cannot be told apart without a locale, and
    guessing wrong changes the value by a factor of a thousand. Leave both."""
    from app.ingestion import parse_upload

    import pandas as pd

    body = ("id,tutar\n1,\"1.234,56\"\n2,\"2.500,00\"\n").encode("utf-8")
    frame = parse_upload("veri.csv", body)
    assert not pd.api.types.is_numeric_dtype(frame["tutar"])


def test_comma_decimals_survive_the_full_pipeline():
    """The end that matters: a comma-decimal column can be a dependent
    variable and produce a real t statistic."""
    import numpy as np

    from app.ingestion import parse_upload
    from app.stats.enums import MeasurementLevel, ResearchTask
    from app.stats.pipeline import AnalysisRequest, run_analysis

    rng = np.random.default_rng(7)
    values = np.r_[rng.normal(70, 6, 30), rng.normal(78, 6, 30)].round(2)
    lines = ["grup;puan"] + [
        f"{'A' if i < 30 else 'B'};{str(v).replace('.', ',')}"
        for i, v in enumerate(values)
    ]
    frame = parse_upload("veri.csv", "\n".join(lines).encode("cp1254"))

    outcome = run_analysis(frame, AnalysisRequest(
        task=ResearchTask.COMPARISON, dependent_variable="puan",
        independent_variables=["grup"],
        measurement_levels={"puan": MeasurementLevel.RATIO,
                            "grup": MeasurementLevel.NOMINAL},
    ))
    assert outcome.executed_analysis_type == "independent_t_test"
    assert outcome.result.n_total == 60
    assert abs(outcome.result.statistics["t"]) > 1


# ---------------------------------------------------------------------------
# Authentication at the API boundary (§7)
# ---------------------------------------------------------------------------

@pytest.fixture
def supabase_client(tmp_path, monkeypatch):
    """A client with the dev header OFF and Supabase configured — i.e. how a
    deployment actually runs."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.auth import reset_verifier
    from app.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(settings, "allow_insecure_header_auth", False)
    monkeypatch.setattr(settings, "supabase_url", "https://abcdefgh.supabase.co")
    monkeypatch.setattr(settings, "supabase_jwt_secret", "test-project-secret-long-enough-for-sha256")
    reset_verifier()

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    from app.db import Base, get_db
    import app.models  # noqa: F401

    Base.metadata.create_all(engine)

    from app.main import app

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_verifier()


def bearer(sub="user-uuid-1", email="tez@universite.edu.tr", **overrides):
    import time

    import jwt

    payload = {
        "sub": sub, "aud": "authenticated",
        "iss": "https://abcdefgh.supabase.co/auth/v1",
        "role": "authenticated", "email": email,
        "user_metadata": {"email_verified": True},
        "iat": int(time.time()) - 5, "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    token = jwt.encode(payload, "test-project-secret-long-enough-for-sha256",
                       algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_valid_supabase_token_authenticates(supabase_client):
    response = supabase_client.get("/api/credits", headers=bearer())
    assert response.status_code == 200
    assert response.json()["credits_remaining"] == 1


def test_the_development_header_is_refused_when_disabled(supabase_client):
    """The header seam must be closed by default — this is the whole point."""
    response = supabase_client.get(
        "/api/credits", headers={"X-User-Email": "sahte@universite.edu.tr"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer not-a-real-token"},
    {"Authorization": "Basic dXNlcjpwYXNz"},
    {"Authorization": "Bearer "},
])
def test_missing_or_malformed_credentials_are_401(supabase_client, headers):
    assert supabase_client.get("/api/credits", headers=headers).status_code == 401


def test_a_token_from_another_project_cannot_authenticate(supabase_client):
    import time

    import jwt

    foreign = jwt.encode({
        "sub": "user-uuid-1", "aud": "authenticated",
        "iss": "https://someoneelse.supabase.co/auth/v1",
        "email": "tez@universite.edu.tr",
        "exp": int(time.time()) + 3600,
    }, "test-project-secret-long-enough-for-sha256", algorithm="HS256")

    response = supabase_client.get(
        "/api/credits", headers={"Authorization": f"Bearer {foreign}"}
    )
    assert response.status_code == 401


def test_identity_follows_the_subject_not_the_email(supabase_client):
    """Supabase's `sub` is stable; an email address is not. Changing the email
    must keep the same account rather than silently creating a second one."""
    from app.db import get_db
    from app.models import User

    supabase_client.get("/api/credits", headers=bearer(email="eski@universite.edu.tr"))
    supabase_client.get("/api/credits", headers=bearer(email="yeni@universite.edu.tr"))

    session = next(supabase_client.app.dependency_overrides[get_db]())
    users = session.query(User).all()
    assert len(users) == 1
    assert users[0].email == "yeni@universite.edu.tr"
    assert users[0].auth_provider_id == "user-uuid-1"


def test_two_subjects_are_two_users(supabase_client):
    supabase_client.get("/api/credits", headers=bearer(sub="a", email="a@universite.edu.tr"))
    supabase_client.get("/api/credits", headers=bearer(sub="b", email="b@universite.edu.tr"))

    from app.db import get_db
    from app.models import User

    session = next(supabase_client.app.dependency_overrides[get_db]())
    assert session.query(User).count() == 2


def test_one_users_dataset_is_invisible_to_another(supabase_client):
    """The property the header seam could not provide: real isolation."""
    data = (FIXTURES / "ttest_independent.csv").read_bytes()
    upload_response = supabase_client.post(
        "/api/datasets",
        files={"file": ("v.csv", io.BytesIO(data), "text/csv")},
        headers=bearer(sub="owner", email="owner@universite.edu.tr"),
    )
    assert upload_response.status_code == 201
    dataset_id = upload_response.json()["id"]

    intruder = supabase_client.get(
        f"/api/datasets/{dataset_id}",
        headers=bearer(sub="intruder", email="intruder@universite.edu.tr"),
    )
    assert intruder.status_code == 404


def test_unverified_email_does_not_count_as_a_verified_university_address(
    supabase_client,
):
    """§3.10 gates the free tier on a *confirmed* university address."""
    from app.db import get_db
    from app.models import User

    supabase_client.get("/api/credits", headers=bearer(
        sub="unconfirmed", email="tez@universite.edu.tr", user_metadata={}))

    session = next(supabase_client.app.dependency_overrides[get_db]())
    user = session.query(User).filter(User.auth_provider_id == "unconfirmed").one()
    assert user.university_email_verified is False


def test_a_confirmed_non_university_address_is_not_marked_verified(supabase_client):
    from app.db import get_db
    from app.models import User

    supabase_client.get("/api/credits", headers=bearer(
        sub="gmail-user", email="birisi@gmail.com"))

    session = next(supabase_client.app.dependency_overrides[get_db]())
    user = session.query(User).filter(User.auth_provider_id == "gmail-user").one()
    assert user.university_email_verified is False


def test_a_confirmed_university_address_is_marked_verified(supabase_client):
    from app.db import get_db
    from app.models import User

    supabase_client.get("/api/credits", headers=bearer(
        sub="uni-user", email="ogrenci@bogazici.edu.tr"))

    session = next(supabase_client.app.dependency_overrides[get_db]())
    user = session.query(User).filter(User.auth_provider_id == "uni-user").one()
    assert user.university_email_verified is True


def test_a_bearer_token_is_refused_when_supabase_is_not_configured(
    supabase_client, monkeypatch
):
    """A misconfigured deployment must fail closed, never fall through to the
    insecure header path."""
    from app.auth import reset_verifier
    from app.config import settings

    monkeypatch.setattr(settings, "supabase_url", None)
    monkeypatch.setattr(settings, "supabase_jwt_secret", None)
    reset_verifier()

    assert supabase_client.get("/api/credits", headers=bearer()).status_code == 401


def test_pre_supabase_rows_are_claimed_on_first_sign_in(supabase_client):
    """A row created before auth existed keeps its datasets when its owner
    signs in for the first time, rather than being orphaned."""
    from app.db import get_db
    from app.models import User

    session = next(supabase_client.app.dependency_overrides[get_db]())
    session.add(User(email="eskikullanici@universite.edu.tr", auth_provider_id=None))
    session.commit()

    supabase_client.get("/api/credits", headers=bearer(
        sub="returning-user", email="eskikullanici@universite.edu.tr"))

    users = session.query(User).all()
    assert len(users) == 1
    assert users[0].auth_provider_id == "returning-user"
