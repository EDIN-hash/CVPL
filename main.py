import os
import re
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from supabase import create_client, Client
import config

# --- ПРОВЕРКА КЛЮЧЕЙ ПРИ СТАРТЕ ---
REQUIRED_ENV_VARS = ["SUPABASE_URL", "SUPABASE_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
for var in REQUIRED_ENV_VARS:
    if not os.environ.get(var):
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не найден ключ окружения {var}!")

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

def escape_html(text):
    """Экранирование символов, чтобы Telegram не крашился на спецсимволах"""
    if not text:
        return "N/A"
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def send_telegram_alert(job: dict, score: int, matches: list):
    title = escape_html(job.get('title'))
    company = escape_html(job.get('company'))
    url = job.get('url')
    location = escape_html(job.get('location'))
    skills = escape_html(', '.join(matches)) if matches else "Нет прямых совпадений"
    
    text = (
        f"🎯 <b>Новая вакансия! Match Score: {score}/100</b>\n\n"
        f"📌 <b>Должность:</b> {title}\n"
        f"🏢 <b>Компания:</b> {company}\n"
        f"📍 <b>Локация:</b> {location}\n"
        f"💡 <b>Совпадения:</b> {skills}\n\n"
        f"🔗 <a href='{url}'>Открыть вакансию</a>"
    )
    
    payload = {
        "chat_id": tg_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        r = requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Ошибка отправки в Telegram: {r.text}")
    except Exception as e:
        print(f"Сетевая ошибка при отправке в Telegram: {e}")

def calculate_score(title: str, description: str, location: str, is_remote: bool) -> tuple[int, list]:
    full_text = f"{title} {description}".lower()
    score = 0
    matched_skills = []

    for neg in config.KEYWORDS["negative"]:
        if re.search(r'\b' + re.escape(neg) + r'\b', full_text):
            return -100, []

    for kw in config.KEYWORDS["primary"]:
        if re.search(r'\b' + re.escape(kw) + r'\b', full_text):
            score += 20
            matched_skills.append(kw)

    for kw in config.KEYWORDS["secondary"]:
        if re.search(r'\b' + re.escape(kw) + r'\b', full_text):
            score += 10
            matched_skills.append(kw)

    if is_remote:
        score += 15
    elif config.TARGET_CITY in location.lower():
        score += 10
    else:
        score -= 25

    return min(max(score, 0), 100), matched_skills

def fetch_justjoin_it():
    print("Подключаюсь к JustJoin.it...")
    url = "https://justjoin.it/api/offers"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,pl;q=0.8"
    }
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            offers = res.json()
            parsed = []
            for item in offers:
                city = item.get('city', '')
                city_lower = city.lower() if city else ''
                is_remote = item.get('workplace_type') == 'remote'
                
                # Ищем Познань (с учетом польских символов) или удаленку
                if "poznań" in city_lower or "poznan" in city_lower or is_remote:
                    parsed.append({
                        'id': f"jjit_{item.get('id')}",
                        'title': item.get('title', ''),
                        'company': item.get('company_name', ''),
                        'description': item.get('body', ''),
                        'url': f"https://justjoin.it/offers/{item.get('id')}",
                        'location': city,
                        'is_remote': is_remote
                    })
            print(f"Успех. Найдено сырых вакансий (Познань/Remote): {len(parsed)}")
            return parsed
        else:
            print(f"Ошибка API JustJoin: Код {res.status_code}")
    except Exception as e:
        print(f"Критическая ошибка парсинга JustJoin: {e}")
    return []

def monitor_jobs():
    while True:
        print("\n--- НАЧАЛО ЦИКЛА МОНИТОРИНГА ---")
        try:
            # 1. Читаем базу
            print("Запрашиваю сохраненные ID из Supabase...")
            existing_records = supabase.table('jobs').select('id').execute()
            existing_ids = {item['id'] for item in existing_records.data}
            print(f"В базе уже есть {len(existing_ids)} вакансий.")

            # 2. Парсим
            jobs = fetch_justjoin_it()
            
            new_jobs_count = 0
            sent_count = 0

            # 3. Фильтруем и шлем
            for job in jobs:
                job_id = str(job['id'])
                if job_id in existing_ids:
                    continue
                
                new_jobs_count += 1
                score, matches = calculate_score(
                    job['title'], 
                    job['description'], 
                    job['location'], 
                    job['is_remote']
                )

                # Сохраняем в Supabase с обработкой ошибки
                try:
                    supabase.table('jobs').insert({'id': job_id, 'url': job['url']}).execute()
                except Exception as db_err:
                    print(f"Ошибка записи в БД для {job_id}: {db_err}")
                    continue # Если не смогли записать, лучше не отправлять, чтобы не спамить дублями потом

                # Если проходит по очкам - шлем алерт
                if score >= config.SCORE_THRESHOLD:
                    send_telegram_alert(job, score, matches)
                    sent_count += 1
                    time.sleep(0.5) # Защита от лимитов Телеграма (не больше 30 сообщений в секунду)

            print(f"Обработка завершена. Новых: {new_jobs_count}. Отправлено в TG: {sent_count}.")
        except Exception as e:
            print(f"ГЛОБАЛЬНАЯ ОШИБКА ЦИКЛА: {e}")
            
        print("Засыпаю на 3 часа...")
        time.sleep(10800)

class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running!")

if __name__ == "__main__":
    print("Инициализация системы...")
    task_thread = threading.Thread(target=monitor_jobs)
    task_thread.daemon = True
    task_thread.start()

    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    print(f"Веб-сервер запущен на порту {port}")
    server.serve_forever()
