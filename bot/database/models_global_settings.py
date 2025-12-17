# bot/database/models_global_settings.py
"""
Глобальные настройки бота (не привязанные к конкретной группе).

Используется для хранения:
- max_seen_user_id - максимальный ID пользователя для расчёта возраста аккаунтов
- Другие глобальные параметры
"""

from sqlalchemy import Column, BigInteger, String, DateTime, Text
from sqlalchemy.sql import func

from bot.database.models import Base


class BotGlobalSettings(Base):
    """
    Таблица для хранения глобальных настроек бота.

    Формат key-value для гибкости.
    """
    __tablename__ = "bot_global_settings"

    key = Column(String(100), primary_key=True, comment="Уникальный ключ настройки")
    value = Column(Text, nullable=False, comment="Значение настройки")
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="Время последнего обновления"
    )

    def __repr__(self):
        return f"<BotGlobalSettings(key={self.key}, value={self.value})>"


# Константы для ключей
class GlobalSettingKeys:
    """Константы ключей глобальных настроек"""
    MAX_SEEN_USER_ID = "max_seen_user_id"
