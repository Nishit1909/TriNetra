from pathlib import Path
import logging
from tempfile import NamedTemporaryFile
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.services.ingestion_service import (
    MAX_UPLOAD_BYTES,
    get_ingestion_run,
    ingest_archive,
    list_ingestion_runs,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


@router.post("/upload")
async def upload_dataset(
    file: Annotated[UploadFile, File(...)],
    dry_run: bool = False,
) -> dict:
    if not file.filename or Path(file.filename).suffix.lower() != ".zip":
        raise HTTPException(status_code=400, detail="Upload a ZIP dataset archive.")

    temporary_path: Path | None = None
    size = 0
    try:
        with NamedTemporaryFile(prefix="sih-upload-", suffix=".zip", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the maximum size.")
                temporary.write(chunk)
        result = ingest_archive(temporary_path, dry_run=dry_run)
        if result["status"] == "validation_failed":
            raise HTTPException(status_code=400, detail=result)
        return result
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Dataset upload failed")
        raise HTTPException(status_code=500, detail="Unable to process the dataset upload.") from error
    finally:
        await file.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@router.get("/runs")
def read_ingestion_runs(
    limit: Annotated[int, Query(gt=0, le=100)] = 20,
) -> list[dict]:
    try:
        return list_ingestion_runs(limit)
    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to retrieve ingestion runs.") from error


@router.get("/runs/{ingestion_run_id}")
def read_ingestion_run(ingestion_run_id: UUID) -> dict:
    try:
        result = get_ingestion_run(ingestion_run_id)
    except Exception as error:
        raise HTTPException(status_code=500, detail="Unable to retrieve the ingestion run.") from error
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion run not found.")
    return result