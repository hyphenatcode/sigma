"""Pydantic request/response models for the §6 API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.stats.enums import MeasurementLevel, ResearchTask, VariableRole


class VariableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    column_name: str
    position: int
    detected_type: str
    confirmed_type: Optional[str] = None
    measurement_level: Optional[str] = None
    role: Optional[str] = None
    distinct_value_count: Optional[int] = None


class DatasetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    row_count: int
    column_count: int
    uploaded_at: datetime
    variables: list[VariableOut] = Field(default_factory=list)


class DatasetUploadOut(DatasetOut):
    """§6: upload returns dataset_id plus the detected variable list."""

    detection: list[dict[str, Any]] = Field(default_factory=list)


class VariableUpdateIn(BaseModel):
    """§3.2: the user confirms or overrides one column."""

    column_name: str
    confirmed_type: Optional[str] = None
    measurement_level: Optional[MeasurementLevel] = None
    role: Optional[VariableRole] = None


class VariableBulkUpdateIn(BaseModel):
    variables: list[VariableUpdateIn]


class AnalysisCreateIn(BaseModel):
    """§6: { dataset_id, analysis_type, variable_config }.

    `analysis_type` is optional: leaving it out asks the §3.3 engine to
    recommend one, which is the normal flow. Supplying it pins the choice, and
    the API rejects a pin that disagrees with the engine rather than running
    a test the rules did not select.
    """

    dataset_id: str
    analysis_type: Optional[str] = None
    task: ResearchTask = ResearchTask.COMPARISON
    dependent_variable: Optional[str] = None
    independent_variables: list[str] = Field(default_factory=list)
    paired_measurements: list[str] = Field(default_factory=list)
    scale_items: list[str] = Field(default_factory=list)
    is_paired: bool = False


class RecommendationOut(BaseModel):
    supported: bool
    candidate: Optional[str] = None
    candidate_label_tr: Optional[str] = None
    fallback: Optional[str] = None
    reason_tr: Optional[str] = None
    rule_path: list[str] = Field(default_factory=list)


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    analysis_type: str
    analysis_label_tr: Optional[str] = None
    recommended_analysis_type: Optional[str] = None
    status: str
    created_at: datetime
    variable_config: dict[str, Any] = Field(default_factory=dict)
    assumption_results: Optional[list[Any]] = None
    effect_size: Optional[dict[str, Any]] = None
    raw_result: Optional[dict[str, Any]] = None
    substituted: bool = False
    substitution_reason_tr: Optional[str] = None
    error_message: Optional[str] = None


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_id: str
    interpretation_text_tr: str
    apa_table_html: str
    interpretation_source: str
    created_at: datetime
    docx_url: Optional[str] = None
    pdf_url: Optional[str] = None
    preview_html: Optional[str] = None


class CreditsOut(BaseModel):
    credits_remaining: int
    entries: list[dict[str, Any]] = Field(default_factory=list)


class PurchaseIn(BaseModel):
    package_type: str = Field(description="free_trial | single_analysis | thesis_bundle")


class PurchaseOut(BaseModel):
    status: str
    package_type: str
    redirect_url: Optional[str] = None
    message_tr: str


class ErrorOut(BaseModel):
    detail: str
    code: Optional[str] = None
    recommendation: Optional[RecommendationOut] = None
