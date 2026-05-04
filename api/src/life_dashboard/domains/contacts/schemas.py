import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class AddressData(BaseModel):
    label: str | None = None
    street: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    country: str | None = None


class AddressResponse(AddressData):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class EmailData(BaseModel):
    email: str = Field(min_length=1, max_length=500)
    label: str | None = None
    is_primary: bool = False


class EmailResponse(EmailData):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class PhoneData(BaseModel):
    phone_number: str = Field(min_length=1, max_length=50)
    label: str | None = None
    is_primary: bool = False


class PhoneResponse(PhoneData):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class ContactCreate(BaseModel):
    vcard_uid: str | None = None
    given_name: str | None = Field(default=None, max_length=200)
    family_name: str | None = Field(default=None, max_length=200)
    middle_name: str | None = Field(default=None, max_length=200)
    prefix: str | None = Field(default=None, max_length=50)
    suffix: str | None = Field(default=None, max_length=50)
    display_name: str | None = Field(default=None, max_length=500)
    organization: str | None = Field(default=None, max_length=500)
    job_title: str | None = Field(default=None, max_length=500)
    birthday: date | None = None
    anniversary: date | None = None
    notes: str | None = None
    website: str | None = Field(default=None, max_length=500)
    source: str | None = None
    external_id: str | None = None
    addresses: list[AddressData] = []
    emails: list[EmailData] = []
    phones: list[PhoneData] = []


class ContactUpdate(BaseModel):
    given_name: str | None = Field(default=None, max_length=200)
    family_name: str | None = Field(default=None, max_length=200)
    middle_name: str | None = Field(default=None, max_length=200)
    prefix: str | None = Field(default=None, max_length=50)
    suffix: str | None = Field(default=None, max_length=50)
    display_name: str | None = Field(default=None, max_length=500)
    organization: str | None = Field(default=None, max_length=500)
    job_title: str | None = Field(default=None, max_length=500)
    birthday: date | None = None
    anniversary: date | None = None
    notes: str | None = None
    website: str | None = Field(default=None, max_length=500)
    addresses: list[AddressData] | None = None
    emails: list[EmailData] | None = None
    phones: list[PhoneData] | None = None


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    vcard_uid: str | None
    given_name: str | None
    family_name: str | None
    middle_name: str | None
    prefix: str | None
    suffix: str | None
    display_name: str | None
    organization: str | None
    job_title: str | None
    birthday: date | None
    anniversary: date | None
    notes: str | None
    website: str | None
    source: str | None
    external_id: str | None
    created_at: datetime
    updated_at: datetime
    addresses: list[AddressResponse] = []
    emails: list[EmailResponse] = []
    phones: list[PhoneResponse] = []


class ContactListResponse(BaseModel):
    items: list[ContactResponse]
    total: int
    limit: int
    offset: int
