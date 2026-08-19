import os
import re
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from supabase import create_client, Client
import config

# Инициализация клиентов
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_alert(job: dict, score: int, matches: list):
    title = job.get('title')
    company = job.get('company', 'N/A')
    url = job.get('url')
    location = job.get('location', 'N/A')
    
    text = (
        f"🎯 *Новая вакансия! Match Score: {score}/100*\n\n"
        f"📌 *Должность:* {title}\n"
        f"🏢 *Компания:* {company}\n"
        f"📍 *Локация:* {location}\n"
        f"💡 *Совпадения:* {', '.join(matches)}\n\n"
        f"🔗 [Открыть вакансию]({url})"
    )
    
    payload = {
        "chat_id": tg_chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json=payload)

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
    url = "https://justjoin.it/api/offers"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            offers = res.json()
            parsed = []
            for item in offers:
                city = item.get('city', '').lower()
                is_remote = item.get('workplace_type') == 'remote'
                
                if city == config.TARGET_CITY or is_remote:
                    parsed.append({
                        'id': f"jjit_{item.get('id')}",
                        'title': item.get('title'),
                        'company': item.get('company_name'),
                        'description': item.get('body', ''),
                        'url': f"https://justjoin.it/offers/{item.get('id')}",
                        'location': item.get('city'),
                        'is_remote': is_remote
                    })
            return parsed
    except Exception as e:
        print(f"Ошибка парсинга JustJoin: {e}")
    return []

# Главная функция теперь крутится в фоне
def monitor_jobs():
    while True:
        print("Запуск мониторинга...")
        try:
            existing_records = supabase.table('jobs').select('id').execute()
            existing_ids = {item['id'] for item in existing_records.data}

            jobs = []
            jobs.extend(fetch_justjoin_it())

            for job in jobs:
                job_id = str(job['id'])
                if job_id in existing_ids:
                    continue

                score, matches = calculate_score(
                    job['title'], 
                    job['description'], 
                    job['location'], 
                    job['is_remote']
                )

                supabase.table('jobs').insert({'id': job_id, 'url': job['url']}).execute()

                if score >= config.SCORE_THRESHOLD:
                    send_telegram_alert(job, score, matches)
                    
            print("Сбор завершен.")
        except Exception as e:
            print(f"Ошибка во время выполнения: {e}")
            
        print("Ожидание 3 часа...")
        time.sleep(10800)

# Фейковый сервер для заглушки портов Рендера
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running!")

if __name__ == "__main__":
    # 1. Запускаем бесконечный парсинг в отдельном потоке
    task_thread = threading.Thread(target=monitor_jobs)
    task_thread.daemon = True
    task_thread.start()

    # 2. Запускаем сервер-заглушку в основном потоке
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    print(f"Слушаю порт {port} для Render...")
    server.serve_forever()
