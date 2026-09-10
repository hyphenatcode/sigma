"""Shared HTML rendering for preview and PDF (§3.8).

§3.8 asks for a single layout path so the in-app preview, the Word file and the
PDF cannot drift apart. This module is that path: it renders the report to
HTML, which the frontend embeds directly and which WeasyPrint turns into the
PDF. The Word exporter walks the same `APATable` objects, so all three read
from one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.apa.tables import APATable
from app.stats.registry import get as get_spec

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


@dataclass
class ReportContent:
    """Everything a report shows, independent of output format."""

    title: str
    dataset_name: str
    analysis_type: str
    interpretation: str
    tables: list[APATable]
    substitution_note: Optional[str] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def analysis_label(self) -> str:
        return get_spec(self.analysis_type).label_tr

    def context(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "dataset_name": self.dataset_name,
            "analysis_label": self.analysis_label,
            "interpretation": self.interpretation,
            "substitution_note": self.substitution_note,
            "generated_at": self.generated_at.strftime("%d.%m.%Y %H:%M"),
            # Tables arrive as trusted, already-escaped markup from
            # APATable.to_html(); the |safe filter in the template applies to
            # these only, never to user text.
            "tables": [table.to_html() for table in self.tables],
        }


def render_report_html(content: ReportContent) -> str:
    """Full standalone HTML document — the PDF source and the preview body."""
    return _env.get_template("report.html").render(**content.context())


def render_tables_html(tables: list[APATable]) -> str:
    """Just the APA tables, for the `Report.apa_table_html` column (§4)."""
    return "".join(table.to_html() for table in tables)
