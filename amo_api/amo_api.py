from pprint import pprint
from typing import Optional, Any
import dotenv
import jwt
import requests
from datetime import datetime
import logging

from pydantic import json
from requests.exceptions import JSONDecodeError

from db import User

logger = logging.getLogger(__name__)



class Contact:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name')
        self.custom_fields_values = kwargs.get('custom_fields_values')
        self.phone_list = self._get_contact_data_list(field_name='Телефон')
        self.mail_list = self._get_contact_data_list(field_name='Email')

    def _get_contact_data_list(self, field_name) -> list:
        data = []
        for field in self.custom_fields_values:
            if field.get('field_name') == field_name:
                for arg in field.get('values'):
                    data.append(arg.get('value'))

        return data

    def __str__(self):
        contact_message = f'\n{self.name}\n'

        for number in self.phone_list:
            value = f'📞 {number}\n'
            contact_message = contact_message + value

        for email in self.mail_list:
            value = f'📧 {email}\n'
            contact_message = contact_message + value

        return contact_message


class Customer:
    # Список доступных статусов партнёра
    partner_status_dct: dict[str, list] = {
        'Отсутствует': ['скидка 0%', 0],
        'Старт': ['скидка 15%', 0],
        'База': ['скидка 20%', 100000],
        'Бронза': ['скидка 25%', 200000],
        'Серебро': ['скидка 30%', 500000],
        'Золото': ['скидка 35%',],
        'Платина': ['скидка 40%',],
        'Бизнес': ['скидка 40%',],
        'Эксклюзив': ['Индивидуальные условия',]
    }

    partner_status_list: list = [
        'Отсутствует', 'Старт', 'База', 'Бронза', 'Серебро', 'Золото', 'Платина', 'Бизнес', 'Эксклюзив'
    ]

    def __init__(self, fields_id: dict[str, int]):
        self.fields_id = fields_id

    def __call__(self, customer_dct: dict):
        self.id = customer_dct.get('id')
        self.name = customer_dct['name']
        self.itv = customer_dct.get('itv')  # Сумма покупок партнёра
        self.custom_fields = customer_dct['custom_fields_values']
        self.manager = customer_dct.get('manager').get('name')
        self.status = self.get_status(self.custom_fields)
        self.bye_in_this_period = self.bye_this_period(self.custom_fields)
        self.bonuses = self.get_bonuses(self.custom_fields)
        self.town = self.get_town(self.custom_fields)
        self.next_status = self.get_next_status(self.status)
        self.tg_id: bool = self.get_customer_tg_id(self.custom_fields)
        self.full_price = self.get_customer_full_price(self.custom_fields)


        return self

    def get_customer_full_price(self, values: list):
        if values is None:
            return 0
        full_price_list = [res for res in values if res['field_id'] == self.fields_id.get('full_price')]
        if not full_price_list:
            return 0
        full_price = full_price_list[0].get('values')[0].get('value')
        full_price = f'{int(full_price):,}'.replace(',', ' ')
        return full_price

    def get_customer_tg_id(self, values: list):
        if values is None:  # Если нет записанного id_tg у партнёра, то True иначе False
            return True

        tg_id = [res for res in values if res['field_id'] == self.fields_id.get('tg_id_field')]
        if tg_id:
            return False
        return True


    def get_status(self, values: list):
        if values is None:
            return f'Отсутствует, {self.partner_status_dct.get("Отсутствует")[0]}'
        status = [res for res in values if res['field_id'] == self.fields_id.get('status_id_field')]
        if not status:
            return f'Отсутствует, {self.partner_status_dct.get("Отсутствует")[0]}'
        status_value: str = status[0].get('values')[0].get('value').split()[0]
        return f'{status_value}, {self.partner_status_dct.get(status_value)[0]}'

    def bye_this_period(self, values: list):
        if values is None:
            return 0
        summ = [res for res in values if res['field_id'] == self.fields_id.get('by_this_period_id_field')]
        if not summ:
            return 0
        summ_value = summ[0].get('values')[0].get('value')
        return summ_value

    def get_bonuses(self, values: list):
        if values is None:
            return 0
        bonuses = [res for res in values if res['field_id'] == self.fields_id.get('bonuses_id_field')]
        if not bonuses:
            return 0
        bonuses_value = bonuses[0].get('values')[0].get('value')
        bonuses_value = f'{int(bonuses_value):,}'.replace(',', ' ')
        return bonuses_value

    def get_town(self, values: list):
        if values is None:
            return 'Отсутствует'
        town = [res for res in values if res['field_id'] == self.fields_id.get('town_id_field')]
        if not town:
            return 'Отсутствует'
        town_value = town[0].get('values')[0].get('value')
        return town_value

    def get_next_status(self, partner_status):
        ind = 1
        for index, status in enumerate(self.partner_status_list):
            if status in partner_status.split()[0]:
                ind = index

        if len(self.partner_status_list) == ind + 1:
            next_status = self.partner_status_list[ind]
        else:
            next_status = self.partner_status_list[ind+1]

        return f'{next_status}, {self.partner_status_dct.get(next_status)[0]}'


