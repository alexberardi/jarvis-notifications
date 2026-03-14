import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)
from app.db import Base


def _generate_uuid() -> str:
    return str(uuid.uuid4())


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id = Column(String(36), primary_key=True, default=_generate_uuid)
    user_id = Column(Integer, nullable=False, index=True)
    household_id = Column(String(255), nullable=False, index=True)
    push_token = Column(String(255), unique=True, nullable=False, index=True)
    device_type = Column(String(20), nullable=False)  # "ios" or "android"
    device_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(String(36), primary_key=True, default=_generate_uuid)
    source_service = Column(String(255), nullable=False, index=True)
    target_type = Column(String(20), nullable=False)  # "user" or "household"
    target_id = Column(String(255), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    data = Column(Text, nullable=True)  # JSON string
    category = Column(String(50), nullable=True)
    token_count = Column(Integer, default=0, nullable=False)
    success_count = Column(Integer, default=0, nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    delivery_status = Column(
        String(20), default="pending", nullable=False
    )  # delivered, partial, failed, skipped
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class InboxItem(Base):
    __tablename__ = "inbox_items"

    id = Column(String(36), primary_key=True, default=_generate_uuid)
    user_id = Column(Integer, nullable=True, index=True)
    household_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    category = Column(String(50), nullable=False)
    source_service = Column(String(255), nullable=False)
    metadata_json = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
