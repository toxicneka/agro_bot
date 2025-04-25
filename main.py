from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message
import asyncio
import aiohttp
import logging
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from io import BytesIO

# Добавляем новые импорты и настройки
import os
from collections import defaultdict

COUNTERS_FILE = 'counters.txt'

from config import (
    TELEGRAM_TOKEN, 
    YC_API_KEY, 
    YC_FOLDER_ID,
    GOOGLE_SHEETS_CREDS,
    SPREADSHEET_KEY,
    GOOGLE_DRIVE_FOLDER_ID
)

# Глобальная переменная для хранения текущего IAM-токена
current_iam_token = None
message_counters = defaultdict(int)

# Настройка Google Sheets
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEETS_CREDS, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_KEY).sheet1
drive_service = build('drive', 'v3', credentials=creds)

# Функция для сохранения счетчиков в файл
def save_counters():
    with open(COUNTERS_FILE, 'w', encoding='utf-8') as f:
        for user_id, count in message_counters.items():
            f.write(f"{user_id},{count}\n")

# Изменяем функцию загрузки счетчиков
def load_counters():
    if os.path.exists(COUNTERS_FILE):
        with open(COUNTERS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    user_id, count = line.strip().split(',')
                    message_counters[int(user_id)] = int(count)
                except ValueError:
                    logger.warning(f"Некорректная строка в файле счетчика: {line}")
                
# Вызываем загрузку при старте
load_counters()

# Функция для создания файла в Google Drive
async def save_to_drive(content: str, filename: str, folder_id: str):
    try:
        file_metadata = {
            'name': filename,
            'parents': [folder_id],
            'mimeType': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        
        # Создаем временный файл в памяти
        file_content = BytesIO(content.encode('utf-8'))
        media = MediaIoBaseUpload(file_content, 
                                mimetype='text/plain',
                                resumable=True)
        
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        return True
    except Exception as e:
        logger.error(f"Ошибка сохранения в Google Drive: {str(e)}")
        return False

# Проверка и создание заголовков таблицы
header = sheet.row_values(1)
if not header:
    sheet.append_row([
        "Дата",
        "Подразделение", 
        "Операция", 
        "Культура", 
        "За день, га", 
        "С начала операции, га"
    ])

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_new_iam_token():
    headers = {
        "Content-Type": "application/json"
    }
    
    data = {
        "yandexPassportOauthToken": YC_API_KEY
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://iam.api.cloud.yandex.net/iam/v1/tokens",
                headers=headers,
                json=data,
                timeout=10
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    logger.error(f"IAM token error: {response.status} - {error}")
                    return None
                
                result = await response.json()
                return result.get('iamToken')
                
    except Exception as e:
        logger.error(f"Ошибка получения IAM-токена: {str(e)}")
        return None

async def refresh_iam_token(interval: int = 3600):
    """Обновляет IAM-токен каждые interval секунд"""
    global current_iam_token
    
    while True:
        new_token = await get_new_iam_token()
        if new_token:
            current_iam_token = new_token
            logger.info("IAM-токен успешно обновлен")
        else:
            logger.error("Не удалось обновить IAM-токен")
        
        await asyncio.sleep(interval)

# Загрузка названий участков из areas.txt
def load_areas(filename="areas.txt"):
    """Загружаем возможные операции из файла"""
    with open(filename, encoding='utf-8') as file:
        return [line.strip() for line in file]

AREAS = load_areas()

# Загрузка названий операций из operations.txt
def load_operations(filename="operations.txt"):
    """Загружаем возможные операции из файла"""
    with open(filename, encoding='utf-8') as file:
        return [line.strip() for line in file]

OPERATIONS = load_operations()

# Загрузка названий культур из cultures.txt
def load_culture_rules():
    try:
        with open('cultures.txt', 'r', encoding='utf-8') as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error("Файл cultures.txt не найден. Используются стандартные правила.")
        return """
        Вика+Тритикале
        Горох на зерно
        Горох товарный
        Гуар
        Конопля
        Кориандр
        Кукуруза кормовая
        Кукуруза семенная
        Кукуруза товарная
        Люцерна
        Многолетние злаковые травы
        Многолетние травы прошлых лет
        Многолетние травы текущего года
        Овес
        Подсолнечник кондитерский
        Подсолнечник семенной
        Подсолнечник товарный
        Просо
        Пшеница озимая на зеленый корм
        Пшеница озимая семенная
        Пшеница озимая товарная
        Рапс озимый
        Рапс яровой
        Свекла сахарная
        Сорго
        Сорго кормовой
        Сорго-суданковый гибрид
        Соя семенная
        Соя товарная
        Чистый пар
        Чумиза
        Ячмень озимый
        Ячмень озимый семенной
        """
    except Exception as e:
        logger.error(f"Ошибка при чтении cultures.txt: {str(e)}")
        return ""

CULTURE_RULES = load_culture_rules()

async def expand_abbreviations(text: str) -> str:
    if not current_iam_token:
        return "Ошибка: IAM-токен не инициализирован"
    
    system_prompt = f"""
    Ты — высококласнный опытный агроном, который расшифровывает сокращённые названия производственного участка, сельскохозяйственных операций, культур, га вспаханные за день и га с начала операции. 

    Строго соблюдай эти правила:
    
    0. Всегда используй СТРОГО ТОЛЬКО эти списки для итогового вывода ПРОИЗВОДСТВЕННЫЙ УЧАСТОК, ОПЕРАЦИЯ и КУЛЬТУРА:
    {AREAS}
    {OPERATIONS}
    {CULTURE_RULES}

    1. Подготовка данных:
    - Если дата указана В НАЧАЛЕ один раз внутри всего сообщения, то это означает, что используется та же ДАТА для всех операции и надо его вписывать
    - Если там указана дата, то СТРОГО впиши в формате день.месяц.год, где . является разделителем внутри даты
    - Оставь дату 00.00.00, если нет никакой даты внутри сообщения (не путать с га)
    - Полностью строго ИГНОРИРУЙ числа, которые связаны с ОСТАТОК, например "Остаток 5763 га"
    - Полностью строго ИГНОРИРУЙ тексты идущие после символа процента, например "131га (3%) Остаток 448 га Осадки 1мм" строго рассматривай как "131га (3%)"

    2. Обработка АОР (особое правило):
    - Все номера ПУ/Отд → всегда заменяй на "АОР"
    - Все названия Производственных участков из этого списка → всегда заменяй на "АОР": Кавказ, Север, Центр, Юг, Рассвет
    - Примеры преобразований: "Отд 12" → "АОР" | "ПУ 7" → "АОР" | "Пу19" → "АОР" | "Кавказ" → "АОР" | "Рассвет" → "АОР" | "Юг" → "АОР"
    
    3. Стандартные преобразования:
    - Дата может быть указана с годом или без года, если без года, то это означает, что используется текущий год
    - Из первых строк расшифруй производственный участок, строго выбирая из списка производственных участков и сохрани название данного производственного участка строго для всех операций и культур при выходе!
    - Для каждой строки определяй выполняемую операцию и тип культуры
    - Операции, которые записаны в виде короткого обозначения, тебе нужно правильно определить операцию среди списка {OPERATIONS} возможных вариантов
    - Если операция указана неполностью, постарайся восстановить полностью её из контекста, строго выбирая операцию из списка операций {OPERATIONS}
    - Если в сокращении не указан тип культуры, выбирай именно тип ТОВАРНЫЙ/ТОВАРНАЯ обязательно
    - Если культура определена "Кукуруза" и его тип не указан, СТРОГО выбирай "Кукуруза товарная"
    - Если культура определена "Кукуруза" и есть слово "на зерно", СТРОГО значит выбирай "Кукуруза товарная"
    - Если культура определена "Кукуруза" и есть слово "cилос", СТРОГО значит выбирай "Кукуруза кормовая"
    - Если культура определена "Многолетние травы" и его тип не указан, выбирай по умолчанию "Многолетние травы текущего года"
    - Поддерживай порядок строк исходного ввода
    - Выводи только полные официальные названия из списка Производственный участок: {AREAS}, Операции: {OPERATIONS}, Культура {CULTURE_RULES}
    - Никаких дополнительных комментариев, только дата (если есть), список и числа для га
    - Никаких процентов
    - га имеет только числовые значение
    - если числовое значение га имеет четыре символа, то строго добавь символ запятого после первого символа числового значения га, например число значение га "1234га" строго брать как "1,234"

    4. ОСОБЫЕ указания:
    - Игнорируй любые культуры, которых нет в списке {CULTURE_RULES}
    - Игнорируй любые операции, которых нет в списке {OPERATIONS}
    - Сохраняй оригинальные названия из списка (кормовая, сахарная и т.д.)
    - Учитывай падежи и сокращения: "сои" → "Соя товарная", "к.корм" → "Кукуруза кормовая"
    

    Пример преобразований для производственного участка с другими данными:
    [Ввод]     -> [Вывод]
    Восход Посев кук-24/252га24% -> Восход; Сев; Кукуруза товарная; 24; 252
    Предпосевная культ Под кук-94/490га46% -> Восход; Предпосевная культивация; Кукуруза товарная; 94; 490
    Пахота зяби под мн тр По Пу 26/488 -> АОР; Пахота; Многолетние травы текущего года; 26; 488

    Примеры преобразований для операций:
    [Ввод]     -> [Вывод]
    СЗР        -> Гербицидная обработка

    Примеры преобразований для культур:
    [Ввод]     -> [Вывод]
    соя        -> Соя товарная
    кук        -> Кукуруза товарная
    кук сил    -> Кукуруза кормовая
    кукуруза на зерно -> Кукуруза товарная
    гор        -> Горох товарный
    пшеница    -> Пшеница озимая товарная
    ячмень     -> Ячмень товарный
    сах        -> Свекла сахарная
    оз пш      -> Пшеница озимая товарная
    подсол     -> Подсолнечник товарный
    мн тр      -> Многолетние травы текущего года

    Примеры преобразований для культур, га вспаханные за день и га с начала операции:
    [Ввод]                     -> [Вывод]
    под сою 24/252га24%                -> Соя товарная; 24; 252
    под сою 152га , 100%               -> Соя товарная; 152; 152
    под сою 53/1816                    -> Соя товарная; 53; 1,816
    под сою 53/181                     -> Соя товарная; 53; 181
    под сою 1523га , 100%              -> Соя товарная; 1,523; 1,523
    под сою 1523га , (100%)              -> Соя товарная; 1,523; 1,523
    под кукурузу 131га 3% Остаток 448 га Осадки 1мм -> Кукуруза товарная; 131; 131
    под кукурузу 131га (3%) Остаток 448 га Осадки 1мм -> Кукуруза товарная; 131; 131
    под сою 152га , 100% Остаток 448 га Осадки 1мм              -> Соя товарная; 152; 152
    под мн тр По Пу 26га -> Многолетние травы текущего года; 26; 26
    под подсолнечник: День - 50 га От начала - 1260 га (30%) Остаток - 2923 га -> Подсолнечник товарный; 50; 1260
    под мн тр По Пу 26/488 Отд 12 26/221 -> Многолетние травы текущего года; 26; 488
    
    Примеры преобразований для производственного участка, операций, культур, га вспаханные за день и га с начала операции:
    [Ввод]                     -> [Вывод]
    Предп культ под оз пш По Пу 91/1403 Отд 11 45/373 Отд 12 46/363 -> АОР; Предпосевная культивация; Пшеница озимая товарная; 91; 1403
    Внесение мин удобрений под оз пшеницу 2025 г ПУ Юг 149/7264 Отд 17-149/1443 -> АОР; Внесение минеральных удобрений; Пшеница озимая товарная; 149; 7264
    2-е диск сои под оз пш По Пу 82/1989 Отд 11 82/993 -> АОР; Дискование 2-е; Пшеница озимая товарная; 82; 1989
    диск сах св По Пу 70/1004 Отд 17 70/302 -> АОР; Дискование; Свекла сахарная; 70; 1004

    "Каждый отдельный отчет должен быть на новой строки без дополнительных символов\n"
    "Пример многострочного вывода:\n"
    "12.12.2024; Восход; Сев. Кукуруза товарная; 24; 252\n"
    "Восход; Пахота; Подсолнечник товарный; 150; 300\n"
    "12.12; Центр; Обработка; Соя товарная; 75; 400"
    
    Итоговый ответ должен быть строго таков: Дата; Производственный участок; Операция; Культура; За день; С начала операции
    """

    headers = {
        "Authorization": f"Bearer {current_iam_token}",
        "Content-Type": "application/json"
    }
    
    data = {
        "modelUri": f"gpt://{YC_FOLDER_ID}/yandexgpt",
        "completionOptions": {
            "temperature": 0.3,
            "maxTokens": 2000
        },
        "messages": [
            {"role": "system", "text": system_prompt},
            {"role": "user", "text": text}
        ]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                headers=headers,
                json=data,
                timeout=30
            ) as response:
                
                if response.status != 200:
                    error = await response.text()
                    logger.error(f"API error: {response.status} - {error}")
                    return "Ошибка обработки запроса"
                
                result = await response.json()
                return result['result']['alternatives'][0]['message']['text']
                
    except Exception as e:
        logger.error(f"Ошибка: {str(e)}")
        return "Ошибка при обработке запроса"

router = Router()

async def write_to_sheet(data: list):
    try:
        sheet.append_row(data)
        return True
    except Exception as e:
        logger.error(f"Ошибка записи в таблицу: {str(e)}")
        return False

def parse_date(date_str: str) -> str:
    """Парсит дату в формате DD/MM или DD/MM/YY и возвращает в формате DD/MM/YYYY"""
    # Если дата 00.00.00, возвращаем текущую дату
    if date_str.strip() == "00.00.00":
        return datetime.now().strftime("%d/%m/%Y")
    
    if not date_str.strip():
        return datetime.now().strftime("%d/%m/%Y")
    
    try:
        # Удаляем возможные точки и заменяем на слеши
        date_str = date_str.replace(".", "/").strip()
        
        parts = date_str.split("/")
        if len(parts) == 2:  # DD/MM
            day, month = parts
            year = datetime.now().year
            return f"{int(day):02d}/{int(month):02d}/{year}"
        elif len(parts) == 3:  # DD/MM/YY
            day, month, year = parts
            # Преобразуем двухзначный год в четырехзначный
            year = int(year)
            if year < 100:
                year = 2000 + year
            return f"{int(day):02d}/{int(month):02d}/{year}"
        else:
            return datetime.now().strftime("%d/%m/%Y")
    except (ValueError, IndexError):
        return datetime.now().strftime("%d/%m/%Y")

@router.message(F.content_type == "text")
async def handle_message(message: Message):
    global message_counters
    
    # Сохраняем оригинальное сообщение
    original_text = message.text
    is_flood = False  # Флаг для определения флуда
    
    # Увеличиваем счетчик только один раз для всего сообщения
    user_id = message.from_user.id
    message_counters[user_id] += 1
    save_counters()
    
    # Обработка сообщения
    expanded_text = await expand_abbreviations(original_text)
    print(expanded_text)
    
    # Разделяем ответ на отдельные строки
    lines = [line.strip() for line in expanded_text.split('\n') if line.strip()]
    
    successful = 0
    errors = 0
    error_details = []
    total_flood_lines = 0  # Счетчик флуд-строк
    
    # Обрабатываем каждую строку отдельно
    for i, line in enumerate(lines, 1):
        parts = [part.strip() for part in line.split(';')]
        
        # Проверка на флуд: если больше двух "-"
        flood_indicator = any(
            part.strip() in ('—', '-', '–', '−')
            for part in parts
        )
        
        if flood_indicator and len(parts) >= 3:
            total_flood_lines += 1
            error_details.append(f"Строка {i}: Обнаружен флуд-формат")
            errors += 1
            continue
        
        # Проверяем количество компонентов
        if len(parts) < 5:
            error_details.append(f"Строка {i}: Неверное количество элементов ({len(parts)} вместо 5-6)")
            errors += 1
            print(parts)
            continue
        
        try:
            # Пытаемся определить дату из первой части
            date_str = ""
            unit_part = 0
            culture_part = 2
            
            # Проверяем, является ли первая часть датой (содержит разделитель)
            if "." in parts[0]:
                date_str = parse_date(parts[0])
                unit_part = 1
                culture_part = 3
            else:
                date_str = datetime.now().strftime("%d/%m/%Y")
                unit_part = 0
                culture_part = 2
            
            # Проверяем, есть ли достаточно частей для всех данных
            if len(parts) < culture_part + 2:
                error_details.append(f"Строка {i}: Недостаточно данных после определения даты")
                errors += 1
                continue
            
            # Формируем данные для записи
            report_data = [
                date_str,  # Дата из сообщения или текущая
                parts[unit_part],    # Производственный участок
                parts[unit_part+1],  # Операция
                parts[culture_part],  # Культура
                parts[culture_part+1],  # За день (заменяем запятую на точку)
                parts[culture_part+2]   # Всего (заменяем запятую на точку)
            ]
            
            # Дополнительная проверка на пустые значения
            if any(val in ('—', '-', '–', '−', '') for val in report_data[1:4]):
                error_details.append(f"Строка {i}: Обнаружены пустые значения в основных полях")
                errors += 1
                continue
            
            # Запись в таблицу
            if await write_to_sheet(report_data):
                successful += 1
            else:
                errors += 1
                error_details.append(f"Строка {i}: Ошибка записи в таблицу")
                
        except ValueError as e:
            errors += 1
            error_details.append(f"Строка {i}: Ошибка преобразования чисел - {str(e)}")
        except Exception as e:
            errors += 1
            error_details.append(f"Строка {i}: Неизвестная ошибка - {str(e)}")
            logger.error(f"Ошибка в строке {i}: {str(e)}")
    
    # Проверка на полный флуд (все строки флуд)
    if total_flood_lines >= len(lines) and len(lines) > 0:
        is_flood = True
        successful = 0
        errors = len(lines)
        error_details.append("Обнаружен полный флуд во всех строках")
    
    # Формируем итоговый отчет
    result_message = f"✅ Успешно записано: {successful}\n❌ Ошибок: {errors}"
    if error_details:
        result_message += "\n\nДетали ошибок:\n" + "\n".join(error_details)
    
    # Сохранение в Google Drive
    if successful > 0 and not is_flood:
        now = datetime.now()
        filename_time = now.strftime("%M%H%d%m%Y")
        filename = f"{message.from_user.first_name}_{message_counters[user_id]}_{filename_time}"
        
        success = await save_to_drive(
            content=original_text,
            filename=f"{filename}.doc",
            folder_id=GOOGLE_DRIVE_FOLDER_ID
        )
        
        if not success:
            result_message += "\n\n⚠️ Не удалось сохранить в Google Drive"
    
    # Сбрасываем счетчик если обнаружен флуд
    if is_flood:
        message_counters[user_id] -= 1
        save_counters()
    
    # Отправляем результат
    # await message.answer(result_message)
    print(result_message)

async def main():
    # Инициализируем токен при старте
    global current_iam_token
    current_iam_token = await get_new_iam_token()
    
    if not current_iam_token:
        logger.error("Не удалось получить начальный IAM-токен")
        return
    bot = Bot(token=TELEGRAM_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)
    
    # Запускаем фоновую задачу для обновления токена
    asyncio.create_task(refresh_iam_token(3600))

if __name__ == "__main__":
    asyncio.run(main())