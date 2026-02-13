from amo_api.amo_api import AmoCRMWrapper
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User


def processing_contact(amo_api: AmoCRMWrapper,
                       contact_phone_number: str,) -> dict|None:
    contact_amo: tuple[bool, dict|str] = amo_api.get_contact_by_phone(phone_number=contact_phone_number)
    if contact_amo[0]: # Контакт найден
        contact = contact_amo[1]
        first_name = contact.get("first_name", "")
        last_name = contact.get("last_name", "")
        amo_id = contact.get('id', '')
        tg_id = [field for field in contact.get('custom_fields_values') if field.get('field_id') == 1097296]

        return {
            "first_name": first_name,
            "last_name": last_name,
            "phone_number": contact_phone_number,
            "amo_contact_id": amo_id,
            'tg_id': tg_id
        }
    else:
        return None


def processing_lead(amo_api: AmoCRMWrapper,
                    contact_id: str,
                    pipeline_id: str,
                    status_id: str) -> dict|None:

    lead = amo_api.find_lead_by_contact_in_pipeline_stage(contact_id=str(contact_id),
                                                          pipeline_id=pipeline_id,
                                                          status_id=status_id)
    if lead is not None:
        lead_id = lead.get('id', '')
    else:
        lead_id = False

    if lead_id:
        return {
            "amo_deal_id": lead_id,
        }
    else:
        return None
