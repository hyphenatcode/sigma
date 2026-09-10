"""PDF export via WeasyPrint (§3.8).

Deliberately thin: the PDF is the shared HTML of `app.export.html` rendered by
WeasyPrint. There is no second layout engine and no PDF-specific template, so
the PDF cannot disagree with the preview.
"""

from __future__ import annotations

from app.export.html import ReportContent, render_report_html


class PdfExportError(RuntimeError):
    pass


def render_pdf(content: ReportContent) -> bytes:
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover — dependency is declared
        raise PdfExportError(
            "PDF oluşturmak için WeasyPrint kurulu olmalıdır."
        ) from exc

    return HTML(string=render_report_html(content)).write_pdf()
