from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services.people import get_person, list_people

router = APIRouter(prefix="/api/people", tags=["people"])


class PersonResponse(BaseModel):
    person_id: str
    case_id: UUID | None = None
    source_domain: str | None = None
    source_entity_id: str | None = None
    display_name: str | None = None
    department: str | None = None
    job_title: str | None = None
    identity_bridge_type: str | None = None


@router.get("", response_model=list[PersonResponse])
def read_people() -> list[dict]:
    try:
        return list_people()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve people.",
        ) from error


@router.get("/{person_id}", response_model=PersonResponse)
def read_person(person_id: str) -> dict:
    try:
        person = get_person(person_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to retrieve the person.",
        ) from error

    if person is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person not found.",
        )

    return person