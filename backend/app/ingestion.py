"""Dataset ingestion and type inference (§3.1).

Parses an uploaded .csv/.xlsx into a dataframe, detects a header row, and infers
each column's type so §3.2 can present it for confirmation. Detection is a
suggestion — the user's `confirmed_type` always wins.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import settings
from app.stats.enums import DetectedType, MeasurementLevel


class IngestionError(ValueError):
    """Carries a Turkish message straight to the user."""

    def __init__(self, message_tr: str):
        super().__init__(message_tr)
        self.message_tr = message_tr


#: A numeric column with at most this many distinct values is *suggested* as
#: categorical — coded variables like 1=Kadın/2=Erkek are numeric in the file
#: but nominal in the analysis. Only a suggestion; §3.2 asks the user.
MAX_DISTINCT_FOR_CODED_CATEGORICAL = 10


@dataclass
class DetectedVariable:
    column_name: str
    position: int
    detected_type: DetectedType
    suggested_measurement_level: MeasurementLevel
    distinct_value_count: int
    missing_count: int
    sample_values: list[Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "column_name": self.column_name,
            "position": self.position,
            "detected_type": self.detected_type.value,
            "suggested_measurement_level": self.suggested_measurement_level.value,
            "distinct_value_count": self.distinct_value_count,
            "missing_count": self.missing_count,
            "sample_values": self.sample_values,
        }


def parse_upload(filename: str, data: bytes) -> pd.DataFrame:
    """§3.1: parse .csv/.xlsx into a tabular structure, detecting the header."""
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.allowed_upload_extensions:
        raise IngestionError(
            f"Yalnızca {', '.join(settings.allowed_upload_extensions)} "
            f"uzantılı dosyalar yüklenebilir."
        )
    if len(data) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise IngestionError(f"Dosya boyutu en fazla {limit_mb} MB olabilir.")
    if not data:
        raise IngestionError("Yüklenen dosya boş.")

    try:
        if suffix == ".csv":
            frame = _read_csv(data)
        else:
            frame = pd.read_excel(io.BytesIO(data))
    except IngestionError:
        raise
    except Exception as exc:  # noqa: BLE001 — surfaced as a Turkish message
        raise IngestionError(f"Dosya okunamadı: {exc}") from exc

    if frame.empty:
        raise IngestionError("Veri setinde hiç satır bulunamadı.")
    if frame.shape[1] < 1:
        raise IngestionError("Veri setinde hiç sütun bulunamadı.")

    frame.columns = [str(c).strip() for c in frame.columns]
    frame = _drop_unnamed_index_columns(frame)
    frame = _convert_turkish_decimals(frame)
    if frame.columns.duplicated().any():
        duplicates = frame.columns[frame.columns.duplicated()].tolist()
        raise IngestionError(
            f"Veri setinde yinelenen sütun adları var: {', '.join(map(str, duplicates))}"
        )
    return frame


#: A number written the Turkish way: optional sign, digits, and a single comma
#: as the decimal separator. Values containing a dot are deliberately excluded —
#: "1.234,56" and "1,234.56" cannot be told apart without knowing the writer's
#: locale, and guessing wrong would silently change someone's data by a factor
#: of a thousand.
_TURKISH_DECIMAL = re.compile(r"^\s*-?\d+,\d+\s*$")
_PLAIN_INTEGER = re.compile(r"^\s*-?\d+\s*$")

#: Share of non-null values that must parse before a column is converted.
_DECIMAL_CONVERSION_THRESHOLD = 0.95


def _convert_turkish_decimals(frame: pd.DataFrame) -> pd.DataFrame:
    """Turn text columns of comma-decimal numbers into real numeric columns.

    A Turkish-locale Excel writes "Save as CSV" with a semicolon separator and
    a comma as the decimal separator, so a score column arrives as the strings
    "68,52", "74,10", ... pandas reads those as text, §3.1 then classifies the
    column as categorical, and the user can never select it as a dependent
    variable — the single most likely upload from the target user is unusable.

    Conversion is deliberately conservative: a column is only converted when
    nearly all of its non-null values look like comma-decimal numbers and at
    least one actually carries a comma. Anything containing a dot is left
    alone, because separating "1.234,56" from "1,234.56" needs locale
    knowledge we do not have.
    """
    for column in frame.columns:
        series = frame[column]
        if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
            continue

        non_null = series.dropna().astype(str)
        if non_null.empty:
            continue

        decimal_like = non_null.str.match(_TURKISH_DECIMAL)
        integer_like = non_null.str.match(_PLAIN_INTEGER)
        parseable = (decimal_like | integer_like).mean()

        # Require a real comma somewhere: a column of plain integers is already
        # numeric as far as pandas is concerned, so there is nothing to fix.
        if parseable < _DECIMAL_CONVERSION_THRESHOLD or not decimal_like.any():
            continue

        converted = pd.to_numeric(
            series.astype(str).str.strip().str.replace(",", ".", regex=False),
            errors="coerce",
        )
        # Do not trade away data: only accept the conversion if it preserves at
        # least as many populated cells as the original column had.
        if converted.notna().sum() >= series.notna().sum() * _DECIMAL_CONVERSION_THRESHOLD:
            frame[column] = converted

    return frame


def _read_csv(data: bytes) -> pd.DataFrame:
    """Try the encodings and separators Turkish datasets actually arrive in.

    Excel's Turkish locale writes CSV with a semicolon separator and cp1254,
    which pandas' defaults do not handle.
    """
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        for separator in (None, ",", ";", "\t"):
            try:
                frame = pd.read_csv(
                    io.BytesIO(data), encoding=encoding, sep=separator,
                    engine="python" if separator is None else "c",
                )
                if frame.shape[1] >= 1 and not frame.empty:
                    return frame
            except Exception as exc:  # noqa: BLE001 — keep trying combinations
                last_error = exc
    raise IngestionError(f"CSV dosyası ayrıştırılamadı: {last_error}")


def _drop_unnamed_index_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the anonymous index column pandas writes with `to_csv(index=True)`."""
    unnamed = [c for c in frame.columns if str(c).startswith("Unnamed:")]
    return frame.drop(columns=unnamed) if unnamed else frame


