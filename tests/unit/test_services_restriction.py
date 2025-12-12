# tests/unit/test_services_restriction.py
"""
Тесты для сервиса сохранения и восстановления ограничений (мутов/банов).

Покрывает:
- Сохранение нового ограничения
- Обновление существующего ограничения
- Получение активного ограничения
- Деактивация ограничения
- Проверка истёкших ограничений
- Восстановление мута через Telegram API
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from bot.services.restriction_service import (
    save_restriction,
    get_active_restriction,
    deactivate_restriction,
    restore_restriction,
    check_and_restore_restriction,
)
from bot.database.models import UserRestriction, Group


# ============================================================
# ФИКСТУРА ДЛЯ СОЗДАНИЯ ГРУППЫ (FK constraint)
# ============================================================

@pytest.fixture
async def test_group(db_session):
    """Создаёт тестовую группу для FK constraint."""
    group = Group(
        chat_id=-1001234567890,
        title="Test Group",
    )
    db_session.add(group)
    await db_session.commit()
    return group


# ============================================================
# ТЕСТЫ ДЛЯ save_restriction
# ============================================================

@pytest.mark.asyncio
async def test_save_restriction_creates_new(db_session, test_group):
    """
    Тест: save_restriction создаёт новую запись если ограничения нет.

    Проверяет что:
    - Создаётся новая запись в БД
    - Все поля заполнены корректно
    - is_active = True по умолчанию
    """
    # Arrange: подготавливаем тестовые данные
    chat_id = test_group.chat_id
    user_id = 123456
    restriction_type = "mute"
    reason = "antispam"
    restricted_by = 999999
    until_date = datetime.now(timezone.utc) + timedelta(hours=24)

    # Act: вызываем функцию сохранения
    result = await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type=restriction_type,
        reason=reason,
        restricted_by=restricted_by,
        until_date=until_date,
    )

    # Assert: проверяем результат
    # Запись должна быть создана
    assert result is not None
    # Поля должны совпадать
    assert result.chat_id == chat_id
    assert result.user_id == user_id
    assert result.restriction_type == restriction_type
    assert result.reason == reason
    assert result.restricted_by == restricted_by
    assert result.is_active is True
    # until_date должен быть близок к заданному (с учётом возможной потери timezone)
    assert result.until_date is not None


@pytest.mark.asyncio
async def test_save_restriction_updates_existing(db_session, test_group):
    """
    Тест: save_restriction обновляет существующее активное ограничение.

    Сценарий:
    1. Создаём мут с причиной "antispam"
    2. Сохраняем новый мут с причиной "content_filter"
    3. Проверяем что запись обновилась, а не создалась новая
    """
    # Arrange: создаём первое ограничение
    chat_id = test_group.chat_id
    user_id = 123456

    first = await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type="mute",
        reason="antispam",
        restricted_by=111,
        until_date=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    first_id = first.id

    # Act: сохраняем второе ограничение для того же юзера
    second = await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type="mute",
        reason="content_filter",
        restricted_by=222,
        until_date=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    # Assert: должен быть тот же ID (обновление, не создание)
    assert second.id == first_id
    # Причина должна обновиться
    assert second.reason == "content_filter"
    # restricted_by тоже
    assert second.restricted_by == 222


@pytest.mark.asyncio
async def test_save_restriction_permanent_mute(db_session, test_group):
    """
    Тест: save_restriction корректно сохраняет бессрочный мут (until_date=None).
    """
    # Act: сохраняем бессрочный мут
    result = await save_restriction(
        session=db_session,
        chat_id=test_group.chat_id,
        user_id=123456,
        restriction_type="mute",
        reason="risk_gate",
        restricted_by=999,
        until_date=None,  # Бессрочно
    )

    # Assert
    assert result.until_date is None
    assert result.is_active is True


# ============================================================
# ТЕСТЫ ДЛЯ get_active_restriction
# ============================================================

@pytest.mark.asyncio
async def test_get_active_restriction_found(db_session, test_group):
    """
    Тест: get_active_restriction возвращает активное ограничение.
    """
    # Arrange: создаём ограничение
    chat_id = test_group.chat_id
    user_id = 123456

    await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type="mute",
        reason="antispam",
        restricted_by=999,
        until_date=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    # Act: получаем активное ограничение
    result = await get_active_restriction(db_session, chat_id, user_id)

    # Assert
    assert result is not None
    assert result.user_id == user_id
    assert result.is_active is True


@pytest.mark.asyncio
async def test_get_active_restriction_not_found(db_session, test_group):
    """
    Тест: get_active_restriction возвращает None если ограничения нет.
    """
    # Act: ищем несуществующее ограничение
    result = await get_active_restriction(
        db_session,
        chat_id=test_group.chat_id,
        user_id=999999,  # Не существует
    )

    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_get_active_restriction_expired(db_session, test_group):
    """
    Тест: get_active_restriction возвращает None для истёкшего ограничения.

    При запросе истёкшего ограничения оно должно быть деактивировано.
    """
    # Arrange: создаём ограничение с истёкшим сроком
    chat_id = test_group.chat_id
    user_id = 123456

    # Устанавливаем дату в прошлом (naive datetime для совместимости)
    past_date = datetime.utcnow() - timedelta(hours=1)

    restriction = await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type="mute",
        reason="antispam",
        restricted_by=999,
        until_date=past_date,
    )

    # Принудительно устанавливаем until_date в прошлое (обходим логику save_restriction)
    restriction.until_date = past_date
    await db_session.commit()

    # Act: запрашиваем ограничение
    result = await get_active_restriction(db_session, chat_id, user_id)

    # Assert: должен вернуть None (истекло)
    assert result is None


# ============================================================
# ТЕСТЫ ДЛЯ deactivate_restriction
# ============================================================

@pytest.mark.asyncio
async def test_deactivate_restriction_success(db_session, test_group):
    """
    Тест: deactivate_restriction деактивирует активное ограничение.
    """
    # Arrange: создаём ограничение
    chat_id = test_group.chat_id
    user_id = 123456

    await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type="mute",
        reason="antispam",
        restricted_by=999,
        until_date=None,
    )

    # Act: деактивируем
    result = await deactivate_restriction(db_session, chat_id, user_id)

    # Assert
    assert result is True

    # Проверяем что ограничение теперь неактивно
    active = await get_active_restriction(db_session, chat_id, user_id)
    assert active is None


@pytest.mark.asyncio
async def test_deactivate_restriction_not_found(db_session, test_group):
    """
    Тест: deactivate_restriction возвращает False если ограничения нет.
    """
    # Act: пытаемся деактивировать несуществующее
    result = await deactivate_restriction(
        db_session,
        chat_id=test_group.chat_id,
        user_id=999999,
    )

    # Assert
    assert result is False


# ============================================================
# ТЕСТЫ ДЛЯ restore_restriction
# ============================================================

@pytest.mark.asyncio
async def test_restore_restriction_mute(db_session, bot_mock):
    """
    Тест: restore_restriction вызывает restrict_chat_member для мута.
    """
    # Arrange: создаём запись об ограничении
    restriction = UserRestriction(
        id=1,
        chat_id=-1001234567890,
        user_id=123456,
        restriction_type="mute",
        reason="antispam",
        restricted_by=999,
        until_date=datetime.now(timezone.utc) + timedelta(hours=24),
        is_active=True,
    )

    # Act: восстанавливаем мут
    result = await restore_restriction(
        bot=bot_mock,
        chat_id=restriction.chat_id,
        user_id=restriction.user_id,
        restriction=restriction,
    )

    # Assert
    assert result is True
    # Проверяем что restrict_chat_member был вызван
    bot_mock.restrict_chat_member.assert_called_once()
    # Проверяем аргументы вызова
    call_args = bot_mock.restrict_chat_member.call_args
    assert call_args.kwargs["chat_id"] == restriction.chat_id
    assert call_args.kwargs["user_id"] == restriction.user_id


@pytest.mark.asyncio
async def test_restore_restriction_ban(db_session, bot_mock):
    """
    Тест: restore_restriction вызывает ban_chat_member для бана.
    """
    # Arrange
    bot_mock.ban_chat_member = AsyncMock()

    restriction = UserRestriction(
        id=1,
        chat_id=-1001234567890,
        user_id=123456,
        restriction_type="ban",
        reason="content_filter",
        restricted_by=999,
        until_date=None,
        is_active=True,
    )

    # Act
    result = await restore_restriction(
        bot=bot_mock,
        chat_id=restriction.chat_id,
        user_id=restriction.user_id,
        restriction=restriction,
    )

    # Assert
    assert result is True
    bot_mock.ban_chat_member.assert_called_once()


# ============================================================
# ТЕСТЫ ДЛЯ check_and_restore_restriction
# ============================================================

@pytest.mark.asyncio
async def test_check_and_restore_restriction_restores_mute(db_session, bot_mock, test_group):
    """
    Тест: check_and_restore_restriction находит и восстанавливает мут.

    Это ключевой тест для исправления бага:
    пользователь был замучен → вышел → зашёл через капчу → мут восстановлен.
    """
    # Arrange: создаём активное ограничение в БД
    chat_id = test_group.chat_id
    user_id = 123456

    await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type="mute",
        reason="antispam",
        restricted_by=999,
        until_date=None,  # Бессрочный мут
    )

    # Act: вызываем проверку и восстановление
    result = await check_and_restore_restriction(
        bot=bot_mock,
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
    )

    # Assert
    # Должно вернуть ограничение
    assert result is not None
    assert result.reason == "antispam"
    # Мут должен быть восстановлен через API
    bot_mock.restrict_chat_member.assert_called_once()


@pytest.mark.asyncio
async def test_check_and_restore_restriction_no_restriction(db_session, bot_mock, test_group):
    """
    Тест: check_and_restore_restriction возвращает None если ограничения нет.
    """
    # Act: проверяем для юзера без ограничений
    result = await check_and_restore_restriction(
        bot=bot_mock,
        session=db_session,
        chat_id=test_group.chat_id,
        user_id=999999,
    )

    # Assert
    assert result is None
    # API не должен вызываться
    bot_mock.restrict_chat_member.assert_not_called()


# ============================================================
# ТЕСТЫ ДЛЯ ИНТЕГРАЦИИ (сценарий бага)
# ============================================================

@pytest.mark.asyncio
async def test_full_scenario_mute_leave_rejoin_restore(db_session, bot_mock, test_group):
    """
    E2E тест полного сценария бага:
    1. Пользователь замучен за спам → мут сохранён в БД
    2. Пользователь выходит из группы
    3. Пользователь заходит через капчу → approve_chat_join_request
    4. После approve проверяем БД → находим мут → восстанавливаем

    Результат: пользователь в группе, но замучен как и был.
    """
    chat_id = test_group.chat_id
    user_id = 123456
    bot_id = 999999

    # ШАГ 1: Антиспам мутит пользователя
    await save_restriction(
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
        restriction_type="mute",
        reason="antispam",
        restricted_by=bot_id,
        until_date=None,  # Навсегда
    )

    # Проверяем что мут сохранён
    restriction = await get_active_restriction(db_session, chat_id, user_id)
    assert restriction is not None
    assert restriction.is_active is True

    # ШАГ 2: Пользователь выходит (ничего не меняется в БД)
    # ... пользователь вышел ...

    # ШАГ 3: Пользователь заходит через капчу
    # approve_chat_join_request снимает все Telegram restrictions
    # Но БД не меняется!

    # ШАГ 4: После approve вызываем check_and_restore_restriction
    restored = await check_and_restore_restriction(
        bot=bot_mock,
        session=db_session,
        chat_id=chat_id,
        user_id=user_id,
    )

    # Assert: мут восстановлен
    assert restored is not None
    assert restored.reason == "antispam"

    # API был вызван для восстановления мута
    bot_mock.restrict_chat_member.assert_called_once()

    # Ограничение всё ещё активно в БД
    still_active = await get_active_restriction(db_session, chat_id, user_id)
    assert still_active is not None
    assert still_active.is_active is True
