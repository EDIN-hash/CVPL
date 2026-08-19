# Порог Match Score для отправки в Telegram (от 0 до 100)
SCORE_THRESHOLD = 0

# Обязательный город или формат
TARGET_CITY = "poznań"

KEYWORDS = {
    # Скиллы/стек (+20 баллов каждый)
    "primary": [
        "python", "c#", "javascript", "react", "postgresql", 
        "appsheet", "sql", "qa", "automation", "testing"
    ],
    # Вспомогательные технологии (+10 баллов)
    "secondary": [
        "git", "docker", "rest api", "json", "html", "css", "unity"
    ],
    # Минус-слова (-100 баллов, сразу отсекают вакансию)
    "negative": [
        "senior", "lead", "principal", "architect", 
        "5+ years", "5+ lat", "10+ years"
    ]
}
