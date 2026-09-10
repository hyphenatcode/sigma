"""ORM models — a direct transcription of the §4 data model.

Two deliberate shape choices carried over from the spec:

- `Organization` exists from v1 with a nullable FK from `User`, so adding
  institutional licensing in v2 needs no schema migration (§3.10).
- `Analysis.analysis_type` is a plain string keyed to the AnalysisType registry
  rather than a database enum, so registering a v2 analysis (§3.9) does not
  require an ALTER TYPE migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db import Base

#: JSONB on PostgreSQL, plain JSON elsewhere (the test suite runs on SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    """§4. Unused by the v1 UI; present so v2 institutional licensing is not a
    schema migration (§3.10)."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(64), default="none", nullable=False)
    seat_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    university_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    organization_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    organization: Mapped[Optional[Organization]] = relationship(back_populates="users")
    datasets: Mapped[list["Dataset"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    credit_entries: Mapped[list["CreditLedger"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    #: Path to the ENCRYPTED file on disk (§5 KVKK: encrypted at rest).
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="datasets")
    variables: Mapped[list["Variable"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan",
        order_by="Variable.position",
    )
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan"
    )


class Variable(Base):
    """§3.1/§3.2: a column, its detected type, and the user's confirmation."""

    __tablename__ = "variables"
    __table_args__ = (UniqueConstraint("dataset_id", "column_name", name="uq_variable_column"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detected_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    measurement_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    #: §3.2: distinct-value count, shown to the user to confirm group structure.
    distinct_value_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    dataset: Mapped[Dataset] = relationship(back_populates="variables")

    @property
    def effective_type(self) -> str:
        """The user's override wins over detection (§3.1)."""
        return self.confirmed_type or self.detected_type


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Registry key, not a DB enum — see the module docstring.
    analysis_type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: What §3.3 recommended, before any §3.4 substitution.
    recommended_analysis_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    variable_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    assumption_results: Mapped[Optional[list[Any]]] = mapped_column(JSONType, nullable=True)
    effect_size: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    raw_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="analyses")
    dataset: Mapped[Dataset] = relationship(back_populates="analyses")
    report: Mapped[Optional["Report"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", uselist=False
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    interpretation_text_tr: Mapped[str] = mapped_column(Text, nullable=False)
    apa_table_html: Mapped[str] = mapped_column(Text, nullable=False)
    docx_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    pdf_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    #: §3.6 audit trail: "llm", "template", or "template_after_rejection".
    interpretation_source: Mapped[str] = mapped_column(String(32), default="template")
    #: The rejected generation, kept for the §3.6 review log. Never shown.
    rejected_interpretation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    analysis: Mapped[Analysis] = relationship(back_populates="report")


class CreditLedger(Base):
    """§3.10: package-based credits, not a subscription."""

    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    package_type: Mapped[str] = mapped_column(String(32), nullable=False)
    credits_remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    payment_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # TODO(spec-gap): §10 leaves credit expiry undecided ("do thesis-bundle
    # credits expire?"). No expiry column is added until that is answered;
    # adding a nullable `expires_at` later is a trivial migration.

    user: Mapped[User] = relationship(back_populates="credit_entries")
