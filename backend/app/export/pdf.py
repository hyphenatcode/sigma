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
    except (ImportError, OSError) as exc:
        # ImportError: the Python package is missing.
        # OSError: the package is installed but its native stack (pango, cairo,
        # harfbuzz) is not on the loader path — the usual state of a fresh
        # macOS machine. Either way the Word export still works, so the caller
        # degrades to a report without a PDF rather than failing outright.
        raise PdfExportError(
            "PDF oluşturulamadı: WeasyPrint ve sistem bağımlılıkları "
            "(pango, cairo, harfbuzz) kurulu olmalıdır. Word (.docx) çıktısı "
            "bundan etkilenmez."
        ) from exc

    return HTML(string=render_report_html(content)).write_pdf()
