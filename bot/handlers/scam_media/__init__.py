# ============================================================
# ОБРАБОТЧИКИ SCAM MEDIA FILTER
# ============================================================
# Этот модуль содержит aiogram handlers для фильтра скам-фото:
# - filter_handler.py: проверка входящих сообщений с фото
# - commands_handler.py: команды /mutein, /banin, /scamrm
# - settings_handler.py: UI настроек в ЛС
# - callbacks_handler.py: обработка inline кнопок
#
# Интеграция:
# - filter_handler вызывается из group_message_coordinator
# - Остальные handlers регистрируются отдельно
# ============================================================

# Экспортируем функцию проверки сообщений
from .filter_handler import check_message_for_scam_media
