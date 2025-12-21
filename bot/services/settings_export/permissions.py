# ============================================================
# ПРОВЕРКА ПРАВ ДОСТУПА ДЛЯ ЭКСПОРТА/ИМПОРТА НАСТРОЕК
# ============================================================
# Этот модуль реализует проверку прав:
# - Владелец группы (creator) → полный доступ
# - Администратор со ВСЕМИ правами → полный доступ
# - Остальные → доступ запрещён
#
# Это защищает настройки от копирования неавторизованными лицами
# ============================================================

# Импортируем стандартные библиотеки
import logging
from typing import Optional, Tuple

# Импортируем типы и классы aiogram
from aiogram import Bot
from aiogram.types import ChatMemberOwner, ChatMemberAdministrator, ChatMember
from aiogram.exceptions import TelegramAPIError

# Создаём логгер для отслеживания проверок прав
logger = logging.getLogger(__name__)


# ============================================================
# ПРОВЕРКА: ЯВЛЯЕТСЯ ЛИ ПОЛЬЗОВАТЕЛЬ ВЛАДЕЛЬЦЕМ
# ============================================================

async def is_chat_owner(
    bot: Bot,
    chat_id: int,
    user_id: int,
) -> bool:
    """
    Проверяет, является ли пользователь владельцем (creator) группы.

    Args:
        bot: Экземпляр бота для API запросов
        chat_id: ID группы
        user_id: ID пользователя для проверки

    Returns:
        True если пользователь является владельцем
    """
    try:
        # Получаем информацию о членстве пользователя в чате
        member = await bot.get_chat_member(chat_id, user_id)

        # Проверяем статус: creator = владелец
        is_owner = isinstance(member, ChatMemberOwner)

        # Логируем результат
        if is_owner:
            logger.debug(f"✅ [PERMISSIONS] user_id={user_id} является владельцем chat_id={chat_id}")

        return is_owner

    except TelegramAPIError as e:
        # Ошибка API (пользователь не в группе, группа не найдена, etc.)
        logger.warning(f"⚠️ [PERMISSIONS] Ошибка проверки владельца: {e}")
        return False


# ============================================================
# ПРОВЕРКА: ИМЕЕТ ЛИ ПОЛЬЗОВАТЕЛЬ ВСЕ ПРАВА АДМИНА
# ============================================================

async def has_full_admin_rights(
    bot: Bot,
    chat_id: int,
    user_id: int,
) -> bool:
    """
    Проверяет, имеет ли администратор ВСЕ права в группе.

    Требуемые права для full admin:
    - can_manage_chat: Управление чатом (базовое право админа)
    - can_delete_messages: Удаление сообщений
    - can_restrict_members: Ограничение участников (мут, бан)
    - can_promote_members: Назначение других администраторов
    - can_change_info: Изменение информации о группе
    - can_invite_users: Приглашение пользователей

    Args:
        bot: Экземпляр бота для API запросов
        chat_id: ID группы
        user_id: ID пользователя для проверки

    Returns:
        True если пользователь имеет ВСЕ права администратора
    """
    try:
        # Получаем информацию о членстве пользователя в чате
        member = await bot.get_chat_member(chat_id, user_id)

        # Владелец автоматически имеет все права
        if isinstance(member, ChatMemberOwner):
            logger.debug(f"✅ [PERMISSIONS] user_id={user_id} - владелец, полные права")
            return True

        # Для администратора проверяем каждое право
        if isinstance(member, ChatMemberAdministrator):
            # Список всех требуемых прав
            required_rights = [
                ('can_manage_chat', member.can_manage_chat),
                ('can_delete_messages', member.can_delete_messages),
                ('can_restrict_members', member.can_restrict_members),
                ('can_promote_members', member.can_promote_members),
                ('can_change_info', member.can_change_info),
                ('can_invite_users', member.can_invite_users),
            ]

            # Проверяем что ВСЕ права включены
            all_rights = all(value for name, value in required_rights)

            # Если не все права - логируем какие отсутствуют
            if not all_rights:
                missing = [name for name, value in required_rights if not value]
                logger.debug(
                    f"❌ [PERMISSIONS] user_id={user_id} не имеет прав: {missing}"
                )
            else:
                logger.debug(f"✅ [PERMISSIONS] user_id={user_id} имеет полные права админа")

            return all_rights

        # Не владелец и не админ
        return False

    except TelegramAPIError as e:
        # Ошибка API
        logger.warning(f"⚠️ [PERMISSIONS] Ошибка проверки прав: {e}")
        return False


