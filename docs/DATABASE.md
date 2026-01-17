# Database Schema / Схема базы данных

## Overview

**СУБД:** PostgreSQL 15
**ORM:** SQLAlchemy 2.x (async)
**Миграции:** Alembic

**Файлы моделей:**
- `bot/database/models.py` — основные модели
- `bot/database/models_antispam.py` — модели антиспам
- `bot/database/models_content_filter.py` — модели фильтра контента
- `bot/database/models_message_management.py` — модели управления сообщениями
- `bot/database/mute_models.py` — модели мутов
- `bot/database/models_global_settings.py` — глобальные настройки бота (max_seen_user_id)
- `bot/database/models_user_stats.py` — статистика пользователей (команда /stat)
- `bot/database/models_profile_monitor.py` — модуль мониторинга профилей
- `bot/database/models_antiraid.py` — модуль защиты от массовых атак (Anti-Raid)

---

## ER Diagram (упрощённая)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   users     │────<│  user_group │>────│     groups      │
└─────────────┘     └─────────────┘     └─────────────────┘
      │                                         │
      │                                         │
      ▼                                         ▼
┌─────────────┐                         ┌─────────────────┐
│ group_users │                         │  chat_settings  │
└─────────────┘                         └─────────────────┘
                                                │
                    ┌───────────────────────────┼───────────────────────────┐
                    ▼                           ▼                           ▼
            ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
            │ antispam_rules│           │captcha_settings│          │ user_restrict │
            └───────────────┘           └───────────────┘           └───────────────┘
                                                │
                    ┌───────────────────────────┼───────────────────────────┐
                    ▼                           ▼                           ▼
            ┌───────────────┐           ┌───────────────┐           ┌───────────────┐
            │content_filter │           │  filter_words │           │filter_whitelist│
            │   _settings   │           └───────────────┘           └───────────────┘
            └───────────────┘
