# ============================================================
# UNIT-ТЕСТЫ ДЛЯ CUSTOMSECTIONSERVICE
# ============================================================
# Тестирует CRUD операции для кастомных разделов спама
# и их паттернов (CustomSpamSection, CustomSectionPattern).
# ============================================================

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Group
from bot.database.models_content_filter import (
    CustomSpamSection,
    CustomSectionPattern,
)
from bot.services.content_filter.scam_pattern_service import (
    CustomSectionService,
    get_section_service,
)


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def section_service() -> CustomSectionService:
    """Создаёт экземпляр сервиса для тестов."""
    return CustomSectionService()


@pytest.fixture
async def test_group(db_session: AsyncSession) -> Group:
    """Создаёт тестовую группу в БД."""
    group = Group(
        chat_id=-1001234567890,
        title="Test Group",
    )
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


@pytest.fixture
async def test_section(
    db_session: AsyncSession,
    test_group: Group,
    section_service: CustomSectionService
) -> CustomSpamSection:
    """Создаёт тестовый раздел спама."""
    success, section_id, error = await section_service.create_section(
        chat_id=test_group.chat_id,
        name="Такси",
        description="Реклама такси",
        threshold=50,
        action="delete",
        session=db_session,
        created_by=123456789
    )
    assert success, f"Не удалось создать раздел: {error}"

    section = await section_service.get_section_by_id(section_id, db_session)
    return section


# ============================================================
# ТЕСТЫ: SINGLETON
# ============================================================

class TestSingleton:
    """Тесты синглтона get_section_service."""

    def test_get_section_service_returns_same_instance(self):
        """Проверяет что get_section_service возвращает один экземпляр."""
        service1 = get_section_service()
        service2 = get_section_service()
        assert service1 is service2


# ============================================================
# ТЕСТЫ: СОЗДАНИЕ РАЗДЕЛА
# ============================================================

class TestCreateSection:
    """Тесты создания разделов спама."""

    @pytest.mark.asyncio
    async def test_create_section_success(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService
    ):
        """Успешное создание раздела."""
        success, section_id, error = await section_service.create_section(
            chat_id=test_group.chat_id,
            name="Жильё",
            description="Аренда недвижимости",
            threshold=70,
            action="mute",
            mute_duration=60,
            session=db_session,
            created_by=111222333
        )

        assert success is True
        assert section_id is not None
        assert error is None

        # Проверяем что раздел создан корректно
        section = await section_service.get_section_by_id(section_id, db_session)
        assert section is not None
        assert section.name == "Жильё"
        assert section.description == "Аренда недвижимости"
        assert section.threshold == 70
        assert section.action == "mute"
        assert section.mute_duration == 60
        assert section.enabled is True
        assert section.created_by == 111222333

    @pytest.mark.asyncio
    async def test_create_section_empty_name_fails(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService
    ):
        """Создание раздела с пустым названием должно провалиться."""
        success, section_id, error = await section_service.create_section(
            chat_id=test_group.chat_id,
            name="   ",
            session=db_session
        )

        assert success is False
        assert section_id is None
        assert "пустым" in error.lower()

    @pytest.mark.asyncio
    async def test_create_section_long_name_fails(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService
    ):
        """Создание раздела с слишком длинным названием должно провалиться."""
        long_name = "A" * 150  # > 100 символов

        success, section_id, error = await section_service.create_section(
            chat_id=test_group.chat_id,
            name=long_name,
            session=db_session
        )

        assert success is False
        assert section_id is None
        assert "длинное" in error.lower()

    @pytest.mark.asyncio
    async def test_create_section_duplicate_name_fails(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService,
        test_section: CustomSpamSection
    ):
        """Создание раздела с дублирующимся названием должно провалиться."""
        success, section_id, error = await section_service.create_section(
            chat_id=test_group.chat_id,
            name="Такси",  # Уже существует
            session=db_session
        )

        assert success is False
        assert section_id is None
        assert "уже существует" in error.lower()


# ============================================================
# ТЕСТЫ: ПОЛУЧЕНИЕ РАЗДЕЛОВ
# ============================================================

