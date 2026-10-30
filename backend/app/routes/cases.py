from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services.cases import get_case, list_cases

router = APIRouter(prefix="/api/cases", tags=["cases"])


class CaseResponse(BaseModel):
    case_id: UUID
    case_name: str
    description: str | None = None
    status: str | None = None
    created_at: datetime | None = None


@router.get("", response_model=list[CaseResponse])
def read_cases() -> list[dict]:
    try:
        return list_cases()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve cases.",
        ) from error


@router.get("/{case_id}", response_model=CaseResponse)
def read_case(case_id: UUID) -> dict:
    try:
        case = get_case(case_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve the case.",
        ) from error

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found.",
        )

    return case