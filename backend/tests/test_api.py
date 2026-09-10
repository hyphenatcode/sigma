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
    from app.config import settings

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")

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
