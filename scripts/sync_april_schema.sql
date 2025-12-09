-- ============================================================
-- СКРИПТ СИНХРОНИЗАЦИИ СХЕМЫ april_test_db
-- Выравнивает структуру БД с postgres_prod
-- Дата: 2025-12-09
-- ============================================================

-- ============================================================
-- 1. ДОБАВЛЕНИЕ КОЛОНОК В chat_settings
-- ============================================================

-- Колонки из разных миграций
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS auto_mute_scammers BOOLEAN;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS global_mute_enabled BOOLEAN;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS username VARCHAR;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS reaction_mute_enabled BOOLEAN DEFAULT false;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS reaction_mute_announce_enabled BOOLEAN DEFAULT true;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS captcha_join_enabled BOOLEAN DEFAULT false;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS captcha_invite_enabled BOOLEAN DEFAULT false;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS captcha_timeout_seconds INTEGER DEFAULT 120;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS captcha_message_ttl_seconds INTEGER DEFAULT 60;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS captcha_flood_threshold INTEGER DEFAULT 5;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS captcha_flood_window_seconds INTEGER DEFAULT 60;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS captcha_flood_action VARCHAR(20) DEFAULT 'mute';
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS system_mute_announcements_enabled BOOLEAN DEFAULT true;
ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS antispam_warning_ttl_seconds INTEGER NOT NULL DEFAULT 3600;

-- ============================================================
-- 2. СОЗДАНИЕ ENUM ТИПОВ
-- ============================================================

