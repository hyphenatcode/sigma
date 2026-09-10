"""Analysis endpoints (§6): run the pipeline, fetch a result."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import ingestion, storage
from app.api.deps import consume_credit, get_current_user
from app.db import get_db
from app.models import Analysis, Dataset, User
from app.schemas import AnalysisCreateIn, AnalysisOut, RecommendationOut
from app.stats import registry
from app.stats.enums import MeasurementLevel
from app.stats.pipeline import (
    AnalysisRequest,
    UnsupportedAnalysisError,
    run_analysis,
)
from app.stats.recommendation import Recommendation
from app.stats.results import InsufficientDataError

router = APIRouter(prefix="/api/analyses", tags=["analyses"])

#: Spelled literally: Starlette renamed its 422 constant and deprecated the old
#: name, so hardcoding avoids coupling to which spelling a given version ships.
HTTP_422 = 422


def _recommendation_out(recommendation: Recommendation | None) -> RecommendationOut | None:
    if recommendation is None:
        return None
    return RecommendationOut(
        supported=recommendation.supported,
        candidate=recommendation.candidate,
        candidate_label_tr=recommendation.candidate_label_tr,
        fallback=recommendation.fallback,
        reason_tr=recommendation.reason_tr,
        rule_path=list(recommendation.rule_path),
    )


def _to_out(analysis: Analysis) -> AnalysisOut:
    label = (
        registry.get(analysis.analysis_type).label_tr
        if analysis.analysis_type in registry.all_specs() else None
    )
    raw = analysis.raw_result or {}
    return AnalysisOut(
        id=analysis.id,
        dataset_id=analysis.dataset_id,
        analysis_type=analysis.analysis_type,
        analysis_label_tr=label,
        recommended_analysis_type=analysis.recommended_analysis_type,
        status=analysis.status,
        created_at=analysis.created_at,
        variable_config=analysis.variable_config or {},
        assumption_results=analysis.assumption_results,
        effect_size=analysis.effect_size,
        raw_result=raw,
        substituted=analysis.analysis_type != analysis.recommended_analysis_type,
        substitution_reason_tr=raw.get("substitution_note_tr"),
        error_message=analysis.error_message,
    )


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
def create_analysis(
    payload: AnalysisCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisOut:
    """§6: run the full deterministic pipeline synchronously (§5 performance)."""
    dataset = db.get(Dataset, payload.dataset_id)
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Veri seti bulunamadı.")

    levels: dict[str, MeasurementLevel] = {}
    for variable in dataset.variables:
        if variable.measurement_level:
            levels[variable.column_name] = MeasurementLevel(variable.measurement_level)

    request = AnalysisRequest(
        task=payload.task,
        dependent_variable=payload.dependent_variable,
        independent_variables=list(payload.independent_variables),
        paired_measurements=list(payload.paired_measurements),
        scale_items=list(payload.scale_items),
        is_paired=payload.is_paired,
        measurement_levels=levels,
    )

    raw = storage.load(dataset.storage_path)
    frame = ingestion.load_dataframe(dataset.filename, raw)

    # §3.10: an analysis costs a credit. Charged before running so a user
    # cannot loop the engine for free. `consume_credit` only flushes, so any
    # `db.rollback()` below returns the credit and discards the Analysis row —
    # a refusal must not cost the user their one free trial.
    consume_credit(db, user)

    analysis = Analysis(
        user_id=user.id,
        dataset_id=dataset.id,
        analysis_type="",
        variable_config=payload.model_dump(mode="json"),
        status="running",
    )
    db.add(analysis)
    db.flush()

    try:
        outcome = run_analysis(frame, request)
    except UnsupportedAnalysisError as exc:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_422,
            detail={
                "detail": exc.message_tr,
                "code": "analysis_not_supported",
                "recommendation": (
                    _recommendation_out(exc.recommendation).model_dump()
                    if exc.recommendation else None
                ),
            },
        ) from exc
    except InsufficientDataError as exc:
        db.rollback()
        raise HTTPException(
            status_code=HTTP_422,
            detail={"detail": exc.message_tr, "code": "insufficient_data"},
        ) from exc

    # §3.3: a pinned analysis_type that disagrees with the rules is refused
    # rather than honoured — the engine's recommendation is the product.
    if payload.analysis_type and payload.analysis_type != outcome.executed_analysis_type:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "detail": (
                    f"İstenen analiz ({payload.analysis_type}) bu veri yapısı için "
                    f"uygun değildir. Öneri motoru "
                    f"{registry.get(outcome.executed_analysis_type).label_tr} "
                    f"analizini seçmiştir."
                ),
                "code": "analysis_type_mismatch",
            },
        )

    result = outcome.result
    analysis.analysis_type = outcome.executed_analysis_type
    analysis.recommended_analysis_type = outcome.recommendation.candidate
    analysis.raw_result = result.to_dict()
    analysis.assumption_results = [a.to_dict() for a in result.assumption_results]
    analysis.effect_size = result.effect_size.to_dict() if result.effect_size else None
    analysis.status = "completed"
    db.commit()
    db.refresh(analysis)
    return _to_out(analysis)



@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalysisOut:
    """§6: result + assumption results + effect size."""
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Analiz bulunamadı.")
    return _to_out(analysis)