class TestGetSections:
    """Тесты получения разделов."""

    @pytest.mark.asyncio
    async def test_get_sections_empty(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService
    ):
        """Получение разделов пустой группы."""
        sections = await section_service.get_sections(
            test_group.chat_id,
            db_session
        )
        assert sections == []

    @pytest.mark.asyncio
    async def test_get_sections_returns_all(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService
    ):
        """Получение всех разделов группы."""
        # Создаём несколько разделов
        await section_service.create_section(
            test_group.chat_id, "Раздел А", db_session
        )
        await section_service.create_section(
            test_group.chat_id, "Раздел Б", db_session
        )
        await section_service.create_section(
            test_group.chat_id, "Раздел В", db_session
        )

        sections = await section_service.get_sections(
            test_group.chat_id,
            db_session,
            enabled_only=False
        )

        assert len(sections) == 3
        # Проверяем сортировку по названию
        names = [s.name for s in sections]
        assert names == sorted(names)

    @pytest.mark.asyncio
    async def test_get_sections_enabled_only(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService
    ):
        """Получение только активных разделов."""
        # Создаём раздел и отключаем его
        success, section_id, _ = await section_service.create_section(
            test_group.chat_id, "Отключённый", db_session
        )
        await section_service.toggle_section(section_id, db_session)

        # Создаём активный раздел
        await section_service.create_section(
            test_group.chat_id, "Активный", db_session
        )

        # enabled_only=True (по умолчанию)
        sections = await section_service.get_sections(
            test_group.chat_id,
            db_session
        )

        assert len(sections) == 1
        assert sections[0].name == "Активный"

    @pytest.mark.asyncio
    async def test_get_section_by_id(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Получение раздела по ID."""
        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )

        assert section is not None
        assert section.id == test_section.id
        assert section.name == test_section.name

    @pytest.mark.asyncio
    async def test_get_section_by_id_not_found(
        self,
        db_session: AsyncSession,
        section_service: CustomSectionService
    ):
        """Получение несуществующего раздела."""
        section = await section_service.get_section_by_id(99999, db_session)
        assert section is None

    @pytest.mark.asyncio
    async def test_get_section_by_name(
        self,
        db_session: AsyncSession,
        test_group: Group,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Получение раздела по названию."""
        section = await section_service.get_section_by_name(
            test_group.chat_id,
            "Такси",
            db_session
        )

        assert section is not None
        assert section.name == "Такси"

    @pytest.mark.asyncio
    async def test_get_section_by_name_not_found(
        self,
        db_session: AsyncSession,
        test_group: Group,
        section_service: CustomSectionService
    ):
        """Поиск несуществующего раздела по названию."""
        section = await section_service.get_section_by_name(
            test_group.chat_id,
            "Несуществующий",
            db_session
        )
        assert section is None


# ============================================================
# ТЕСТЫ: ОБНОВЛЕНИЕ РАЗДЕЛА
# ============================================================

class TestUpdateSection:
    """Тесты обновления разделов."""

    @pytest.mark.asyncio
    async def test_update_section_name(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление названия раздела."""
        success, error = await section_service.update_section(
            test_section.id,
            db_session,
            name="Яндекс Такси"
        )

        assert success is True
        assert error is None

        # Проверяем обновление
        updated = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert updated.name == "Яндекс Такси"

    @pytest.mark.asyncio
    async def test_update_section_threshold(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление порога чувствительности."""
        success, error = await section_service.update_section(
            test_section.id,
            db_session,
            threshold=80
        )

        assert success is True

        updated = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert updated.threshold == 80

    @pytest.mark.asyncio
    async def test_update_section_action_and_mute(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление действия и длительности мута."""
        success, error = await section_service.update_section(
            test_section.id,
            db_session,
            action="mute",
            mute_duration=120
        )

        assert success is True

        updated = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert updated.action == "mute"
        assert updated.mute_duration == 120

    @pytest.mark.asyncio
    async def test_update_section_forward_channel(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление канала для пересылки."""
        success, error = await section_service.update_section(
            test_section.id,
            db_session,
            action="forward_delete",
            forward_channel_id=-1001111222333
        )

        assert success is True

        updated = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert updated.action == "forward_delete"
        assert updated.forward_channel_id == -1001111222333

    @pytest.mark.asyncio
    async def test_update_section_empty_name_fails(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление на пустое название должно провалиться."""
        success, error = await section_service.update_section(
            test_section.id,
            db_session,
            name=""
        )

        assert success is False
        assert "пустым" in error.lower()

    @pytest.mark.asyncio
    async def test_update_section_not_found(
        self,
        db_session: AsyncSession,
        section_service: CustomSectionService
    ):
        """Обновление несуществующего раздела."""
        success, error = await section_service.update_section(
            99999,
            db_session,
            name="Новое имя"
        )

        assert success is False
        assert "не найден" in error.lower()


# ============================================================
# ТЕСТЫ: УДАЛЕНИЕ РАЗДЕЛА
# ============================================================

class TestDeleteSection:
    """Тесты удаления разделов."""

    @pytest.mark.asyncio
    async def test_delete_section_success(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Успешное удаление раздела."""
        section_id = test_section.id

        result = await section_service.delete_section(section_id, db_session)
        assert result is True

        # Проверяем что удалён
        deleted = await section_service.get_section_by_id(section_id, db_session)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_section_not_found(
        self,
        db_session: AsyncSession,
        section_service: CustomSectionService
    ):
        """Удаление несуществующего раздела."""
        result = await section_service.delete_section(99999, db_session)
        assert result is False


# ============================================================
# ТЕСТЫ: ПЕРЕКЛЮЧЕНИЕ АКТИВНОСТИ
# ============================================================

class TestToggleSection:
    """Тесты переключения активности раздела."""

    @pytest.mark.asyncio
    async def test_toggle_section_disable(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Отключение активного раздела."""
        assert test_section.enabled is True

        result = await section_service.toggle_section(test_section.id, db_session)
        assert result is True

        toggled = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert toggled.enabled is False

    @pytest.mark.asyncio
    async def test_toggle_section_enable(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Включение отключённого раздела."""
        # Сначала отключаем
        await section_service.toggle_section(test_section.id, db_session)

        # Затем включаем
        result = await section_service.toggle_section(test_section.id, db_session)
        assert result is True

        toggled = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert toggled.enabled is True

    @pytest.mark.asyncio
    async def test_toggle_section_not_found(
        self,
        db_session: AsyncSession,
        section_service: CustomSectionService
    ):
        """Переключение несуществующего раздела."""
        result = await section_service.toggle_section(99999, db_session)
        assert result is False


# ============================================================
# ТЕСТЫ: ПАТТЕРНЫ РАЗДЕЛА
# ============================================================

class TestSectionPatterns:
    """Тесты работы с паттернами раздела."""

    @pytest.mark.asyncio
    async def test_add_pattern_success(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Успешное добавление паттерна."""
        success, pattern_id, error = await section_service.add_section_pattern(
            section_id=test_section.id,
            pattern="такси недорого",
            session=db_session,
            weight=30,
            created_by=123456789
        )

        assert success is True
        assert pattern_id is not None
        assert error is None

        # Проверяем паттерн
        patterns = await section_service.get_section_patterns(
            test_section.id,
            db_session
        )
        assert len(patterns) == 1
        assert patterns[0].pattern == "такси недорого"
        assert patterns[0].weight == 30

    @pytest.mark.asyncio
    async def test_add_pattern_normalized(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Паттерн нормализуется при добавлении."""
        success, pattern_id, _ = await section_service.add_section_pattern(
            section_id=test_section.id,
            pattern="ТАКСИ Недорого",  # Разный регистр
            session=db_session
        )

        assert success is True

        patterns = await section_service.get_section_patterns(
            test_section.id,
            db_session
        )
        # Нормализованная версия должна быть в нижнем регистре
        # TextNormalizer убирает пробелы между словами для поиска подстрок
        assert patterns[0].normalized.islower() or patterns[0].normalized == "таксинедорого"
        # Главное - паттерн сохраняется как есть
        assert patterns[0].pattern == "ТАКСИ Недорого"

    @pytest.mark.asyncio
    async def test_add_pattern_empty_fails(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Добавление пустого паттерна должно провалиться."""
        success, pattern_id, error = await section_service.add_section_pattern(
            section_id=test_section.id,
            pattern="   ",
            session=db_session
        )

        assert success is False
        assert pattern_id is None
        assert "пустым" in error.lower()

    @pytest.mark.asyncio
    async def test_add_pattern_duplicate_fails(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Добавление дублирующегося паттерна должно провалиться."""
        # Добавляем первый раз
        await section_service.add_section_pattern(
            test_section.id,
            "такси дёшево",
            db_session
        )

        # Пытаемся добавить второй раз
        success, pattern_id, error = await section_service.add_section_pattern(
            test_section.id,
            "такси дёшево",
            db_session
        )

        assert success is False
        assert "уже существует" in error.lower()

    @pytest.mark.asyncio
    async def test_get_patterns_sorted_by_weight(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Паттерны отсортированы по весу (по убыванию)."""
        await section_service.add_section_pattern(
            test_section.id, "низкий вес", db_session, weight=10
        )
        await section_service.add_section_pattern(
            test_section.id, "высокий вес", db_session, weight=50
        )
        await section_service.add_section_pattern(
            test_section.id, "средний вес", db_session, weight=30
        )

        patterns = await section_service.get_section_patterns(
            test_section.id,
            db_session
        )

        weights = [p.weight for p in patterns]
        assert weights == sorted(weights, reverse=True)

    @pytest.mark.asyncio
    async def test_delete_pattern_success(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Успешное удаление паттерна."""
        success, pattern_id, _ = await section_service.add_section_pattern(
            test_section.id,
            "для удаления",
            db_session
        )

        result = await section_service.delete_section_pattern(pattern_id, db_session)
        assert result is True

        # Проверяем что удалён
        patterns = await section_service.get_section_patterns(
            test_section.id,
            db_session
        )
        assert len(patterns) == 0

    @pytest.mark.asyncio
    async def test_delete_pattern_not_found(
        self,
        db_session: AsyncSession,
        section_service: CustomSectionService
    ):
        """Удаление несуществующего паттерна."""
        result = await section_service.delete_section_pattern(99999, db_session)
        assert result is False

    @pytest.mark.asyncio
    async def test_toggle_pattern(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Переключение активности паттерна."""
        success, pattern_id, _ = await section_service.add_section_pattern(
            test_section.id,
            "паттерн для toggle",
            db_session
        )

        # Отключаем
        result = await section_service.toggle_section_pattern(pattern_id, db_session)
        assert result is True

        pattern = await section_service.get_section_pattern_by_id(
            pattern_id,
            db_session
        )
        assert pattern.is_active is False

        # Включаем обратно
        await section_service.toggle_section_pattern(pattern_id, db_session)
        pattern = await section_service.get_section_pattern_by_id(
            pattern_id,
            db_session
        )
        assert pattern.is_active is True

    @pytest.mark.asyncio
    async def test_get_patterns_count(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Подсчёт количества паттернов."""
        # Изначально пусто
        count = await section_service.get_patterns_count(
            test_section.id,
            db_session
        )
        assert count == 0

        # Добавляем паттерны
        await section_service.add_section_pattern(
            test_section.id, "один", db_session
        )
        await section_service.add_section_pattern(
            test_section.id, "два", db_session
        )

        count = await section_service.get_patterns_count(
            test_section.id,
            db_session
        )
        assert count == 2

    @pytest.mark.asyncio
    async def test_increment_pattern_trigger(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Увеличение счётчика срабатываний."""
        success, pattern_id, _ = await section_service.add_section_pattern(
            test_section.id,
            "триггер тест",
            db_session
        )

        # Проверяем начальное значение
        pattern = await section_service.get_section_pattern_by_id(
            pattern_id,
            db_session
        )
        assert pattern.triggers_count == 0
        assert pattern.last_triggered_at is None

        # Увеличиваем счётчик
        await section_service.increment_pattern_trigger(pattern_id, db_session)

        pattern = await section_service.get_section_pattern_by_id(
            pattern_id,
            db_session
        )
        assert pattern.triggers_count == 1
        assert pattern.last_triggered_at is not None

    @pytest.mark.asyncio
    async def test_get_patterns_active_only(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Получение только активных паттернов."""
        # Добавляем и отключаем один паттерн
        _, inactive_id, _ = await section_service.add_section_pattern(
            test_section.id, "неактивный", db_session
        )
        await section_service.toggle_section_pattern(inactive_id, db_session)

        # Добавляем активный
        await section_service.add_section_pattern(
            test_section.id, "активный", db_session
        )

        # Получаем только активные
        patterns = await section_service.get_section_patterns(
            test_section.id,
            db_session,
            active_only=True
        )

        assert len(patterns) == 1
        assert patterns[0].pattern == "активный"


# ============================================================
# ТЕСТЫ: CASCADE DELETE
# ============================================================

class TestCascadeDelete:
    """Тесты каскадного удаления."""

    @pytest.mark.asyncio
    async def test_delete_section_deletes_patterns(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """При удалении раздела удаляются и его паттерны."""
        # Добавляем паттерны
        await section_service.add_section_pattern(
            test_section.id, "паттерн 1", db_session
        )
        await section_service.add_section_pattern(
            test_section.id, "паттерн 2", db_session
        )

        # Проверяем что паттерны есть
        count = await section_service.get_patterns_count(
            test_section.id,
            db_session
        )
        assert count == 2

        # Удаляем раздел
        await section_service.delete_section(test_section.id, db_session)

        # Паттерны должны быть удалены (CASCADE)
        # Проверяем через прямой запрос к БД
        from sqlalchemy import select
        result = await db_session.execute(
            select(CustomSectionPattern).where(
                CustomSectionPattern.section_id == test_section.id
            )
        )
        patterns = result.scalars().all()
        assert len(patterns) == 0


# ============================================================
# ТЕСТЫ: ОПЦИИ ПЕРЕСЫЛКИ ПО ДЕЙСТВИЯМ
# ============================================================

class TestSectionForwardOptions:
    """Тесты опций пересылки (forward_on_delete/mute/ban)."""

    @pytest.mark.asyncio
    async def test_section_forward_options_default_false(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """По умолчанию все опции пересылки отключены."""
        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.forward_on_delete is False
        assert section.forward_on_mute is False
        assert section.forward_on_ban is False

    @pytest.mark.asyncio
    async def test_update_forward_on_delete(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление опции forward_on_delete."""
        # Устанавливаем канал пересылки (обязательно для forward)
        await section_service.update_section(
            test_section.id,
            db_session,
            forward_channel_id=-1001234567890,
            forward_on_delete=True
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.forward_on_delete is True
        assert section.forward_on_mute is False
        assert section.forward_on_ban is False

    @pytest.mark.asyncio
    async def test_update_forward_on_mute(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление опции forward_on_mute."""
        await section_service.update_section(
            test_section.id,
            db_session,
            forward_channel_id=-1001234567890,
            forward_on_mute=True
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.forward_on_mute is True
        assert section.forward_on_delete is False
        assert section.forward_on_ban is False

    @pytest.mark.asyncio
    async def test_update_forward_on_ban(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление опции forward_on_ban."""
        await section_service.update_section(
            test_section.id,
            db_session,
            forward_channel_id=-1001234567890,
            forward_on_ban=True
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.forward_on_ban is True
        assert section.forward_on_delete is False
        assert section.forward_on_mute is False

    @pytest.mark.asyncio
    async def test_update_all_forward_options(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление всех опций пересылки одновременно."""
        await section_service.update_section(
            test_section.id,
            db_session,
            forward_channel_id=-1001234567890,
            forward_on_delete=True,
            forward_on_mute=True,
            forward_on_ban=True
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.forward_on_delete is True
        assert section.forward_on_mute is True
        assert section.forward_on_ban is True

    @pytest.mark.asyncio
    async def test_toggle_forward_option(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Переключение опции пересылки туда и обратно."""
        # Включаем
        await section_service.update_section(
            test_section.id,
            db_session,
            forward_on_delete=True
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.forward_on_delete is True

        # Выключаем
        await section_service.update_section(
            test_section.id,
            db_session,
            forward_on_delete=False
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.forward_on_delete is False


# ============================================================
# ТЕСТЫ: ДОПОЛНИТЕЛЬНЫЕ НАСТРОЙКИ РАЗДЕЛА
# ============================================================

class TestSectionAdvancedSettings:
    """Тесты дополнительных настроек раздела."""

    @pytest.mark.asyncio
    async def test_update_notification_delete_delay(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление задержки автоудаления уведомления."""
        await section_service.update_section(
            test_section.id,
            db_session,
            notification_delete_delay=30
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.notification_delete_delay == 30

    @pytest.mark.asyncio
    async def test_update_mute_text(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление кастомного текста мута."""
        custom_text = "Вы замучены за спам: %user%"
        await section_service.update_section(
            test_section.id,
            db_session,
            mute_text=custom_text
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.mute_text == custom_text

    @pytest.mark.asyncio
    async def test_update_ban_text(
        self,
        db_session: AsyncSession,
        test_section: CustomSpamSection,
        section_service: CustomSectionService
    ):
        """Обновление кастомного текста бана."""
        custom_text = "Забанен за нарушение: %user%"
        await section_service.update_section(
            test_section.id,
            db_session,
            ban_text=custom_text
        )

        section = await section_service.get_section_by_id(
            test_section.id,
            db_session
        )
        assert section.ban_text == custom_text
