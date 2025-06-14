# AgroAI Telegram Bot

**AgroAI** — интеллектуальный помощник для агропромышленности, автоматизирующий сбор и обработку полевых отчетов через Telegram-бота.

## 🎯 Решаемая проблема

Агрономы ежедневно отправляют множество сообщений с отчетами о проделанной работе в свободной текстовой форме или фотографиями таблиц. Ручная обработка таких данных:
- Занимает значительное время
- Содержит человеческие ошибки
- Затрудняет оперативный анализ

**@test_AgroAI_bot** решает эти проблемы, автоматически извлекая и структурируя ключевую информацию из сообщений.

## ✨ Основные возможности

### 🤖 Основной функционал
- Автоматический сбор отчетов из групповых чатов
- Обработка текстовых сообщений (обработка через YandexGPT)
- Удобное представление структурированных данных

### Требуемые API ключи
Создайте файл `config.py` со следующим содержимым:

```
# Настройки OpenAI
YANDEX_API_KEY="ваш_ключ"
TELEGRAM_TOKEN="ваш телеграм-бот"
YC_FOLDER_ID="айди папки яндекс клауд"
GOOGLE_SHEETS_CREDS = "имя джсон для гугл апи"
YC_API_KEY = "oauth ключ яндекс"

# SPREADSHEET_KEY = "адрес гугл таблицы"
# GOOGLE_DRIVE_FOLDER_ID = "адрес папки гугл драйв""
SPREADSHEET_KEY = "адрес гугл таблицы"
GOOGLE_DRIVE_FOLDER_ID = "адрес папки гугл драйв"
```

### 🚀 Быстрый старт
1. Добавьте бота в рабочую группу
2. Пригласите @test_AgroAI_bot в Telegram-чат
3. Назначьте бота администратором группы
4. Установите и запустите бота

bash
### Создание виртуального окружения
python -m venv .venv

### Активация окружения
### Windows:
.venv/Scripts/activate
### Unix-системы:
source .venv/bin/activate

### Установка зависимостей
pip install -r requirements.txt

### Запуск бота
python main.py

### Готово! Бот настроен и готов к работе. Для начала просто отправьте ему сообщение с полевым отчетом в любом формате.