DO $$ BEGIN
    CREATE TYPE rule_type_enum AS ENUM (
        'TELEGRAM_LINK', 'ANY_LINK', 'FORWARD_CHANNEL', 'FORWARD_GROUP',
        'FORWARD_USER', 'FORWARD_BOT', 'QUOTE_CHANNEL', 'QUOTE_GROUP',
        'QUOTE_USER', 'QUOTE_BOT'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE action_type_enum AS ENUM ('OFF', 'WARN', 'KICK', 'RESTRICT', 'BAN', 'DELETE');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE whitelist_scope_enum AS ENUM ('TELEGRAM_LINK', 'ANY_LINK', 'FORWARD', 'QUOTE');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- 3. СОЗДАНИЕ ТАБЛИЦЫ spammers
-- ============================================================

CREATE TABLE IF NOT EXISTS spammers (
    user_id BIGINT PRIMARY KEY,
    risk_score INTEGER NOT NULL DEFAULT 0,
    reason VARCHAR,
    incidents INTEGER NOT NULL DEFAULT 1,
    last_incident_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_spammers_last_incident ON spammers (last_incident_at);

-- ============================================================
-- 4. СОЗДАНИЕ ТАБЛИЦЫ group_journal_channels
-- ============================================================

CREATE TABLE IF NOT EXISTS group_journal_channels (
    id SERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL UNIQUE,
    journal_channel_id BIGINT NOT NULL,
    journal_type VARCHAR(20) DEFAULT 'channel',
    journal_title VARCHAR,
    is_active BOOLEAN DEFAULT true,
    linked_at TIMESTAMP,
    linked_by_user_id BIGINT,
    last_event_at TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES groups(chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_group_journal_group_id ON group_journal_channels (group_id);
CREATE INDEX IF NOT EXISTS ix_group_journal_channel_id ON group_journal_channels (journal_channel_id);

-- ============================================================
-- 5. СОЗДАНИЕ ТАБЛИЦЫ group_mutes
-- ============================================================

CREATE TABLE IF NOT EXISTS group_mutes (
    id SERIAL PRIMARY KEY,
    group_id BIGINT NOT NULL,
    target_user_id BIGINT NOT NULL,
    admin_user_id BIGINT NOT NULL,
    reaction VARCHAR(16) NOT NULL,
    mute_until TIMESTAMP,
    reason VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_group_mutes_group_id ON group_mutes (group_id);
CREATE INDEX IF NOT EXISTS ix_group_mutes_target_user_id ON group_mutes (target_user_id);
CREATE INDEX IF NOT EXISTS ix_group_mutes_admin_user_id ON group_mutes (admin_user_id);

-- ============================================================
-- 6. СОЗДАНИЕ ТАБЛИЦЫ user_scores
-- ============================================================

CREATE TABLE IF NOT EXISTS user_scores (
    user_id BIGINT PRIMARY KEY,
    score INTEGER NOT NULL DEFAULT 0
);

-- ============================================================
-- 7. СОЗДАНИЕ ТАБЛИЦ ANTISPAM
-- ============================================================

CREATE TABLE IF NOT EXISTS antispam_rules (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    rule_type rule_type_enum NOT NULL,
    action action_type_enum NOT NULL,
    delete_message BOOLEAN NOT NULL DEFAULT false,
    restrict_minutes INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_antispam_rules_chat_id ON antispam_rules (chat_id);
CREATE INDEX IF NOT EXISTS ix_antispam_rules_chat_rule ON antispam_rules (chat_id, rule_type);
CREATE INDEX IF NOT EXISTS ix_antispam_rules_rule_type ON antispam_rules (rule_type);
CREATE INDEX IF NOT EXISTS ix_antispam_rules_action ON antispam_rules (action);

CREATE TABLE IF NOT EXISTS antispam_whitelist (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    scope whitelist_scope_enum NOT NULL,
    pattern TEXT NOT NULL,
    added_by BIGINT NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_antispam_whitelist_chat_id ON antispam_whitelist (chat_id);
CREATE INDEX IF NOT EXISTS ix_antispam_whitelist_scope ON antispam_whitelist (scope);
CREATE INDEX IF NOT EXISTS ix_antispam_whitelist_chat_scope ON antispam_whitelist (chat_id, scope);

-- ============================================================
-- 8. СОЗДАНИЕ ТАБЛИЦ CONTENT FILTER
-- ============================================================

CREATE TABLE IF NOT EXISTS content_filter_settings (
    chat_id BIGINT PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT false,
    word_filter_enabled BOOLEAN NOT NULL DEFAULT true,
    scam_detection_enabled BOOLEAN NOT NULL DEFAULT true,
    flood_detection_enabled BOOLEAN NOT NULL DEFAULT true,
    referral_detection_enabled BOOLEAN NOT NULL DEFAULT false,
    scam_sensitivity INTEGER NOT NULL DEFAULT 60,
    flood_max_repeats INTEGER NOT NULL DEFAULT 2,
    flood_time_window INTEGER NOT NULL DEFAULT 60,
    default_action VARCHAR(20) NOT NULL DEFAULT 'delete',
    default_mute_duration INTEGER NOT NULL DEFAULT 1440,
    log_violations BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS filter_words (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    word VARCHAR(500) NOT NULL,
    normalized VARCHAR(500) NOT NULL,
    match_type VARCHAR(20) NOT NULL DEFAULT 'word',
    action VARCHAR(20),
    action_duration INTEGER,
    category VARCHAR(50),
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE,
    UNIQUE (chat_id, word)
);

CREATE INDEX IF NOT EXISTS ix_filter_words_chat_id ON filter_words (chat_id);
CREATE INDEX IF NOT EXISTS ix_filter_words_normalized ON filter_words (normalized);
CREATE INDEX IF NOT EXISTS ix_filter_words_chat_normalized ON filter_words (chat_id, normalized);

CREATE TABLE IF NOT EXISTS filter_whitelist (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    word VARCHAR(500) NOT NULL,
    normalized VARCHAR(500) NOT NULL,
    added_by BIGINT NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE,
    UNIQUE (chat_id, word)
);

CREATE INDEX IF NOT EXISTS ix_filter_whitelist_chat_id ON filter_whitelist (chat_id);

CREATE TABLE IF NOT EXISTS filter_violations (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    detector_type VARCHAR(30) NOT NULL,
    trigger VARCHAR(500),
    scam_score INTEGER,
    message_text TEXT,
    message_id BIGINT,
    action_taken VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_filter_violations_chat_id ON filter_violations (chat_id);
CREATE INDEX IF NOT EXISTS ix_filter_violations_user_id ON filter_violations (user_id);
CREATE INDEX IF NOT EXISTS ix_violations_chat_user ON filter_violations (chat_id, user_id);
CREATE INDEX IF NOT EXISTS ix_violations_chat_date ON filter_violations (chat_id, created_at);
CREATE INDEX IF NOT EXISTS ix_filter_violations_created_at ON filter_violations (created_at);

-- ============================================================
-- 9. СОЗДАНИЕ ТАБЛИЦЫ scam_patterns
-- ============================================================

CREATE TABLE IF NOT EXISTS scam_patterns (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    pattern VARCHAR(500) NOT NULL,
    normalized VARCHAR(500) NOT NULL,
    pattern_type VARCHAR(20) NOT NULL DEFAULT 'phrase',
    weight INTEGER NOT NULL DEFAULT 25,
    category VARCHAR(50),
    is_active BOOLEAN NOT NULL DEFAULT true,
    triggers_count INTEGER NOT NULL DEFAULT 0,
    last_triggered_at TIMESTAMP,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    FOREIGN KEY (chat_id) REFERENCES groups(chat_id) ON DELETE CASCADE,
    UNIQUE (chat_id, pattern)
);

CREATE INDEX IF NOT EXISTS ix_scam_patterns_chat_id ON scam_patterns (chat_id);
CREATE INDEX IF NOT EXISTS ix_scam_patterns_normalized ON scam_patterns (normalized);
CREATE INDEX IF NOT EXISTS ix_scam_patterns_chat_active ON scam_patterns (chat_id, is_active);

-- ============================================================
-- 10. УСТАНОВКА ВЕРСИИ ALEMBIC
-- ============================================================

-- Очищаем таблицу версий
DELETE FROM alembic_version;

-- Устанавливаем текущую версию (head из postgres_prod)
INSERT INTO alembic_version (version_num) VALUES ('h8i9j0k1l2m3');

-- ============================================================
-- ГОТОВО! Схема синхронизирована.
-- ============================================================
