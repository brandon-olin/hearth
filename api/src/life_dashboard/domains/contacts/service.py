import uuid
from datetime import datetime

from sqlalchemy import delete as sa_delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from life_dashboard.domains.contacts.models import (
    Contact,
    ContactAddress,
    ContactEmail,
    ContactPhone,
)
from life_dashboard.domains.contacts.schemas import (
    AddressData,
    AddressResponse,
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
    EmailData,
    EmailResponse,
    PhoneData,
    PhoneResponse,
)


# ── Child loaders ─────────────────────────────────────────────────────────────

async def _load_children(
    db: AsyncSession, contact_ids: list[uuid.UUID]
) -> tuple[
    dict[uuid.UUID, list[ContactAddress]],
    dict[uuid.UUID, list[ContactEmail]],
    dict[uuid.UUID, list[ContactPhone]],
]:
    if not contact_ids:
        return {}, {}, {}

    addr_rows = (await db.execute(
        select(ContactAddress).where(ContactAddress.contact_id.in_(contact_ids))
    )).scalars().all()
    email_rows = (await db.execute(
        select(ContactEmail).where(ContactEmail.contact_id.in_(contact_ids))
    )).scalars().all()
    phone_rows = (await db.execute(
        select(ContactPhone).where(ContactPhone.contact_id.in_(contact_ids))
    )).scalars().all()

    addr_map: dict[uuid.UUID, list[ContactAddress]] = {}
    for a in addr_rows:
        addr_map.setdefault(a.contact_id, []).append(a)

    email_map: dict[uuid.UUID, list[ContactEmail]] = {}
    for e in email_rows:
        email_map.setdefault(e.contact_id, []).append(e)

    phone_map: dict[uuid.UUID, list[ContactPhone]] = {}
    for p in phone_rows:
        phone_map.setdefault(p.contact_id, []).append(p)

    return addr_map, email_map, phone_map


def _build_response(
    contact: Contact,
    addrs: list[ContactAddress],
    emails: list[ContactEmail],
    phones: list[ContactPhone],
) -> ContactResponse:
    return ContactResponse.model_validate(contact).model_copy(update={
        "addresses": [AddressResponse.model_validate(a) for a in addrs],
        "emails": [EmailResponse.model_validate(e) for e in emails],
        "phones": [PhoneResponse.model_validate(p) for p in phones],
    })


# ── Child writers ─────────────────────────────────────────────────────────────

async def _replace_addresses(
    db: AsyncSession, contact_id: uuid.UUID, items: list[AddressData]
) -> None:
    await db.execute(sa_delete(ContactAddress).where(ContactAddress.contact_id == contact_id))
    for item in items:
        db.add(ContactAddress(contact_id=contact_id, **item.model_dump()))


async def _replace_emails(
    db: AsyncSession, contact_id: uuid.UUID, items: list[EmailData]
) -> None:
    await db.execute(sa_delete(ContactEmail).where(ContactEmail.contact_id == contact_id))
    for item in items:
        db.add(ContactEmail(contact_id=contact_id, **item.model_dump()))


async def _replace_phones(
    db: AsyncSession, contact_id: uuid.UUID, items: list[PhoneData]
) -> None:
    await db.execute(sa_delete(ContactPhone).where(ContactPhone.contact_id == contact_id))
    for item in items:
        db.add(ContactPhone(contact_id=contact_id, **item.model_dump()))


# ── CRUD ──────────────────────────────────────────────────────────────────────

async def create_contact(
    db: AsyncSession,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ContactCreate,
) -> ContactResponse:
    vcard_uid = data.vcard_uid or f"ld-{uuid.uuid4()}@life-dashboard.local"
    contact = Contact(
        household_id=household_id,
        created_by_user_id=user_id,
        vcard_uid=vcard_uid,
        given_name=data.given_name,
        family_name=data.family_name,
        middle_name=data.middle_name,
        prefix=data.prefix,
        suffix=data.suffix,
        display_name=data.display_name,
        organization=data.organization,
        job_title=data.job_title,
        birthday=data.birthday,
        anniversary=data.anniversary,
        notes=data.notes,
        website=data.website,
        source=data.source,
        external_id=data.external_id,
    )
    db.add(contact)
    await db.flush()

    await _replace_addresses(db, contact.id, data.addresses)
    await _replace_emails(db, contact.id, data.emails)
    await _replace_phones(db, contact.id, data.phones)

    await db.commit()
    await db.refresh(contact)

    addr_map, email_map, phone_map = await _load_children(db, [contact.id])
    return _build_response(
        contact,
        addr_map.get(contact.id, []),
        email_map.get(contact.id, []),
        phone_map.get(contact.id, []),
    )


async def get_contact(
    db: AsyncSession,
    contact_id: uuid.UUID,
    household_id: uuid.UUID,
) -> ContactResponse | None:
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.household_id == household_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        return None

    addr_map, email_map, phone_map = await _load_children(db, [contact.id])
    return _build_response(
        contact,
        addr_map.get(contact.id, []),
        email_map.get(contact.id, []),
        phone_map.get(contact.id, []),
    )


async def list_contacts(
    db: AsyncSession,
    household_id: uuid.UUID,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> ContactListResponse:
    query = select(Contact).where(Contact.household_id == household_id)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Contact.given_name.ilike(pattern),
                Contact.family_name.ilike(pattern),
                Contact.display_name.ilike(pattern),
                Contact.organization.ilike(pattern),
            )
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    contacts = list(
        (await db.execute(
            query.order_by(
                Contact.family_name.asc().nulls_last(),
                Contact.given_name.asc().nulls_last(),
            ).limit(limit).offset(offset)
        )).scalars().all()
    )

    ids = [c.id for c in contacts]
    addr_map, email_map, phone_map = await _load_children(db, ids)
    items = [
        _build_response(c, addr_map.get(c.id, []), email_map.get(c.id, []), phone_map.get(c.id, []))
        for c in contacts
    ]
    return ContactListResponse(items=items, total=total, limit=limit, offset=offset)


async def update_contact(
    db: AsyncSession,
    contact_id: uuid.UUID,
    household_id: uuid.UUID,
    data: ContactUpdate,
) -> ContactResponse | None:
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.household_id == household_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        return None

    sent = data.model_fields_set
    for field in ("given_name", "family_name", "middle_name", "prefix", "suffix",
                  "display_name", "organization", "job_title", "birthday", "anniversary",
                  "notes", "website"):
        if field in sent:
            setattr(contact, field, getattr(data, field))

    if "addresses" in sent and data.addresses is not None:
        await _replace_addresses(db, contact.id, data.addresses)
    if "emails" in sent and data.emails is not None:
        await _replace_emails(db, contact.id, data.emails)
    if "phones" in sent and data.phones is not None:
        await _replace_phones(db, contact.id, data.phones)

    await db.commit()
    await db.refresh(contact)

    addr_map, email_map, phone_map = await _load_children(db, [contact.id])
    return _build_response(
        contact,
        addr_map.get(contact.id, []),
        email_map.get(contact.id, []),
        phone_map.get(contact.id, []),
    )


async def delete_contact(
    db: AsyncSession,
    contact_id: uuid.UUID,
    household_id: uuid.UUID,
) -> bool:
    result = await db.execute(
        select(Contact).where(Contact.id == contact_id, Contact.household_id == household_id)
    )
    contact = result.scalar_one_or_none()
    if contact is None:
        return False
    await db.delete(contact)
    await db.commit()
    return True
