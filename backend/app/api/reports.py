"""Report endpoints (§6, §3.8): generate the interpretation, tables and files."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import storage
from app.api.deps import get_current_user
from app.apa.tables import APATable, build_tables
from app.db import get_db
from app.export.html import ReportContent, render_report_html, render_tables_html
from app.export.pdf import PdfExportError, render_pdf
from app.export.word import render_docx
from app.interpretation.service import interpret
from app.models import Analysis, Report, User
from app.schemas import ReportOut
from app.stats.results import TestResult

router = APIRouter(prefix="/api/analyses", tags=["reports"])


def _owned_analysis(analysis_id: str, db: Session, user: User) -> Analysis:
    analysis = db.get(Analysis, analysis_id)
    if analysis is None or analysis.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Analiz bulunamadı.")
    if analysis.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu analiz henüz tamamlanmadı.",
        )
    return analysis


def _rehydrate(analysis: Analysis) -> TestResult:
    """Rebuild a TestResult from the stored JSON.

    The APA generators and the interpretation templates read a `TestResult`, so
    a report can be regenerated later without re-running the analysis — and,
    importantly, without touching the uploaded data again.
    """
    from app.stats.assumptions import AssumptionResult
    from app.stats.effect_size import EffectSize
    from app.stats.enums import AssumptionStatus, EffectSizeBand
    from app.stats.results import GroupDescriptive

    raw = analysis.raw_result or {}
    effect = raw.get("effect_size")

    return TestResult(
        analysis_type=raw.get("analysis_type", analysis.analysis_type),
        statistics=raw.get("statistics", {}),
        p_value=raw.get("p_value") if raw.get("p_value") is not None else float("nan"),
        df=raw.get("df", {}),
        effect_size=(
            EffectSize(
                metric=effect["metric"],
                value=effect["value"],
                band=EffectSizeBand(effect["band"]),
                label_tr=effect["label_tr"],
                thresholds=tuple(effect["thresholds"]) if effect.get("thresholds") else None,
                extra=effect.get("extra", {}),
            ) if effect else None
        ),
        descriptives=[
            GroupDescriptive(
                label=d["label"], n=d["n"], mean=d.get("mean"), sd=d.get("sd"),
                median=d.get("median"), mean_rank=d.get("mean_rank"),
            )
            for d in raw.get("descriptives", [])
        ],
        assumption_results=[
            AssumptionResult(
                assumption=a["assumption"], test_name=a["test_name"],
                status=AssumptionStatus(a["status"]), blocking=a.get("blocking", False),
                statistic=a.get("statistic"), p_value=a.get("p_value"),
                group=a.get("group"), detail=a.get("detail", {}),
                message_tr=a.get("message_tr", ""),
            )
            for a in raw.get("assumption_results", [])
        ],
        n_total=raw.get("n_total", 0),
        alpha=raw.get("alpha", 0.05),
        substitution_note_tr=raw.get("substitution_note_tr"),
        extra=raw.get("extra", {}),
    )


@router.post("/{analysis_id}/report", response_model=ReportOut,
             status_code=status.HTTP_201_CREATED)
def generate_report(
    analysis_id: str,
    use_llm: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    """§6: generate the Report (docx + pdf) and return download URLs."""
    analysis = _owned_analysis(analysis_id, db, user)
    result = _rehydrate(analysis)

    tables: list[APATable] = build_tables(result)
    interpretation = interpret(result, use_llm=use_llm)

    content = ReportContent(
        title="İstatistiksel Analiz Raporu",
        dataset_name=analysis.dataset.filename,
        analysis_type=result.analysis_type,
        interpretation=interpretation.text_tr,
        tables=tables,
        substitution_note=result.substitution_note_tr,
    )

    docx_path = storage.save_artifact(f"{analysis.id}.docx", render_docx(content))
    try:
        pdf_path = storage.save_artifact(f"{analysis.id}.pdf", render_pdf(content))
    except PdfExportError:
        # The Word file is the primary deliverable; a PDF backend problem must
        # not lose the whole report.
        pdf_path = None

    report = analysis.report or Report(analysis_id=analysis.id,
                                       interpretation_text_tr="", apa_table_html="")
    report.interpretation_text_tr = interpretation.text_tr
    report.apa_table_html = render_tables_html(tables)
    report.interpretation_source = interpretation.source
    report.rejected_interpretation = interpretation.rejected_text
    report.docx_path = docx_path
    report.pdf_path = pdf_path
    db.add(report)
    db.commit()
    db.refresh(report)

    return _report_out(report, preview=render_report_html(content))


def _report_out(report: Report, preview: str | None = None) -> ReportOut:
    return ReportOut(
        id=report.id,
        analysis_id=report.analysis_id,
        interpretation_text_tr=report.interpretation_text_tr,
        apa_table_html=report.apa_table_html,
        interpretation_source=report.interpretation_source,
        created_at=report.created_at,
        docx_url=f"/api/analyses/{report.analysis_id}/report/download/docx"
        if report.docx_path else None,
        pdf_url=f"/api/analyses/{report.analysis_id}/report/download/pdf"
        if report.pdf_path else None,
        preview_html=preview,
    )


@router.get("/{analysis_id}/report", response_model=ReportOut)
def get_report(
    analysis_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ReportOut:
    analysis = _owned_analysis(analysis_id, db, user)
    if analysis.report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Bu analiz için rapor oluşturulmamış.")
    return _report_out(analysis.report)


@router.get("/{analysis_id}/report/download/{fmt}")
def download_report(
    analysis_id: str,
    fmt: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Stream the stored report back.

    The bytes are read from storage and returned rather than served from a
    path: with R2 there is no local path, and streaming through this endpoint
    keeps the ownership check in one place. A presigned R2 URL would hand out
    access that bypasses `_owned_analysis` entirely.
    """
    analysis = _owned_analysis(analysis_id, db, user)
    report = analysis.report
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Bu analiz için rapor oluşturulmamış.")

    if fmt == "docx":
        key, media_type = report.docx_path, (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    elif fmt == "pdf":
        key, media_type = report.pdf_path, "application/pdf"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Desteklenmeyen dosya biçimi.")

    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Rapor dosyası bulunamadı.")

    try:
        data = storage.load_artifact(key)
    except storage.ObjectNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Rapor dosyası bulunamadı.") from exc

    filename = f"sigma-rapor-{analysis.id[:8]}.{fmt}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
