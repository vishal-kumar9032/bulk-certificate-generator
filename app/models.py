import enum
import uuid
from datetime import date, datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship
from app.database import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class ItemStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class CertificateJob(Base):
    __tablename__ = "certificate_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_name = Column(String(150), nullable=False)
    issuer_name = Column(String(150), nullable=True)
    issue_date = Column(Date, nullable=False, default=date.today)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING, index=True)

    total_count = Column(Integer, nullable=False, default=0)
    success_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # One-to-many relationship with cascade delete
    items = relationship(
        "CertificateItem",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="CertificateItem.index",
    )


class CertificateItem(Base):
    __tablename__ = "certificate_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("certificate_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    index = Column(Integer, nullable=False)  # 0-based index from input request
    recipient_name = Column(String(200), nullable=True)
    recipient_email = Column(String(255), nullable=True)
    status = Column(Enum(ItemStatus), nullable=False, default=ItemStatus.PENDING, index=True)
    error_message = Column(String(500), nullable=True)
    file_path = Column(String(500), nullable=True)
    verification_code = Column(String(32), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("CertificateJob", back_populates="items")


# Composite index for filtering items by job and status
Index("ix_cert_items_job_status", CertificateItem.job_id, CertificateItem.status)
