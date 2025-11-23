#!/usr/bin/env python3
"""
Универсальный скрипт запуска бота
Можно запускать из любой директории через IDE Play кнопку
"""

import os
import sys
import asyncio
from pathlib import Path

# Получаем абсолютный путь к корню проекта
project_root = Path(__file__).parent.absolute()

# Добавляем корень проекта в sys.path
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Меняем рабочую директорию на корень проекта
os.chdir(project_root)

# Загружаем переменные окружения
try:
    from dotenv import load_dotenv
    # Пробуем загрузить .env.dev, если нет - то .env
    if os.path.exists('.env.dev'):
        load_dotenv('.env.dev')
        print("OK Загружены переменные из .env.dev")
    elif os.path.exists('.env'):
        load_dotenv('.env')
        print("OK Загружены переменные из .env")
    else:
        print("WARNING Файлы .env не найдены, используются системные переменные")
except ImportError:
    print("WARNING python-dotenv не установлен, используются системные переменные")

# Импортируем и запускаем бота
try:
    from bot.bot import main
    print("START Запуск бота...")
    asyncio.run(main())
except KeyboardInterrupt:
    print("\nSTOP Бот остановлен пользователем")
except Exception as e:
    print(f"ERROR Ошибка запуска бота: {e}")
    sys.exit(1)



    