```

---

## Основные таблицы

### users
Пользователи Telegram.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| user_id | BIGINT UNIQUE | Telegram user ID |
| username | VARCHAR | @username |
| full_name | VARCHAR | Полное имя |
| first_name | VARCHAR | Имя |
| last_name | VARCHAR | Фамилия |
| language_code | VARCHAR | Язык |
| is_bot | BOOLEAN | Является ботом |
| is_premium | BOOLEAN | Premium подписка |
| created_at | DATETIME | Дата создания |
| updated_at | DATETIME | Дата обновления |

### groups
Группы, в которых работает бот.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT UNIQUE | Telegram chat ID |
| title | VARCHAR | Название группы |
| creator_user_id | BIGINT FK | ID создателя |
| added_by_user_id | BIGINT FK | Кто добавил бота |
| bot_id | BIGINT | ID бота |

### user_group
Связь администраторов с группами (Many-to-Many).

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| user_id | BIGINT FK | ID пользователя |
| group_id | BIGINT FK | ID группы (chat_id) |

**Индексы:** `ix_user_group_unique(user_id, group_id)`

### group_users
Все участники групп с дополнительной информацией.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| user_id | BIGINT FK | ID пользователя |
| chat_id | BIGINT FK | ID группы |
| username | VARCHAR | @username |
| first_name | VARCHAR | Имя |
| last_name | VARCHAR | Фамилия |
| joined_at | DATETIME | Дата вступления |
| last_activity | DATETIME | Последняя активность |
| is_admin | BOOLEAN | Администратор |
| is_creator | BOOLEAN | Создатель группы |

---

## Настройки

### chat_settings
Настройки групп.

| Колонка | Тип | По умолчанию | Описание |
|---------|-----|--------------|----------|
| chat_id | BIGINT PK FK | - | ID группы |
| username | VARCHAR | NULL | @username группы |
| enable_photo_filter | BOOLEAN | false | Фильтр фото |
| photo_filter_mute_minutes | INTEGER | 60 | Время мута за фото |
| mute_new_members | BOOLEAN | false | Мутить новых |
| auto_mute_scammers | BOOLEAN | true | Автомут скаммеров |
| global_mute_enabled | BOOLEAN | false | Глобальный мут |
| reaction_mute_enabled | BOOLEAN | false | Мут по реакции |
| reaction_mute_announce_enabled | BOOLEAN | true | Анонс мута |
| captcha_join_enabled | BOOLEAN | false | Капча при вступлении |
| captcha_invite_enabled | BOOLEAN | false | Капча при инвайте |
| captcha_timeout_seconds | INTEGER | 300 | Таймаут капчи |
| captcha_message_ttl_seconds | INTEGER | 900 | TTL сообщения капчи |
| captcha_flood_threshold | INTEGER | 5 | Порог антифлуда |
| captcha_flood_window_seconds | INTEGER | 180 | Окно антифлуда |
| captcha_flood_action | VARCHAR(16) | "warn" | Действие при флуде |
| antispam_warning_ttl_seconds | INTEGER | 0 | TTL предупреждений |

### captcha_settings
Настройки капчи (legacy).

| Колонка | Тип | Описание |
|---------|-----|----------|
| group_id | BIGINT PK FK | ID группы |
| is_enabled | BOOLEAN | Капча включена |
| is_visual_enabled | BOOLEAN | Визуальная капча |
| created_at | DATETIME | Дата создания |

---

## Антиспам

### antispam_rules
Правила антиспам для групп.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| rule_type | ENUM | Тип правила (см. ниже) |
| action | ENUM | Действие (см. ниже) |
| delete_message | BOOLEAN | Удалять сообщение |
| restrict_minutes | INTEGER | Время ограничения |
| created_at | DATETIME | Дата создания |
| updated_at | DATETIME | Дата обновления |

**ENUM rule_type_enum:**
- `TELEGRAM_LINK` — ссылки t.me, telegram.me
- `ANY_LINK` — любые HTTP/HTTPS ссылки
- `FORWARD_CHANNEL` — пересылки из каналов
- `FORWARD_GROUP` — пересылки из групп
- `FORWARD_USER` — пересылки от пользователей
- `FORWARD_BOT` — пересылки от ботов
- `QUOTE_CHANNEL` — цитаты из каналов
- `QUOTE_GROUP` — цитаты из групп
- `QUOTE_USER` — цитаты от пользователей
- `QUOTE_BOT` — цитаты от ботов

**ENUM action_type_enum:**
- `OFF` — выключено
- `DELETE` — только удаление
- `WARN` — предупреждение
- `KICK` — исключение
- `RESTRICT` — мут
- `BAN` — бан

### antispam_whitelist
Белый список для антиспам.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| scope | ENUM | Область применения |
| pattern | TEXT | Паттерн (URL, ID) |
| added_by | BIGINT | Кто добавил |
| added_at | DATETIME | Дата добавления |

**ENUM whitelist_scope_enum:**
- `TELEGRAM_LINK` — для Telegram ссылок
- `ANY_LINK` — для любых ссылок
- `FORWARD` — для пересылок
- `QUOTE` — для цитат

---

## Муты и ограничения

### user_restrictions
Активные ограничения пользователей с возможностью восстановления после повторного входа.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| user_id | BIGINT | Telegram user ID |
| chat_id | BIGINT FK | ID группы (→ groups.chat_id) |
| restriction_type | VARCHAR(50) | Тип ограничения (mute, ban, kick) |
| reason | VARCHAR(50) | Причина (antispam, content_filter, reaction, manual, risk_gate) |
| restricted_by | BIGINT | ID админа или бота, применившего ограничение |
| until_date | DATETIME | Дата окончания (NULL = бессрочно) |
| is_active | BOOLEAN | Активно ли ограничение (true = действует) |
| created_at | DATETIME | Дата создания записи |
| updated_at | DATETIME | Дата последнего обновления |

**Важно:** Таблица используется для восстановления ограничений после `approve_chat_join_request()`.
При одобрении заявки на вступление Telegram автоматически снимает все restrictions,
поэтому после approve бот проверяет БД и восстанавливает мут/бан если запись is_active=True.

### group_mutes
История мутов по реакции.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| group_id | BIGINT | ID группы |
| target_user_id | BIGINT | Кого замутили |
| admin_user_id | BIGINT | Кто замутил |
| reaction | VARCHAR(16) | Реакция |
| mute_until | DATETIME | До какого времени |
| reason | VARCHAR | Причина |
| created_at | DATETIME | Дата создания |

### spammers
Глобальный реестр спаммеров.

| Колонка | Тип | Описание |
|---------|-----|----------|
| user_id | BIGINT PK | ID пользователя |
| risk_score | INTEGER | Балл риска |
| reason | VARCHAR | Причина |
| incidents | INTEGER | Количество инцидентов |
| last_incident_at | DATETIME | Последний инцидент |

### scammer_tracker
Отслеживание скаммеров по группам.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| user_id | BIGINT | ID пользователя |
| chat_id | BIGINT FK | ID группы |
| username | VARCHAR | @username |
| violation_type | VARCHAR(50) | Тип нарушения |
| violation_count | INTEGER | Количество |
| is_scammer | BOOLEAN | Является скаммером |
| scammer_level | INTEGER | Уровень (0-5) |
| is_whitelisted | BOOLEAN | В белом списке |

---

## Капча

### visual_captcha
Данные визуальной капчи.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| user_id | BIGINT | ID пользователя |
| chat_id | BIGINT FK | ID группы |
| answer | VARCHAR(10) | Правильный ответ |
| message_id | BIGINT | ID сообщения |
| expires_at | DATETIME | Истечение |
| created_at | DATETIME | Дата создания |

### captcha_answers
Ответы на капчу (legacy).

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| user_id | BIGINT | ID пользователя |
| chat_id | BIGINT FK | ID группы |
| answer | VARCHAR(50) | Ответ |
| expires_at | DATETIME | Истечение |

---

## Журнал

### group_journal_channels
Привязка журналов к группам.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| group_id | BIGINT FK UNIQUE | ID группы |
| journal_channel_id | BIGINT | ID канала журнала |
| journal_type | VARCHAR(20) | channel/group |
| journal_title | VARCHAR | Название |
| is_active | BOOLEAN | Активен |
| linked_at | DATETIME | Дата привязки |
| linked_by_user_id | BIGINT | Кто привязал |
| last_event_at | DATETIME | Последнее событие |

---

## Фильтр контента

### content_filter_settings
Настройки фильтра контента для групп.

| Колонка | Тип | По умолчанию | Описание |
|---------|-----|--------------|----------|
| chat_id | BIGINT PK FK | - | ID группы |
| enabled | BOOLEAN | false | Фильтр включён |
| word_filter_enabled | BOOLEAN | true | Фильтр слов |
| scam_detection_enabled | BOOLEAN | true | Детектор скама |
| flood_detection_enabled | BOOLEAN | true | Детектор флуда |
| referral_detection_enabled | BOOLEAN | false | Детектор рефералов |
| scam_sensitivity | INTEGER | 60 | Чувствительность (40-90) |
| flood_max_repeats | INTEGER | 2 | Макс. повторов для флуда |
| flood_time_window | INTEGER | 60 | Временное окно флуда (сек) |
| default_action | VARCHAR(20) | "delete" | Действие по умолчанию |
| default_mute_duration | INTEGER | 1440 | Длительность мута (минуты) |
| word_filter_action | VARCHAR(20) | NULL | Действие для слов (NULL=default) |
| word_filter_mute_duration | INTEGER | NULL | Длительность мута для слов |
| flood_action | VARCHAR(20) | NULL | Действие для флуда (NULL=default) |
| flood_mute_duration | INTEGER | NULL | Длительность мута для флуда |
| word_filter_normalize | BOOLEAN | true | Применять нормализатор к словам |
| flood_detect_any_messages | BOOLEAN | false | Детектировать любые сообщения подряд |
| flood_any_max_messages | INTEGER | 5 | Макс. сообщений для любых |
| flood_any_time_window | INTEGER | 10 | Окно для любых сообщений (сек) |
| flood_detect_media | BOOLEAN | false | Детектировать медиа-флуд |
| flood_mute_text | VARCHAR(500) | NULL | Кастомный текст при муте за флуд |
| flood_ban_text | VARCHAR(500) | NULL | Кастомный текст при бане за флуд |
| flood_warn_text | VARCHAR(500) | NULL | Кастомный текст предупреждения за флуд |
| delete_user_commands | BOOLEAN | false | Удалять команды от обычных пользователей |
| delete_system_messages | BOOLEAN | false | Удалять системные сообщения |
| log_violations | BOOLEAN | true | Логировать нарушения |
| simple_words_enabled | BOOLEAN | true | Простые слова включены |
| simple_words_action | VARCHAR(20) | "delete" | Действие для простых слов |
| simple_words_mute_duration | INTEGER | NULL | Длительность мута для простых |
| simple_words_mute_text | VARCHAR(500) | NULL | Кастомный текст при муте |
| simple_words_ban_text | VARCHAR(500) | NULL | Кастомный текст при бане |
| simple_words_delete_delay | INTEGER | NULL | Задержка удаления сообщения (сек) |
| simple_words_notification_delete_delay | INTEGER | NULL | Автоудаление уведомления (сек) |
| harmful_words_enabled | BOOLEAN | true | Вредные слова включены |
| harmful_words_action | VARCHAR(20) | "ban" | Действие для вредных слов |
| harmful_words_mute_duration | INTEGER | NULL | Длительность мута для вредных |
| harmful_words_mute_text | VARCHAR(500) | NULL | Кастомный текст при муте |
| harmful_words_ban_text | VARCHAR(500) | NULL | Кастомный текст при бане |
| harmful_words_delete_delay | INTEGER | NULL | Задержка удаления сообщения (сек) |
| harmful_words_notification_delete_delay | INTEGER | NULL | Автоудаление уведомления (сек) |
| obfuscated_words_enabled | BOOLEAN | true | Обфускация включена |
| obfuscated_words_action | VARCHAR(20) | "mute" | Действие для обфускации |
| obfuscated_words_mute_duration | INTEGER | 1440 | Длительность мута для обфускации |
| obfuscated_words_mute_text | VARCHAR(500) | NULL | Кастомный текст при муте |
| obfuscated_words_ban_text | VARCHAR(500) | NULL | Кастомный текст при бане |
| obfuscated_words_delete_delay | INTEGER | NULL | Задержка удаления сообщения (сек) |
| obfuscated_words_notification_delete_delay | INTEGER | NULL | Автоудаление уведомления (сек) |
| created_at | DATETIME | now | Дата создания |
| updated_at | DATETIME | now | Дата обновления |

**Примечания к кастомному тексту:**
- Поддерживает плейсхолдер `%user%` — заменяется на упоминание нарушителя
- Пример: `%user% получил мут за спам` → `@username получил мут за спам`
- Если NULL — используется стандартный текст бота

### filter_words
Запрещённые слова/фразы.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| word | VARCHAR(255) | Оригинальное слово |
| normalized | VARCHAR(255) | Нормализованная версия |
| match_type | VARCHAR(20) | word/phrase/regex |
| action | VARCHAR(20) | Индивидуальное действие |
| action_duration | INTEGER | Длительность мута |
| category | VARCHAR(50) | Категория (drugs, profanity) |
| created_by | BIGINT | Кто добавил |
| created_at | DATETIME | Дата добавления |

**Индексы:** `ix_filter_words_chat_id`, `ix_filter_words_normalized`

### filter_whitelist
Исключения (слова которые НЕ фильтруются).

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| word | VARCHAR(255) | Оригинальное слово |
| normalized | VARCHAR(255) | Нормализованная версия |
| created_by | BIGINT | Кто добавил |
| created_at | DATETIME | Дата добавления |

**Индексы:** `ix_filter_whitelist_chat_id`

### filter_violations
Лог нарушений.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| user_id | BIGINT | ID нарушителя |
| message_id | BIGINT | ID сообщения |
| detector_type | VARCHAR(50) | word_filter/scam/flood/referral |
| trigger | TEXT | Что сработало |
| action_taken | VARCHAR(20) | Применённое действие |
| created_at | DATETIME | Дата нарушения |

**Индексы:** `ix_filter_violations_chat_id`, `ix_filter_violations_user_id`

### scam_signal_categories
Категории сигналов для антискама с настраиваемыми ключевыми словами.

| Колонка | Тип | По умолчанию | Описание |
|---------|-----|--------------|----------|
| id | INTEGER PK | - | Автоинкремент |
| chat_id | BIGINT FK | - | ID группы |
| category_name | VARCHAR(100) | - | Название категории |
| keywords | TEXT | - | Ключевые слова через запятую |
| weight | INTEGER | 25 | Вес при подсчёте score |
| enabled | BOOLEAN | true | Категория активна |
| created_at | DATETIME | now | Дата создания |

**Индексы:** `ix_scam_signal_categories_chat_id`

**Пример использования:**
| Категория | Keywords | Weight | Описание |
|-----------|----------|--------|----------|
| Наркотики | drugs, наркота, weed, hashish | 40 | +40 к score |
| Финансовый скам | перевод, обмен, swift, sepa | 25 | +25 к score |
| Документы | диплом, права, паспорт | 30 | +30 к score |

### scam_patterns
Кастомные паттерны для антискама.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| pattern | TEXT | Оригинальный паттерн |
| normalized | TEXT | Нормализованная версия |
| pattern_type | VARCHAR(20) | keyword/phrase/regex |
| weight | INTEGER | Вес при подсчёте (15/25/40) |
| hit_count | INTEGER | Количество срабатываний |
| created_by | BIGINT | Кто добавил |
| created_at | DATETIME | Дата добавления |

**Индексы:** `ix_scam_patterns_chat_id`

### custom_spam_sections
Кастомные разделы спама (группировка паттернов по тематике).

| Колонка | Тип | По умолчанию | Описание |
|---------|-----|--------------|----------|
| id | INTEGER PK | - | Автоинкремент |
| chat_id | BIGINT FK | - | ID группы |
| name | VARCHAR(100) | - | Название раздела (например "Такси", "Недвижимость") |
| description | TEXT | NULL | Описание раздела |
| threshold | INTEGER | 50 | Порог срабатывания (сумма весов паттернов) |
| action | VARCHAR(20) | "delete" | Действие: delete / mute / ban / forward_delete |
| mute_duration | INTEGER | 1440 | Длительность мута в минутах |
| forward_channel_id | BIGINT | NULL | ID канала для пересылки нарушений |
| forward_on_delete | BOOLEAN | false | Пересылать при действии delete |
| forward_on_mute | BOOLEAN | false | Пересылать при действии mute |
| forward_on_ban | BOOLEAN | false | Пересылать при действии ban |
| mute_text | VARCHAR(500) | NULL | Кастомный текст уведомления мута |
| ban_text | VARCHAR(500) | NULL | Кастомный текст уведомления бана |
| notification_delete_delay | INTEGER | 30 | Автоудаление уведомления через N секунд |
| delete_delay | INTEGER | 0 | Задержка удаления сообщения |
| log_violations | BOOLEAN | true | Логировать нарушения в журнал |
| enabled | BOOLEAN | true | Раздел активен |
| created_by | BIGINT | NULL | Кто создал |
| created_at | DATETIME | now | Дата создания |
| updated_at | DATETIME | now | Дата обновления |

**Индексы:** `ix_custom_spam_sections_chat_id`, `ix_custom_spam_sections_enabled`

**Пример использования:**
| Раздел | Threshold | Action | Описание |
|--------|-----------|--------|----------|
| Такси | 30 | delete | Удаление рекламы такси |
| Наркотики | 25 | ban | Бан за рекламу наркотиков |
| Недвижимость | 40 | mute | Мут за спам недвижимости |

### custom_section_patterns
Паттерны для кастомных разделов спама.

| Колонка | Тип | По умолчанию | Описание |
|---------|-----|--------------|----------|
| id | INTEGER PK | - | Автоинкремент |
| section_id | INTEGER FK | - | ID раздела (CASCADE при удалении) |
| pattern | VARCHAR(500) | - | Оригинальный паттерн (как ввёл админ) |
| normalized | VARCHAR(500) | - | Нормализованная версия для поиска |
| weight | INTEGER | 25 | Вес паттерна при подсчёте скора |
| is_active | BOOLEAN | true | Паттерн активен |
| triggers_count | INTEGER | 0 | Количество срабатываний |
| last_triggered_at | DATETIME | NULL | Последнее срабатывание |
| created_by | BIGINT | NULL | Кто добавил |
| created_at | DATETIME | now | Дата добавления |

**Индексы:** `ix_custom_section_patterns_section_id`

**Логика работы:**
1. При проверке сообщения система ищет совпадения с паттернами раздела
2. Веса совпавших паттернов суммируются
3. Если сумма >= threshold раздела, применяется действие
4. При срабатывании инкрементируется triggers_count паттерна
5. Если установлен forward_channel_id и включён forward_on_*, информация отправляется в канал

---

## Управление сообщениями

### message_management_settings
Настройки модуля управления сообщениями для групп.

| Колонка | Тип | По умолчанию | Описание |
|---------|-----|--------------|----------|
| id | INTEGER PK | - | Автоинкремент |
| chat_id | BIGINT UNIQUE | - | ID группы |
| delete_admin_commands | BOOLEAN | false | Удалять команды от админов |
| delete_user_commands | BOOLEAN | false | Удалять команды от пользователей |
| delete_join_messages | BOOLEAN | false | Удалять сообщения о входе участников |
| delete_leave_messages | BOOLEAN | false | Удалять сообщения о выходе участников |
| delete_pin_messages | BOOLEAN | false | Удалять уведомления о закрепе |
| delete_chat_photo_messages | BOOLEAN | false | Удалять сообщения об изменении фото/названия |
| repin_enabled | BOOLEAN | false | Включён ли автозакреп |
| repin_message_id | BIGINT | NULL | ID сообщения для автозакрепа |
| created_at | DATETIME | now | Дата создания |
| updated_at | DATETIME | - | Дата обновления |

**Индексы:** `ix_message_management_settings_chat_id` (unique)

**Использование:**
- Удаление команд работает отдельно для админов и пользователей
- Системные сообщения: вход (new_chat_members), выход (left_chat_member), закреп (pinned_message), изменение фото/названия
- Репин: при закрепе другого сообщения бот автоматически перезакрепляет `repin_message_id`
- Закрепы от связанного канала игнорируются при репине

---

## Глобальные настройки бота

### bot_global_settings
Глобальные настройки бота (не привязанные к конкретной группе).

| Колонка | Тип | Описание |
|---------|-----|----------|
| key | VARCHAR(100) PK | Уникальный ключ настройки |
| value | TEXT NOT NULL | Значение настройки |
| updated_at | DATETIME(TZ) | Время последнего обновления (auto) |

**Константы ключей:**
- `max_seen_user_id` — максимальный известный ID пользователя для расчёта возраста аккаунтов

**Использование:**
```python
from bot.database.models_global_settings import BotGlobalSettings, GlobalSettingKeys