# ============================================================
# КОМБИНИРОВАННАЯ ПРОВЕРКА: ВЛАДЕЛЕЦ ИЛИ ПОЛНЫЙ АДМИН
# ============================================================

async def can_export_import_settings(
    bot: Bot,
    chat_id: int,
    user_id: int,
) -> Tuple[bool, Optional[str]]:
    """
    Проверяет, может ли пользователь экспортировать/импортировать настройки.

    Разрешено только:
    - Владельцу группы (creator)
    - Администратору со ВСЕМИ правами

    Args:
        bot: Экземпляр бота для API запросов
        chat_id: ID группы
        user_id: ID пользователя для проверки

    Returns:
        Tuple[bool, Optional[str]]:
        - (True, None) если доступ разрешён
        - (False, "причина") если доступ запрещён
    """
    try:
        # Получаем информацию о членстве пользователя в чате
        member = await bot.get_chat_member(chat_id, user_id)

        # Проверяем статус владельца
        if isinstance(member, ChatMemberOwner):
            logger.info(
                f"✅ [PERMISSIONS] Экспорт/импорт разрешён для владельца: "
                f"user_id={user_id}, chat_id={chat_id}"
            )
            return True, None

        # Проверяем статус администратора с полными правами
        if isinstance(member, ChatMemberAdministrator):
            # Проверяем все необходимые права
            has_full_rights = await has_full_admin_rights(bot, chat_id, user_id)

            if has_full_rights:
                logger.info(
                    f"✅ [PERMISSIONS] Экспорт/импорт разрешён для полного админа: "
                    f"user_id={user_id}, chat_id={chat_id}"
                )
                return True, None
            else:
                # Админ, но не со всеми правами
                return False, "Для экспорта/импорта требуются ВСЕ права администратора"

        # Не владелец и не админ
        return False, "Только владелец или администратор со всеми правами может экспортировать настройки"

    except TelegramAPIError as e:
        # Ошибка API (пользователь не в группе, группа не найдена)
        logger.warning(f"⚠️ [PERMISSIONS] Ошибка проверки прав: {e}")
        return False, f"Ошибка проверки прав: {e}"


# ============================================================
# ПОЛУЧЕНИЕ ИНФОРМАЦИИ О ПРАВАХ ПОЛЬЗОВАТЕЛЯ
# ============================================================

async def get_user_permissions_info(
    bot: Bot,
    chat_id: int,
    user_id: int,
) -> dict:
    """
    Получает подробную информацию о правах пользователя в группе.

    Используется для отображения в UI какие права есть/отсутствуют.

    Args:
        bot: Экземпляр бота для API запросов
        chat_id: ID группы
        user_id: ID пользователя

    Returns:
        Словарь с информацией о правах:
        {
            'is_owner': bool,
            'is_admin': bool,
            'rights': {'can_manage_chat': True, ...},
            'missing_rights': ['can_promote_members', ...],
            'can_export_import': bool,
        }
    """
    # Результирующий словарь
    result = {
        'is_owner': False,
        'is_admin': False,
        'rights': {},
        'missing_rights': [],
        'can_export_import': False,
    }

    try:
        # Получаем информацию о членстве
        member = await bot.get_chat_member(chat_id, user_id)

        # Проверяем владельца
        if isinstance(member, ChatMemberOwner):
            result['is_owner'] = True
            result['can_export_import'] = True
            return result

        # Проверяем администратора
        if isinstance(member, ChatMemberAdministrator):
            result['is_admin'] = True

            # Собираем информацию о правах
            rights_to_check = [
                'can_manage_chat',
                'can_delete_messages',
                'can_restrict_members',
                'can_promote_members',
                'can_change_info',
                'can_invite_users',
            ]

            for right in rights_to_check:
                # Получаем значение права
                has_right = getattr(member, right, False)
                result['rights'][right] = has_right

                # Если права нет - добавляем в missing
                if not has_right:
                    result['missing_rights'].append(right)

            # Проверяем можно ли экспортировать
            result['can_export_import'] = len(result['missing_rights']) == 0

        return result

    except TelegramAPIError as e:
        logger.warning(f"⚠️ [PERMISSIONS] Ошибка получения прав: {e}")
        return result
