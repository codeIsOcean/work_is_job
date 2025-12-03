#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Универсальный скрипт запуска бота
Можно запускать из любой директории через IDE Play кнопку
"""

import os
import sys
import asyncio
from pathlib import Path

# ============================================================
# ИСПРАВЛЕНИЕ КОДИРОВКИ ДЛЯ WINDOWS
# ============================================================
# Windows по умолчанию использует кодировку 'charmap' (cp1251/cp866)
# которая не поддерживает эмодзи и многие unicode символы.
# Устанавливаем UTF-8 для корректного отображения логов с эмодзи.
if sys.platform == 'win32':
    # Настраиваем кодировку для stdin/stdout/stderr
    sys.stdin.reconfigure(encoding='utf-8') if hasattr(sys.stdin, 'reconfigure') else None
    sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
    sys.stderr.reconfigure(encoding='utf-8') if hasattr(sys.stderr, 'reconfigure') else None

    # Устанавливаем переменную окружения для всех подпроцессов
    os.environ['PYTHONIOENCODING'] = 'utf-8'

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



    