class AmoCRMWrapper:
    def __init__(self,
                 path: str,
                 amocrm_subdomain: str,
                 amocrm_client_id: str,
                 amocrm_client_secret: str,
                 amocrm_redirect_url: str,
                 amocrm_access_token: str | None,
                 amocrm_refresh_token: str | None,
                 amocrm_secret_code: str
                 ):
        self.path_to_env = path
        self.amocrm_subdomain = amocrm_subdomain
        self.amocrm_client_id = amocrm_client_id
        self.amocrm_client_secret = amocrm_client_secret
        self.amocrm_redirect_url = amocrm_redirect_url
        self.amocrm_access_token = amocrm_access_token
        self.amocrm_refresh_token = amocrm_refresh_token
        self.amocrm_secret_code = amocrm_secret_code


    @staticmethod
    def _is_expire(token: str):
        token_data = jwt.decode(token, options={"verify_signature": False})
        exp = datetime.utcfromtimestamp(token_data["exp"])
        now = datetime.utcnow()

        return now >= exp

    def _save_tokens(self, access_token: str, refresh_token: str):
        dotenv.set_key(self.path_to_env, "AMOCRM_ACCESS_TOKEN", access_token)
        dotenv.set_key(self.path_to_env, "AMOCRM_REFRESH_TOKEN", refresh_token)
        self.amocrm_access_token = access_token
        self.amocrm_refresh_token = refresh_token

    def _get_access_token(self):
        return self.amocrm_access_token

    def _get_new_tokens(self):
        data = {
            "client_id": self.amocrm_client_id,
            "client_secret": self.amocrm_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.amocrm_refresh_token,
            "redirect_uri": self.amocrm_redirect_url
        }
        response = requests.post("https://{}.amocrm.ru/oauth2/access_token".format(self.amocrm_subdomain),
                                 json=data).json()
        try:
            access_token = response["access_token"]
            refresh_token = response["refresh_token"]
        except KeyError as error:
            logger.error("Ошибка обновления токенов")
            return False

        self._save_tokens(access_token, refresh_token)

    def init_oauth2(self):
        data = {
            "client_id": self.amocrm_client_id,
            "client_secret": self.amocrm_client_secret,
            "grant_type": "authorization_code",
            "code": self.amocrm_secret_code,
            "redirect_uri": self.amocrm_redirect_url
        }

        response = requests.post("https://{}.amocrm.ru/oauth2/access_token".format(self.amocrm_subdomain),
                                 json=data).json()

        access_token = response["access_token"]
        refresh_token = response["refresh_token"]

        self._save_tokens(access_token, refresh_token)

    def _base_request(self, **kwargs) -> json:
        if self._is_expire(self._get_access_token()):
            self._get_new_tokens()

        access_token = "Bearer " + self._get_access_token()

        headers = {"Authorization": access_token}
        req_type = kwargs.get("type")
        response = ""
        if req_type == "get":
            response = requests.get("https://{}.amocrm.ru{}".format(
                self.amocrm_subdomain, kwargs.get("endpoint")), headers=headers)

        elif req_type == "get_param":
            url = "https://{}.amocrm.ru{}?{}".format(
                self.amocrm_subdomain,
                kwargs.get("endpoint"), kwargs.get("parameters"))
            response = requests.get(str(url), headers=headers)

        elif req_type == "post":
            response = requests.post("https://{}.amocrm.ru{}".format(
                self.amocrm_subdomain,
                kwargs.get("endpoint")), headers=headers, json=kwargs.get("data"))

        elif req_type == 'patch':
            response = requests.patch("https://{}.amocrm.ru{}".format(
                self.amocrm_subdomain,
                kwargs.get("endpoint")), headers=headers, json=kwargs.get("data"))
        return response

    def get_contact_by_phone(self, phone_number) -> tuple[bool, dict|str]:

        logger.info(f'Получен телефон клиента: {[phone_number]}')

        url = '/api/v4/contacts'
        query = str(f'query={phone_number}')
        contact = self._base_request(endpoint=url, type="get_param", parameters=query)

        if contact.status_code == 200:
            contacts_list = contact.json()['_embedded']['contacts']

            return True, contacts_list[0]
        elif contact.status_code == 204:
            logger.info(f'Номер телефона {[phone_number]} не найден, пробуем найти через 8')
            phone_number = '8' + phone_number[1:]
            logger.info(f"Пробуем найти номер {phone_number}")

            query = str(f'query={phone_number}')
            contact = self._base_request(endpoint=url, type="get_param", parameters=query)
            if contact.status_code == 200:
                contacts_list = contact.json()['_embedded']['contacts']
                return True, contacts_list[0]
            else:
                return False, 'Контакт не найден'

        else:
            logger.error('Нет авторизации в AMO_API')
            return False, 'Произошла ошибка на сервере!'




    def get_customer_by_id(self, customer_id, with_contacts=False) -> tuple:
        url = f'/api/v4/customers/{customer_id}'
        try:
            if with_contacts:
                query = str(f'with=contacts')
                customer = self._base_request(endpoint=url, type='get_param', parameters=query)
            else:
                customer = self._base_request(endpoint=url, type='get')
        except Exception:
            return False, "Произошла ошибка на сервере"
        if customer.status_code == 200:
            return True, customer.json()
        elif customer.status_code == 204:
            return False, 'Партнёр не найден!'
        else:
            logger.error('Нет авторизации в AMO_API')
            return False, 'Произошла ошибка на сервере!'

    def add_new_task(self, contact_id, descr, url_materials, time, user_id):
        url = '/api/v4/tasks'
        data = [{
            'text': f'Обращение по ошибке чат-бота:\n{descr} {url_materials}',
            'complete_till': time,
            'entity_id': contact_id,
            "entity_type": "contacts",
            'responsible_user_id': user_id
        }
        ]
        response = self._base_request(type='post', endpoint=url, data=data)
        return response

    def get_customer_by_tg_id(self, tg_id: int) -> dict:  # Нужно убрать все id полей амо в конфиг
        url = '/api/v4/customers'
        field_id = '1104992'
        query = str(f'filter[custom_fields_values][{field_id}][]={tg_id}')
        response = self._base_request(endpoint=url, type='get_param', parameters=query)

        if response.status_code == 200:
            customer_list = response.json()['_embedded']['customers']

            if len(customer_list) > 1:
                return {'status_code': False,
                        'tg_id_in_db': False,
                        'response': 'Найдено более одного номера tg_id в базе данных\n'
                                    'Обратитесь к Вашему менеджеру'
                        }
            return {'status_code': True,
                    'tg_id_in_db': True,
                    'response': customer_list[0]
                    }

        elif response.status_code == 204:
            return {'status_code': True,
                    'tg_id_in_db': False,
                    'response': 'Телеграмм id не найден в базе данных'
                    }

        else:
            return {'status_code': False,
                    'tg_id_in_db': False,
                    'response': 'Произошла ошибка на сервере'
                    }

    def get_contact_by_tg_id(self, tg_id: int, fields_id: dict) -> dict:  # Нужно убрать все id полей амо в конфиг
        url = '/api/v4/contacts'
        field_id = fields_id.get('tg_id_field')
        query = str(f'filter[custom_fields_values][{field_id}][]={tg_id}')
        response = self._base_request(endpoint=url, type='get_param', parameters=query)
        if response.status_code == 200:
            contacts_list = response.json()['_embedded']['contacts']

            if len(contacts_list) > 1:
                return {'status_code': False,
                        'tg_id_in_db': False,
                        'response': 'Найдено более одного номера tg_id в базе данных\n'
                                    'Обратитесь к Вашему менеджеру'
                        }
            return {'status_code': True,
                    'tg_id_in_db': True,
                    'response': contacts_list[0]
                    }

        elif response.status_code == 204:
            return {'status_code': True,
                    'tg_id_in_db': False,
                    'response': 'Телеграмм id не найден в базе данных'
                    }

        else:
            return {'status_code': False,
                    'tg_id_in_db': False,
                    'response': 'Произошла ошибка на сервере'
                    }

    def put_data_in_lead(self):
        url = f'/api/v4/leads/32049218'
        data = {"custom_fields_values": [
            {"field_id": 1105338, # Поле оплаты картой
             "values": [
                 {"value": True},
                 ]
             },
            {"field_id": 971974, # Поле склад
             "values": [
                 {"value": 'Я.Доставка'},
             ]
             },
            {"field_id": 958756,  # Поле адрес доставки
             "values": [
                 {'enum_code': 'address_line_1',
                  'enum_id': 1,
                  'value': 'Москва. ул. Берзарина 36, стр.2'}
             ]
             },
            {"field_id": 972566,  # Поле ИНН
             "values": [
                 {"value": '92139123'},
             ]
             },
            {"field_id": 1095240,  # Поле Юр. адрес
             "values": [
                 {"value": 'г. Саратов'},
             ]
             },
            {"field_id": 972568,  # Поле Бик
             "values": [
                 {"value": '777777777'},
             ]
             },
            {"field_id": 972570,  # Поле Расчетный счет
             "values": [
                 {"value": '5555555555'},
             ]
             }
        ]}
        response = self._base_request(type='patch', endpoint=url, data=data)
        return response

    def put_tg_id_to_customer(self, id_customer, tg_id):
        url = f'/api/v4/customers/{id_customer}'
        data = {"custom_fields_values": [
            {"field_id": 1104992,
             "values": [
                 {"value": f"{tg_id}"},
                 ]
             }]}
        response = self._base_request(type='patch', endpoint=url, data=data)
        logger.info(f'Запись ID_telegram: {tg_id} в карту партнёра: {id_customer}\n'
                    f'Статус операции: {response.status_code}')

    def put_tgid_username_to_contact(self, id_contact, tg_id, username, fields_id: dict):
        url = f'/api/v4/contacts/{id_contact}'
        tg_id_field = fields_id.get('tg_id_field')
        tg_username_field = fields_id.get('tg_username_field')
        data = {"custom_fields_values": [
            {"field_id": tg_id_field,
             "values": [
                 {"value": f"{tg_id}"},
             ]
             },
            {"field_id": tg_username_field,
             "values": [
                 {"value": f"{username}"},
             ]
             }]}
        response = self._base_request(type='patch', endpoint=url, data=data)
        logger.info(f'Запись ID_telegram: {tg_id} и username: {username} в контакт покупателя: {id_contact}\n'
                    f'Статус операции: {response.status_code}')

    def send_lead_to_amo(self, pipeline_id: int, status_id: int, contact_id: int, utm_metriks_fields: dict,
                         user: User):
        custom_fields_values = []
        for metrik, metrika_id in utm_metriks_fields.items():
            custom_fields_values.append({
                'field_id': metrika_id,
                'values': [
                    {
                        'value': getattr(user, metrik)
                    }
                ]
            })
        url = f'/api/v4/leads'
        data = [{
            'name': 'Автосделка из бота HiTE_PRO_Education',
            'pipeline_id': int(pipeline_id),
            'created_by': 0,
            'status_id': int(status_id),
            'responsible_user_id': 453498,
            'custom_fields_values': custom_fields_values,
            '_embedded': {
                'contacts': [
                    {
                        'id': int(contact_id)
                    }
                ]
            }

        },]
        response = self._base_request(type='post', endpoint=url, data=data)
        lead_id = response.json().get('_embedded').get('leads')[0].get('id')
        return lead_id

    def push_lead_to_status(self, lead_id: str, pipeline_id: int, status_id: int):
        url = f'/api/v4/leads/{int(lead_id)}'
        data = {
            'name': 'Автосделка из бота hite_pro_education',
            'pipeline_id': int(pipeline_id),
            'updated_by': 0,
            'status_id': int(status_id),

        }
        response = self._base_request(type='patch', endpoint=url, data=data)

        if response.status_code == 200:
            return True
        else:
            return False




    def add_new_note_to_lead(self, lead_id, text):
        url = f'/api/v4/leads/{lead_id}/notes'
        data = [
            {
                'note_type': 'common',
                'params': {
                    'text': text
                }
            }
        ]
        response = self._base_request(type='post', endpoint=url, data=data)
        return response.json()

    def add_catalog_elements_to_lead(self, lead_id, catalog_id: int, elements: list[dict,]):
        url = f'/api/v4/leads/{lead_id}/link'
        data = []
        for element in elements:
            element_id = int(element.get('modificationId'))
            quantity = int(element.get('quantity'))
            element_for_record = {
                'to_entity_id': element_id,
                "to_entity_type": "catalog_elements",
                "metadata": {
                    "quantity": quantity,
                    "catalog_id": catalog_id
                }
            }
            data.append(element_for_record)
        response = self._base_request(type='post', endpoint=url, data=data)
        return response.json()

    # def get_catalog_by_id(self, catalog_id: int, page: int, limit:int):
    #     url = f'/api/v4/catalogs/{catalog_id}/elements'
    #     data = {
    #         'page': page,
    #         'limit': limit
    #     }
    #     response = self._base_request(type='get_param', endpoint=url, parameters=data)
    #     return response.json()

    def get_catalog_elements_by_partnerid(self, partner_id):
        catalog_id = 2244
        url = f'/api/v4/catalogs/{catalog_id}/elements'
        filter = str(f'filter[custom_fields][1105082][from]={partner_id}&filter[custom_fields][1105082][to]={partner_id}')
        response = self._base_request(type='get_param', endpoint=url, parameters=filter)
        print(response.url)
        return response.json()


    def get_contact_by_id(self, contact_id) -> dict:
        url = f'/api/v4/contacts/{contact_id}'
        response = self._base_request(type='get', endpoint=url)

        return response.json()

    def get_responsible_user_by_id(self, manager_id: int):
        url = f'/api/v4/users/{manager_id}'

        responsible_manager = self._base_request(endpoint=url, type='get')
        if responsible_manager.status_code == 200:
            return responsible_manager.json()
        else:
            raise JSONDecodeError

    def get_lead_by_id(self, lead_id):
        url = f'/api/v4/leads/{lead_id}'
        response = self._base_request(type='get', endpoint=url)
        return response.json()

    @staticmethod
    def get_customer_params(customer_dct: dict[str, str], fields_id: dict) -> Customer:
        customer = Customer(fields_id)
        customer = customer(customer_dct)
        return customer


    def get_customers_list_if_tg(self):
        url = f'/api/v4/customers/'
        limit = 250
        page = 1
        filter = {
            'filter[custom_fields][5B1104992][from]': '1',
            # 'page': '1'
        }
        response = self._base_request(type='get_param', endpoint=url, parameters=filter)
        logger.info(f'Статус код запроса записей покупателя: {response.status_code}')
        return response.json()

    def create_new_contact(self, first_name: str, last_name: str, phone: str, tg_id_field: int, tg_id: str,
                           username_id: int, username: str):
        url = '/api/v4/contacts'
        data = [{
            'first_name': first_name,
            'last_name': last_name,
            'responsible_user_id': 453498,
            'custom_fields_values': [
                {"field_id": 671750,
                 "values": [
                     {'enum_code': 'WORK',
                      "value": str(phone)
                      },]
                 },
                {"field_id": tg_id_field,
                 "values": [
                     {
                      "value": str(tg_id)
                      }, ]
                 },
                {"field_id": username_id,
                 "values": [
                     {
                         "value": str(username)
                     }, ]
                 }
            ],
        }]
        response = self._base_request(type='post', endpoint=url, data=data)
        contact_id = response.json().get('_embedded').get('contacts')[0].get('id')
        return contact_id

    def add_tg_to_contact(self, contact_id: int, tg_id_field: int, tg_id: str, username_id: int, username: str):
        url = f'/api/v4/contacts/{contact_id}'
        data = {
            'custom_fields_values': [
                {"field_id": tg_id_field,
                 "values": [
                     {
                         "value": str(tg_id)
                     }, ]
                 },
                {"field_id": username_id,
                 "values": [
                     {
                         "value": str(username)
                     }, ]
                 }
            ],
        }
        response = self._base_request(type='patch', endpoint=url, data=data)
        if response.status_code == 200:
            logger.info('TG_ID успешно добавлен в контакт')
            return True
        else:
            logger.error('TG_ID не добавлен в контакт')
            return False

    def find_lead_by_contact_in_pipeline_stage(
            self,
            contact_id: str,
            pipeline_id: str,
            status_id: str,
            *,
            with_entities: bool = True
    ) -> Optional[dict]:
        """
        Найти сделку по ID контакта в конкретной воронке (pipeline_id) и на конкретном этапе (status_id).

        :param contact_id: ID контакта amoCRM
        :param pipeline_id: ID воронки (pipeline)
        :param status_id: ID этапа (status)
        :param with_entities: если True - запросит embedded сущности (contacts и т.п.)
        :return: dict сделки (lead) или None, если не найдено
        :raises RuntimeError: если amoCRM вернул ошибку
        """

        # Сразу фильтруем на стороне amoCRM по контакту, чтобы не тянуть все сделки
        params = [f"filter[contacts][id]={contact_id}"]

        # Опционально можно сразу сузить по pipeline/status (если вы уверены, что amoCRM принимает эти фильтры у leads)
        # Обычно работает:
        params.append(f"filter[pipeline_id]={pipeline_id}")
        params.append(f"filter[status_id]={status_id}")  # иногда фильтр статуса делают именно так

        if with_entities:
            params.append("with=contacts")

        response = self._base_request(
            type="get_param",
            endpoint="/api/v4/leads",
            parameters="&".join(params),
        )


        # requests.Response
        if response.status_code >= 400:
            # тут можно логировать response.text
            raise RuntimeError(f"amoCRM error {response.status_code}: {response.text}")

        payload = response.json()

        # Если сделок нет, amoCRM обычно возвращает {} или {"_page":..., "_embedded": {...}}
        embedded = payload.get("_embedded", {})
        leads = embedded.get("leads", []) or []

        if not leads:
            return None

        # На всякий случай делаем "жёсткую" проверку pipeline/status (иногда фильтры отличаются)
        for lead in leads:
            if int(lead.get("pipeline_id", -1)) != int(pipeline_id):
                continue
            if int(lead.get("status_id", -1)) != int(status_id):
                continue

            # Доп. проверка, что контакт реально привязан (если with_entities=True)
            if with_entities:
                lead_contacts = (
                        lead.get("_embedded", {}).get("contacts", []) or
                        lead.get("_embedded", {}).get("contacts", [])
                # оставлено намеренно, на случай разных форматов
                )
                if lead_contacts and all(int(c.get("id", -1)) != int(contact_id) for c in lead_contacts):
                    continue

            return lead

        return None

    def find_lead_by_contact_in_pipeline_stage_new(
            self,
            contact_id: str,
            pipeline_id: str,
            status_id: str,
            *,
            with_entities: bool = True
    ) -> Optional[int]:
        page = 1
        limit = 250
        target_contact_id = int(contact_id)
        target_pipeline_id = int(pipeline_id)
        target_status_id = int(status_id)

        while True:
            query = (
                f'filter[pipeline_id][]=3616530&'
                f'filter[statuses][0][pipeline_id]=3616530&'
                f'filter[statuses][0][status_id]=47244117&'
                f'with=contacts&'
                f'limit={limit}&'
                f'page={page}'
            )

            response = self._base_request(
                type="get_param",
                endpoint="/api/v4/leads",
                parameters=query,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"amoCRM error {response.status_code}: {response.text}")

            payload = response.json()

            leads = payload.get("_embedded", {}).get("leads", []) or []
            if not leads:
                return None

            for lead in leads:
                if int(lead.get("pipeline_id", -1)) != target_pipeline_id:
                    continue
                if int(lead.get("status_id", -1)) != target_status_id:
                    continue

                lead_contacts = lead.get("_embedded", {}).get("contacts", []) or []
                if not lead_contacts:
                    continue

                main_contact = None
                for lead_contact in lead_contacts:
                    is_main = lead_contact.get("is_main")
                    if is_main is True or str(is_main).lower() in {"1", "true"}:
                        main_contact = lead_contact
                        break

                if main_contact is None and len(lead_contacts) == 1:
                    main_contact = lead_contacts[0]
                if main_contact is None:
                    continue

                try:
                    main_contact_id = int(main_contact.get("id", -1))
                except (TypeError, ValueError):
                    continue

                if main_contact_id == target_contact_id:
                    return lead.get("id")

            if not payload.get("_links", {}).get("next"):
                return None

            page += 1





if __name__ == '__main__':
    from config.config import load_config, Config
    config: Config = load_config()

    amo_api = AmoCRMWrapper(
        path=config.amo_config.path_to_env,
        amocrm_subdomain=config.amo_config.amocrm_subdomain,
        amocrm_client_id=config.amo_config.amocrm_client_id,
        amocrm_redirect_url=config.amo_config.amocrm_redirect_url,
        amocrm_client_secret=config.amo_config.amocrm_client_secret,
        amocrm_secret_code=config.amo_config.amocrm_secret_code,
        amocrm_access_token=config.amo_config.amocrm_access_token,
        amocrm_refresh_token=config.amo_config.amocrm_refresh_token
    )
    amo_api.init_oauth2()


