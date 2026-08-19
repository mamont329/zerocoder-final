# FinControl

Сервис учёта личных финансов: веб-интерфейс на Django и Telegram-бот.
Позволяет вести доходы и расходы, смотреть аналитику по категориям и периодам,
получать советы и предупреждения о превышении лимитов.

## Стек

- Python 3.13, Django 6.1
- SQLite
- pandas, plotly — аналитика и графики
- aiogram — Telegram-бот
- Bootstrap — вёрстка

## Запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux / macOS

pip install -r requirements.txt

cp .env.example .env            # и заполнить SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Сайт: http://127.0.0.1:8000/, админка: http://127.0.0.1:8000/admin/

## Структура

| Путь | Назначение |
| --- | --- |
| `fincontrol/` | Настройки проекта, корневые URL |
| `finance/` | Приложение учёта финансов: модели, представления, шаблоны |
| `docs/` | Техническое задание |
