import aiohttp
import asyncio
import logging
import json
import os
import time

# ----------------- Настройки -----------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
if not TELEGRAM_TOKEN or not CHAT_ID:
    raise ValueError("Не заданы TELEGRAM_TOKEN или CHAT_ID в переменных окружения!")

# Определяем рабочую директорию для Actions
BASE_DIR = os.getenv("GITHUB_WORKSPACE", ".")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")
LINKS_FILE = os.path.join(BASE_DIR, "sent_links.txt")

# ----------------- Логирование -----------------
os.makedirs(BASE_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True
)

ALGOLIA_URL = (
    "https://muyenv21k6-dsn.algolia.net/1/indexes/*/queries"
    "?x-algolia-agent=Algolia%20for%20JavaScript%20(4.22.1)%3B%20Browser%20(lite)%3B%20instantsearch.js%20(4.64.2)%3B%20Vue%20(2.6.12)%3B%20Vue%20InstantSearch%20(4.13.6)%3B%20JS%20Helper%20(3.16.2)"
    "&x-algolia-api-key=MGMwZWQxNWJjMDU0MDJmNzM0YTQ1OWU0ZDA0MzkyNzI5ZjZmYTE1MDU0YmZiZWRiZjJkYzBiNTBmZmVkNDkxZGZpbHRlcnM9JTI4aXNfc29sZCUzQWZhbHNlJTI5K0FORCslMjhzaXRlX2lkJTNBMSUyOStBTkQrJTI4bWFrZSUzQVRveW90YSUyOQ%3D%3D"
    "&x-algolia-application-id=MUYENV21K6"
)

HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "uk,en-US;q=0.9,en;q=0.8,ru;q=0.7,no;q=0.6",
    "Connection": "keep-alive",
    "Origin": "https://forhandler.toyota.no",
    "Referer": "https://forhandler.toyota.no/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 OPR/120.0.0.0",
    "content-type": "application/x-www-form-urlencoded"
}

FILTERS = {
    "year_from": 2017,
    "km_to": 130000,
    "price_from": 100000,
    "price_to": 200000,
    "gearbox": "Automat"
}

# ----------------- Вспомогательные функции -----------------
def load_sent_ids():
    if os.path.exists(LINKS_FILE):
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            return set(line.split(",")[0] for line in f.read().splitlines())
    return set()

def save_sent_ids(ids):
    with open(LINKS_FILE, "a", encoding="utf-8") as f:
        for eid in ids:
            f.write(f"{eid},{int(time.time())}\n")
    logging.info(f"Сохранили {len(ids)} новых ID в {LINKS_FILE}")

def format_message(car):
    link = f"https://forhandler.toyota.no/bruktbil/{car.get('external_ad_id')}?toyota_global_styling"
    title = car.get('title') or f"{car.get('make','')} {car.get('model','')}"
    return (
        f"🚗 <b>{title}</b>\n"
        f"⚡ Двигатель: {car.get('fuel_type','')}, {car.get('gearbox_type','')}\n"
        f"📅 Год: {car.get('model_year','')}\n"
        f"🛣 Пробег: {car.get('mileage_in_km','')} km\n"
        f"💰 Цена: kr {car.get('price','')}\n"
        f"📍 {car['department'].get('name','')}, {car['department'].get('department_city','')}\n"
        f"🔗 <a href='{link}'>Ссылка на объявление</a>"
    )

async def send_telegram_photo(session, car):
    photo_url = (
        car.get("featured_image") or
        car.get("featured_image_small") or
        (car.get("images")[0] if car.get("images") else None) or
        (car.get("gallery_images")[0] if car.get("gallery_images") else None)
    )

    if not photo_url:
        logging.warning(f"Фото отсутствует для {car.get('title')}")
        await send_telegram_message(session, format_message(car))
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": photo_url,
        "caption": format_message(car),
        "parse_mode": "HTML"
    }
    async with session.post(url, data=payload) as resp:
        logging.info(f"Отправлено фото в Telegram - HTTP {resp.status}")

async def send_telegram_message(session, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
    async with session.post(url, data=payload) as resp:
        logging.info(f"Отправлено сообщение в Telegram - HTTP {resp.status}")

# ----------------- Основная логика -----------------
async def fetch_cars():
    numeric_filters = (
        f"[\"price>={FILTERS['price_from']}\","
        f"\"price<={FILTERS['price_to']}\","
        f"\"model_year>={FILTERS['year_from']}\","
        f"\"mileage_in_km<={FILTERS['km_to']}\"]"
    )
    filters = f"(is_sold:false) AND (site_id:1) AND (make:Toyota) AND (gearbox_type:{FILTERS['gearbox']})"

    payload = {
        "requests": [
            {
                "indexName": "prod_used_car",
                "params": (
                    f"analytics=false&clickAnalytics=false&facets=mileage_in_km"
                    f"&highlightPostTag=__%2Fais-highlight__&highlightPreTag=__ais-highlight__"
                    f"&hitsPerPage=50&maxValuesPerFacet=200"
                    f"&numericFilters={numeric_filters}"
                    f"&page=0&query=&filters={filters}"
                )
            }
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(ALGOLIA_URL, headers=HEADERS, data=json.dumps(payload)) as resp:
            text = await resp.text()
            try:
                data = json.loads(text)
                return data["results"][0]["hits"]
            except Exception as e:
                logging.error("Ошибка парсинга JSON: %s", e)
                logging.info("RAW RESPONSE: %s", text)
                return []

async def main():
    sent_ids = load_sent_ids()
    new_ids = set()

    cars = await fetch_cars()
    logging.info(f"Найдено объявлений: {len(cars)}")

    async with aiohttp.ClientSession() as session:
        sent_any = False
        for car in cars:
            title = car.get('title')
            model = car.get('model')
            eid = car.get('external_ad_id')

            # Исключаем Toyota Yaris
            if model == "Yaris":
                logging.info(f"Пропускаем Yaris: {eid}")
                continue

            if not eid:
                logging.warning(f"Пропущено объявление без external_ad_id: {title}")
                continue

            if eid in sent_ids:
                logging.info(f"Уже отправлено: {title} ({eid})")
                continue

            await send_telegram_photo(session, car)
            new_ids.add(eid)
            sent_any = True
            logging.info(f"Отправлено новое объявление: {title} ({eid})")

        if new_ids:
            save_sent_ids(new_ids)
        if not sent_any:
            await send_telegram_message(session, "ℹ️ Новых объявлений нет.")

if __name__ == "__main__":
    asyncio.run(main())
