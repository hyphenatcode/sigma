"""Dataset endpoints (§6): upload, variable confirmation, deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import ingestion, storage
from app.api.deps import get_current_user
from app.db import get_db
from app.models import Dataset, User, Variable
from app.schemas import DatasetOut, DatasetUploadOut, VariableBulkUpdateIn
from app.stats.enums import MeasurementLevel, VariableRole

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.post("", response_model=DatasetUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DatasetUploadOut:
    """§3.1: parse the upload, infer column types, return them for confirmation."""
    data = await file.read()
    try:
        frame = ingestion.parse_upload(file.filename or "veri.csv", data)
    except ingestion.IngestionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=exc.message_tr) from exc

    detected = ingestion.detect_variables(frame)

    dataset = Dataset(
        user_id=user.id,
        filename=file.filename or "veri.csv",
        storage_path="",
        row_count=int(frame.shape[0]),
        column_count=int(frame.shape[1]),
    )
    db.add(dataset)
    db.flush()

    # §5 KVKK: the raw file is encrypted before it touches the disk.
    dataset.storage_path = storage.save(dataset.id, dataset.filename, data)

    for variable in detected:
        db.add(Variable(
            dataset_id=dataset.id,
            column_name=variable.column_name,
            position=variable.position,
            detected_type=variable.detected_type.value,
            measurement_level=variable.suggested_measurement_level.value,
            distinct_value_count=variable.distinct_value_count,
        ))
    db.commit()
    db.refresh(dataset)

    return DatasetUploadOut(
        id=dataset.id,
        filename=dataset.filename,
        row_count=dataset.row_count,
        column_count=dataset.column_count,
        uploaded_at=dataset.uploaded_at,
        variables=dataset.variables,
        detection=[v.to_dict() for v in detected],
    )


def _owned_dataset(dataset_id: str, db: Session, user: User) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None or dataset.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Veri seti bulunamadı.")
    return dataset


@router.get("/{dataset_id}", response_model=DatasetOut)
def get_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dataset:
    return _owned_dataset(dataset_id, db, user)


@router.patch("/{dataset_id}/variables", response_model=DatasetOut)
def confirm_variables(
    dataset_id: str,
    payload: VariableBulkUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Dataset:
    """§3.2: confirm or override each column's type, level and role."""
    dataset = _owned_dataset(dataset_id, db, user)
    by_name = {v.column_name: v for v in dataset.variables}

    for update in payload.variables:
        variable = by_name.get(update.column_name)
        if variable is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{update.column_name}' sütunu bu veri setinde bulunmuyor.",
            )
        if update.confirmed_type is not None:
            variable.confirmed_type = update.confirmed_type
        if update.measurement_level is not None:
            variable.measurement_level = update.measurement_level.value
        if update.role is not None:
            variable.role = update.role.value

    db.commit()
    db.refresh(dataset)
    return dataset


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """§5 KVKK: the data-deletion endpoint.

    Removes the encrypted file from storage and the dataset row, which cascades
    to its variables and analyses.
    """
    dataset = _owned_dataset(dataset_id, db, user)
    if dataset.storage_path:
        storage.delete(dataset.storage_path)
    db.delete(dataset)
    db.commit()