# Чтение
result = await session.execute(
    select(BotGlobalSettings.value).where(
        BotGlobalSettings.key == GlobalSettingKeys.MAX_SEEN_USER_ID
    )
)
max_id = int(result.scalar_one_or_none() or 8_600_000_000)
```

**Связь с account_age_estimator:**
Сервис `AccountAgeEstimator` использует эту таблицу как источник истины для `max_seen_user_id`.
Приоритет: Redis (кэш) → БД → Fallback (8.6B)

---

## Profile Monitor

### profile_monitor_settings
Настройки модуля мониторинга профилей для групп.

| Колонка | Тип | По умолчанию | Описание |
|---------|-----|--------------|----------|
| chat_id | BIGINT PK FK | - | ID группы |
| enabled | BOOLEAN | false | Модуль включён |
| log_name_changes | BOOLEAN | true | Логировать смену имени |
| log_username_changes | BOOLEAN | true | Логировать смену username |
| log_photo_changes | BOOLEAN | true | Логировать смену фото |
| auto_mute_no_photo_young | BOOLEAN | true | Автомут: нет фото + молодой аккаунт |
| auto_mute_account_age_days | INTEGER | 15 | Порог возраста аккаунта (дней) |
| auto_mute_delete_messages | BOOLEAN | true | Удалять сообщения при автомуте |
| auto_mute_name_change_fast_msg | BOOLEAN | true | Автомут: смена имени + быстрое сообщение |
| name_change_window_hours | INTEGER | 24 | Окно для смены имени (часов) |
| first_message_window_minutes | INTEGER | 30 | Окно для сообщения после смены (минут) |
| photo_freshness_threshold_days | INTEGER | 1 | Порог свежести фото (дней) для критериев 4,5 |
| send_to_journal | BOOLEAN | true | Отправлять в журнал |
| min_changes_for_journal | INTEGER | 1 | Минимум изменений для журнала |
| send_to_group | BOOLEAN | false | Отправлять уведомления в группу |
| created_at | DATETIME | now | Дата создания |
| updated_at | DATETIME | now | Дата обновления |

**Критерии автомута:**
1. Смена имени + смена фото + сообщение ≤30 мин
2. Смена имени + сообщение ≤30 мин
3. Добавление фото + сообщение ≤30 мин
4. Свежее фото (<N дней) + смена имени + сообщение ≤30 мин
5. Свежее фото (<N дней) + сообщение ≤30 мин

### profile_snapshots
Снимки профиля при входе в группу.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| user_id | BIGINT | ID пользователя |
| first_name | VARCHAR(256) | Имя |
| last_name | VARCHAR(256) | Фамилия |
| full_name | VARCHAR(512) | Полное имя |
| username | VARCHAR(256) | @username |
| has_photo | BOOLEAN | Есть фото |
| photo_id | VARCHAR(256) | ID фото |
| photo_age_days | INTEGER | Возраст самого свежего фото (дней) |
| account_age_days | INTEGER | Возраст аккаунта (дней) |
| account_created_at | DATETIME | Дата регистрации |
| is_premium | BOOLEAN | Premium аккаунт |
| joined_at | DATETIME | Время входа в группу |
| updated_at | DATETIME | Время обновления |
| first_message_at | DATETIME | Время первого сообщения |

**Индексы:** `ix_profile_snapshot_chat_user(chat_id, user_id)` (unique)

### profile_change_logs
Журнал изменений профиля.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Автоинкремент |
| chat_id | BIGINT FK | ID группы |
| user_id | BIGINT | ID пользователя |
| change_type | VARCHAR(50) | Тип изменения (name, username, photo_*) |
| old_value | TEXT | Старое значение |
| new_value | TEXT | Новое значение |
| minutes_since_join | INTEGER | Минут с момента входа |
| detected_at_message_id | BIGINT | ID сообщения при обнаружении |
| action_taken | VARCHAR(50) | Применённое действие |
| journal_message_id | BIGINT | ID сообщения в журнале |
| sent_to_group | BOOLEAN | Отправлено в группу |
| created_at | DATETIME | Время изменения |

**Индексы:** `ix_profile_changes_chat_user`, `ix_profile_changes_chat_date`

---

## Таблицы Anti-Raid (models_antiraid.py)

### antiraid_settings

Настройки модуля Anti-Raid для каждой группы (per-group).

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный ID |
| chat_id | BIGINT UNIQUE | ID группы |
| join_exit_enabled | BOOLEAN | Защита от частых входов/выходов |
| join_exit_window | INTEGER | Окно в секундах (дефолт: 60) |
| join_exit_threshold | INTEGER | Порог событий (дефолт: 3) |
| join_exit_action | VARCHAR(20) | Действие: kick/ban/mute (дефолт: ban) |
| join_exit_ban_duration | INTEGER | Длительность бана в часах (дефолт: 168) |
| name_pattern_enabled | BOOLEAN | Бан по паттернам имени |
| name_pattern_action | VARCHAR(20) | Действие: kick/ban (дефолт: ban) |
| name_pattern_ban_duration | INTEGER | Длительность бана (дефолт: 0 = навсегда) |
| mass_join_enabled | BOOLEAN | Защита от массовых вступлений |
| mass_join_window | INTEGER | Окно в секундах (дефолт: 60) |
| mass_join_threshold | INTEGER | Порог вступлений (дефолт: 10) |
| mass_join_action | VARCHAR(20) | Действие: slowmode/lock/notify (дефолт: slowmode) |
| mass_join_slowmode | INTEGER | Slowmode в секундах (дефолт: 60) |
| mass_join_auto_unlock | INTEGER | Авто-снятие в минутах (дефолт: 30) |
| mass_invite_enabled | BOOLEAN | Защита от массовых инвайтов |
| mass_invite_window | INTEGER | Окно в секундах (дефолт: 300) |
| mass_invite_threshold | INTEGER | Порог инвайтов (дефолт: 5) |
| mass_invite_action | VARCHAR(20) | Действие: warn/kick/ban (дефолт: warn) |
| mass_invite_ban_duration | INTEGER | Длительность бана (дефолт: 24) |
| mass_reaction_enabled | BOOLEAN | Защита от массовых реакций |
| mass_reaction_window | INTEGER | Окно в секундах (дефолт: 60) |
| mass_reaction_threshold_user | INTEGER | Порог по юзеру (дефолт: 10) |
| mass_reaction_threshold_msg | INTEGER | Порог по сообщению (дефолт: 20) |
| mass_reaction_action | VARCHAR(20) | Действие: warn/mute/kick (дефолт: mute) |
| mass_reaction_mute_duration | INTEGER | Длительность мута в минутах (дефолт: 60) |
| created_at | DATETIME | Дата создания |
| updated_at | DATETIME | Дата обновления |

**Индексы:** `ix_antiraid_settings_chat_id` (unique)

### antiraid_name_patterns

Паттерны имён для бана при входе в группу.

| Колонка | Тип | Описание |
|---------|-----|----------|
| id | INTEGER PK | Уникальный ID |
| chat_id | BIGINT | ID группы |
| pattern | VARCHAR(255) | Текст паттерна |
| pattern_type | VARCHAR(20) | Тип: contains/regex/exact (дефолт: contains) |
| is_enabled | BOOLEAN | Включён ли паттерн (дефолт: true) |
| created_by | BIGINT | user_id админа |
| created_at | DATETIME | Дата создания |

**Индексы:** `ix_antiraid_name_patterns_chat_id`, `ix_antiraid_name_patterns_chat_enabled`

---

## Миграции Alembic

### Важные миграции

| Revision | Описание |
|----------|----------|
| d62bd1141646 | init — начальная структура |
| a1b2c3d4e5f6 | add_antispam_tables — таблицы антиспам |
| b2c3d4e5f6g7 | add_antispam_warning_ttl |
| c3d4e5f6g7h8 | add_delete_action_type — DELETE в enum |
| d4e5f6g7h8i9 | add_content_filter_tables — таблицы фильтра контента |
| e5f6g7h8i9j0 | add_scam_patterns_table — кастомные паттерны антискама |
| f6g7h8i9j0k1 | add_separate_actions_columns — раздельные действия для word/flood |
| g7h8i9j0k1l2 | add_word_categories_columns — категории слов (simple/harmful/obfuscated) |
| h8i9j0k1l2m3 | add_category_notification_settings — текст уведомлений и задержки |
| j0k1l2m3n4o5 | add_extended_flood_settings — расширенный антифлуд (any, media) |
| k1l2m3n4o5p6 | add_message_cleanup_settings — модуль удаления сообщений |
| l2m3n4o5p6q7 | add_scam_signal_categories — категории сигналов + flood_warn_text |
| m3n4o5p6q7r8 | add_message_management_settings — модуль управления сообщениями |
| n4o5p6q7r8s9 | add_user_restrictions_table — расширение таблицы user_restrictions |
| 9356cadad695 | add_bot_global_settings_table — глобальные настройки бота (max_seen_user_id) |
| u1v2w3x4y5z6 | add_user_statistics_table — статистика пользователей (сообщения, дни активности) |
| v2w3x4y5z6a7 | add_photo_freshness_columns — колонки для критериев автомута 4,5 |
| d0e1f2g3h4i5 | add_cross_group_detection_tables — кросс-групповая детекция скамеров |
| e1f2g3h4i5j6 | add_antiraid_tables — модуль Anti-Raid (защита от массовых атак) |

### Паттерн для ENUM в миграциях

```python
from sqlalchemy.dialects import postgresql

# Создание (идемпотентно)
connection.execute(sa.text("""
    DO $$ BEGIN
        CREATE TYPE my_enum AS ENUM ('A', 'B');
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$;
"""))

# Использование
my_enum = postgresql.ENUM('A', 'B', name='my_enum', create_type=False)
```

---

*Последнее обновление: 2026-01-17 (добавлены таблицы Anti-Raid: antiraid_settings, antiraid_name_patterns)*
