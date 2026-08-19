import os
import re
import time
import requests
from supabase import create_client, Client
import config

# Инициализация клиентов (Render берет их из Environment Variables)
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

    # 1. Минус-слова
    for neg in config.KEYWORDS["negative"]:
        if re.search(r'\b' + re.escape(neg) + r'\b', full_text):
            return -100, []

    # 2. Основные навыки
    for kw in config.KEYWORDS["primary"]:
        if re.search(r'\b' + re.escape(kw) + r'\b', full_text):
            score += 20
            matched_skills.append(kw)

    # 3. Вторичные навыки
    for kw in config.KEYWORDS["secondary"]:
        if re.search(r'\b' + re.escape(kw) + r'\b', full_text):
            score += 10
            matched_skills.append(kw)

    # 4. Локация / Удаленка
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

def main():
    print("Собираю вакансии...")
    try:
        # Получаем уже сохраненные ID
        existing_records = supabase.table('jobs').select('id').execute()
        existing_ids = {item['id'] for item in existing_records.data}

        # Парсинг
        jobs = []
        jobs.extend(fetch_justjoin_it())

        # Фильтрация и отправка
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

            # Сохраняем в Supabase
            supabase.table('jobs').insert({'id': job_id, 'url': job['url']}).execute()

            # Отправляем в Telegram
            if score >= config.SCORE_THRESHOLD:
                send_telegram_alert(job, score, matches)
                
        print("Сбор завершен.")
    except Exception as e:
        print(f"Ошибка во время выполнения: {e}")

if __name__ == "__main__":
    while True:
        print("Запуск мониторинга...")
        main()
        print("Ожидание 3 часа...")
        time.sleep(10800)
