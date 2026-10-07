from datetime import date, datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from app.models import JobStatus, ItemStatus
from app.settings import settings


class CertificateJobCreateRequest(BaseModel):
    """Bulk certificate generation request schema."""

    event_name: str = Field(
        ...,
        description="Title of the event or course (1-150 characters)",
        examples=["Python Bootcamp 2026"],
    )
    issuer_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Organization or issuer name",
        examples=["Acme Academy"],
    )
    issue_date: Optional[date] = Field(
        default=None,
        description="Date of certificate issuance (defaults to today)",
        examples=["2026-10-01"],
    )
    recipients: list[dict[str, Any]] = Field(
        ...,
        description="List of recipient items. Evaluated leniently at recipient level.",
        examples=[
            {"name": "Asha Verma", "email": "asha@example.com"},
            {"name": "Rohan Das", "email": "rohan@example.com"},
        ],
    )

    @field_validator("event_name")
    @classmethod
    def validate_event_name(cls, v: str) -> str:
        v_stripped = v.strip()
        if not v_stripped:
            raise ValueError("event_name cannot be empty or whitespace only")
        if len(v_stripped) > 150:
            raise ValueError("event_name exceeds maximum length of 150 characters")
        return v_stripped

    @field_validator("issuer_name")
    @classmethod
    def validate_issuer_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v_stripped = v.strip()
        return v_stripped if v_stripped else None

    @field_validator("recipients")
    @classmethod
    def validate_recipients_list(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not v:
            raise ValueError("recipients list cannot be empty")
        max_limit = settings.MAX_RECIPIENTS_PER_JOB
        if len(v) > max_limit:
            raise ValueError(
                f"recipients count ({len(v)}) exceeds maximum allowed limit of {max_limit} per job"
            )
        return v


class CertificateJobCreateResponse(BaseModel):
    """202 Accepted response for newly created certificate job."""

    job_id: str = Field(..., description="Unique UUID of the created job")
    status: JobStatus = Field(..., description="Current job status")
    total_count: int = Field(..., description="Total recipients submitted in job")
    status_url: str = Field(..., description="URL to poll status and progress")


class CertificateJobDetailResponse(BaseModel):
    """Detailed job status and progress response."""

    id: str
    event_name: str
    issuer_name: Optional[str] = None
    issue_date: date
    status: JobStatus
    total_count: int
    success_count: int
    failed_count: int
    pending_count: int
    progress_percent: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    download_all_url: Optional[str] = None


class CertificateItemResponse(BaseModel):
    """Individual certificate item details and download link."""

    id: str
    index: int
    recipient_name: Optional[str] = None
    recipient_email: Optional[str] = None
    status: ItemStatus
    error_message: Optional[str] = None
    verification_code: Optional[str] = None
    download_url: Optional[str] = None


class PaginatedCertificatesResponse(BaseModel):
    """Paginated list of certificate items for a job."""

    total: int
    limit: int
    offset: int
    items: list[CertificateItemResponse]


class VerificationLookupResponse(BaseModel):
    """Certificate verification details."""

    verification_code: str
    recipient_name: str
    event_name: str
    issuer_name: Optional[str] = None
    issue_date: date
    issued_at: datetime