def detect_variables(frame: pd.DataFrame) -> list[DetectedVariable]:
    """§3.1: infer each column's type, to be confirmed by the user in §3.2."""
    detected: list[DetectedVariable] = []
    for position, column in enumerate(frame.columns):
        series = frame[column]
        non_null = series.dropna()
        distinct = int(non_null.nunique())
        detected_type, level = _classify(non_null, distinct)
        detected.append(DetectedVariable(
            column_name=str(column),
            position=position,
            detected_type=detected_type,
            suggested_measurement_level=level,
            distinct_value_count=distinct,
            missing_count=int(series.isna().sum()),
            sample_values=[_jsonable(v) for v in non_null.head(5).tolist()],
        ))
    return detected


def _classify(non_null: pd.Series, distinct: int) -> tuple[DetectedType, MeasurementLevel]:
    if non_null.empty:
        return DetectedType.CATEGORICAL, MeasurementLevel.NOMINAL

    if pd.api.types.is_bool_dtype(non_null):
        return DetectedType.CATEGORICAL, MeasurementLevel.NOMINAL

    if pd.api.types.is_numeric_dtype(non_null):
        # A numeric column with very few distinct values is probably a coded
        # category. §3.1 only suggests; §3.2 asks the user to confirm.
        if distinct <= MAX_DISTINCT_FOR_CODED_CATEGORICAL:
            return DetectedType.NUMERIC, MeasurementLevel.ORDINAL
        return DetectedType.NUMERIC, MeasurementLevel.RATIO

    if pd.api.types.is_datetime64_any_dtype(non_null):
        # §3.1: dates are informational only, never used to pick a test in v1.
        return DetectedType.DATE, MeasurementLevel.NOMINAL

    parsed = pd.to_numeric(non_null, errors="coerce")
    if parsed.notna().mean() > 0.95:
        # Numbers stored as text, e.g. with a Turkish decimal comma.
        return DetectedType.NUMERIC, (
            MeasurementLevel.ORDINAL if distinct <= MAX_DISTINCT_FOR_CODED_CATEGORICAL
            else MeasurementLevel.RATIO
        )

    return DetectedType.CATEGORICAL, MeasurementLevel.NOMINAL


def _jsonable(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def load_dataframe(filename: str, data: bytes) -> pd.DataFrame:
    """Re-parse a stored dataset for analysis."""
    return parse_upload(filename, data)
