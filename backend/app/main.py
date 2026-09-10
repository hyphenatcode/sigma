"""Sigma — FastAPI application entry point.

One app, one process: the statistics engine and the API live together (§7
explicitly rules out a microservices split), and analyses run synchronously
inside the request (§5's performance NFR rules out a job queue for v1).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import analyses, credits, datasets, reports
from app.config import settings
from app.ingestion import IngestionError
from app.stats import registry
from app.stats.pipeline import UnsupportedAnalysisError
from app.stats.results import InsufficientDataError
from app.storage import StorageError

#: See app/api/analyses.py — Starlette deprecated its 422 constant's old name.
HTTP_422 = 422

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Sigma API",
    version="0.1.0",
    description=(
        "Türkçe, yapay zekâ destekli istatistiksel analiz platformu. "
        "Tüm istatistiksel değerler deterministik Python ile hesaplanır; "
        "dil modeli yalnızca hesaplanmış sayıların çevresine Türkçe yorum "
        "cümlesi kurar ve çıktısındaki her sayısal değer doğrulanır."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router)
app.include_router(analyses.router)
app.include_router(reports.router)
app.include_router(credits.router)


@app.exception_handler(UnsupportedAnalysisError)
def _unsupported(request: Request, exc: UnsupportedAnalysisError) -> JSONResponse:
    """§3.3: an explicit refusal, never a best-guess substitute."""
    return JSONResponse(
        status_code=HTTP_422,
        content={"detail": exc.message_tr, "code": "analysis_not_supported"},
    )


@app.exception_handler(InsufficientDataError)
def _insufficient(request: Request, exc: InsufficientDataError) -> JSONResponse:
    return JSONResponse(
        status_code=HTTP_422,
        content={"detail": exc.message_tr, "code": "insufficient_data"},
    )


@app.exception_handler(IngestionError)
def _ingestion(request: Request, exc: IngestionError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": exc.message_tr, "code": "ingestion_failed"},
    )


@app.exception_handler(StorageError)
def _storage(request: Request, exc: StorageError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc), "code": "storage_error"},
    )


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.get("/api/analysis-types", tags=["meta"])
def analysis_types() -> dict[str, object]:
    """The AnalysisType registry (§3.9), for the frontend to render choices."""
    return {
        "supported": [
            {
                "key": spec.key,
                "label_tr": spec.label_tr,
                "label_en": spec.label_en,
                "family": spec.family.value,
                "effect_size_metric": spec.effect_size_metric,
            }
            for spec in registry.all_specs().values()
            if spec.supported_in_v1 and spec.recommendable
        ],
        "not_supported_in_v1": [
            {"key": spec.key, "label_tr": spec.label_tr, "notes": spec.notes}
            for spec in registry.all_specs().values()
            if not spec.supported_in_v1
        ],
    }
