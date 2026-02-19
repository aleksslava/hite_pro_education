from pathlib import Path
import os.path
from dataclasses import dataclass
from environs import Env


BASE_DIR = Path(__file__).resolve().parent.parent

amo_fields = {
    'statuses': {
        'admitted_to_training': 47244117,
        'authorized_in_bot': 65758021,
        'compleat_lesson_1': 35444481,
        'compleat_lesson_2': 35444484,
        'compleat_lesson_3': 41608782,
        'compleat_lesson_4': 41608785,
        'compleat_lesson_5': 41608788,
        'compleat_lesson_6': 41608791,
        'compleat_lesson_7': 58699973,
        'ready_to_exam': 41608797,
        'compleat_exam': 41608800,
        'compleat_training': 35440800,
    },
    'pipelines': {
        'hite_pro_education': 3616530,
    },
    'fields_id': {
        'tg_id': 1097296,
        'tg_username': 1097294,
        'utm_metriks': {
            'utm_compaign': 1106028,
            'utm_content': 930622,
            'utm_source': 930624,
            'utm_medium': 930630,
            'utm_term': 935823
        }
    }
}


# Класс с токеном бота телеграмм
@dataclass
class TgBot:
    token: str  #Токен для доступа к боту


# Класс с объектом TGBot
@dataclass
class Database:
    url: str  # URL подключения к PostgreSQL (async)

# Класс с данными для подключения к API AMO
@dataclass
class AmoConfig:
    amocrm_subdomain: str
    amocrm_client_id: str
    amocrm_client_secret: str
    amocrm_redirect_url: str
    amocrm_access_token: str | None
    amocrm_refresh_token: str | None
    amocrm_secret_code: str
    path_to_env: str

@dataclass
class Config:
    tg_bot: TgBot
    db: Database
    amo_config: AmoConfig
    amo_fields: dict
    admin: str
    utm_token: str
    webhook_url: str




# Функция создания экземпляра класса config
def load_config(path: str | None = BASE_DIR / '.env'):
    env: Env = Env()
    env.read_env(path)

    return Config(
        tg_bot=TgBot(
            token=env("BOT_TOKEN")
        ),
        db=Database(
            url=env("DATABASE_URL")
        ),
        amo_config=AmoConfig(
            path_to_env=path,
            amocrm_subdomain=env("AMOCRM_SUBDOMAIN"),
            amocrm_client_id=env("AMOCRM_CLIENT_ID"),
            amocrm_client_secret=env("AMOCRM_CLIENT_SECRET"),
            amocrm_redirect_url=env("AMOCRM_REDIRECT_URL"),
            amocrm_access_token=env("AMOCRM_ACCESS_TOKEN"),
            amocrm_refresh_token=env("AMOCRM_REFRESH_TOKEN"),
            amocrm_secret_code=env("AMOCRM_SECRET")
        ),
        amo_fields=amo_fields,
        admin=env("ADMIN_ID"),
        utm_token=env("UTM_TOKEN"),
        webhook_url=env("WEBHOOK_URL"),
    )
