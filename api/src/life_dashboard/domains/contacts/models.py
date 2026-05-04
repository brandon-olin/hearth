import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from life_dashboard.core.database import Base


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("households.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    vcard_uid: Mapped[str | None] = mapped_column(Text)
    given_name: Mapped[str | None] = mapped_column(String(200))
    family_name: Mapped[str | None] = mapped_column(String(200))
    middle_name: Mapped[str | None] = mapped_column(String(200))
    prefix: Mapped[str | None] = mapped_column(String(50))
    suffix: Mapped[str | None] = mapped_column(String(50))
    display_name: Mapped[str | None] = mapped_column(String(500))
    organization: Mapped[str | None] = mapped_column(String(500))
    job_title: Mapped[str | None] = mapped_column(String(500))
    birthday: Mapped[date | None] = mapped_column(Date)
    anniversary: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[str | None] = mapped_column(String(100))
    external_id: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    addresses: Mapped[list["ContactAddress"]] = relationship(
        "ContactAddress", passive_deletes=True, lazy="noload"
    )
    emails: Mapped[list["ContactEmail"]] = relationship(
        "ContactEmail", passive_deletes=True, lazy="noload"
    )
    phones: Mapped[list["ContactPhone"]] = relationship(
        "ContactPhone", passive_deletes=True, lazy="noload"
    )


class ContactAddress(Base):
    __tablename__ = "contact_addresses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(100))
    street: Mapped[str | None] = mapped_column(String(500))
    city: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(200))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(200))


class ContactEmail(Base):
    __tablename__ = "contact_emails"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(String(500))
    label: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class ContactPhone(Base):
    __tablename__ = "contact_phones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="CASCADE")
    )
    phone_number: Mapped[str] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(String(100))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
