"""
Announcement endpoints for the High School Management System API
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)


class AnnouncementPayload(BaseModel):
    """Announcement payload used to create or update records."""

    message: str = Field(..., min_length=3, max_length=240)
    end_date: date
    start_date: Optional[date] = None

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message cannot be empty")
        return normalized


class AnnouncementResponse(BaseModel):
    """Serialized announcement returned by the API."""

    id: str
    message: str
    start_date: Optional[str]
    end_date: str
    created_by: str
    is_active: bool


def _validate_teacher(teacher_username: Optional[str]) -> Dict[str, Any]:
    """Validate teacher credentials for protected actions."""
    if not teacher_username:
        raise HTTPException(
            status_code=401,
            detail="Authentication required for this action"
        )

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Invalid teacher credentials")

    return teacher


def _serialize_announcement(announcement: Dict[str, Any], today: date) -> Dict[str, Any]:
    start_date = _normalize_to_date(announcement.get("start_date"))
    end_date = _normalize_to_date(announcement.get("end_date"))

    if not end_date:
        raise HTTPException(status_code=500, detail="Invalid announcement end date")

    start_active = start_date is None or start_date <= today
    end_active = end_date >= today

    return {
        "id": str(announcement["_id"]),
        "message": announcement["message"],
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat(),
        "created_by": announcement.get("created_by", "unknown"),
        "is_active": start_active and end_active
    }


def _normalize_to_date(value: Optional[Any]) -> Optional[date]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    return None


def _validate_date_window(payload: AnnouncementPayload) -> None:
    if payload.start_date and payload.end_date < payload.start_date:
        raise HTTPException(
            status_code=400,
            detail="Expiration date must be on or after start date"
        )


@router.get("", response_model=List[AnnouncementResponse])
def get_active_announcements() -> List[AnnouncementResponse]:
    """Return only active announcements for the homepage banner."""
    today = date.today()

    announcements = []
    for announcement in announcements_collection.find({}):
        serialized = _serialize_announcement(announcement, today)
        if serialized["is_active"]:
            announcements.append(serialized)

    return sorted(announcements, key=lambda item: item["end_date"])


@router.get("/all", response_model=List[AnnouncementResponse])
def get_all_announcements(teacher_username: Optional[str] = Query(None)) -> List[AnnouncementResponse]:
    """Return all announcements for authenticated users managing content."""
    _validate_teacher(teacher_username)

    today = date.today()
    announcements = [
        _serialize_announcement(announcement, today)
        for announcement in announcements_collection.find({})
    ]

    return sorted(
        announcements,
        key=lambda item: (
            item["end_date"],
            item["start_date"] or ""
        )
    )


@router.post("", response_model=AnnouncementResponse)
def create_announcement(
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> AnnouncementResponse:
    """Create a new announcement. Authentication is required."""
    teacher = _validate_teacher(teacher_username)
    _validate_date_window(payload)

    data = {
        "message": payload.message,
        "start_date": payload.start_date.isoformat() if payload.start_date else None,
        "end_date": payload.end_date.isoformat(),
        "created_by": teacher["username"]
    }

    result = announcements_collection.insert_one(data)
    created = announcements_collection.find_one({"_id": result.inserted_id})
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create announcement")

    return _serialize_announcement(created, date.today())


@router.put("/{announcement_id}", response_model=AnnouncementResponse)
def update_announcement(
    announcement_id: str,
    payload: AnnouncementPayload,
    teacher_username: Optional[str] = Query(None)
) -> AnnouncementResponse:
    """Update an existing announcement by ID. Authentication is required."""
    teacher = _validate_teacher(teacher_username)
    _validate_date_window(payload)

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.update_one(
        {"_id": object_id},
        {
            "$set": {
                "message": payload.message,
                "start_date": payload.start_date.isoformat() if payload.start_date else None,
                "end_date": payload.end_date.isoformat(),
                "created_by": teacher["username"]
            }
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": object_id})
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to load updated announcement")

    return _serialize_announcement(updated, date.today())


@router.delete("/{announcement_id}")
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement by ID. Authentication is required."""
    _validate_teacher(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.delete_one({"_id": object_id})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
