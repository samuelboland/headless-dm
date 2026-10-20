-- Guidance (isekai branch): what the operator sent one person as a system message, and what it changed.
-- Written by services/lore/guidance.py through the lore gate; lives in acore_characters beside lore_character.
-- `plan` keeps both what was applied and what it replaced, so a message can be taken back.

CREATE TABLE IF NOT EXISTS guidance (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    guid          INT UNSIGNED NOT NULL COMMENT 'Who received it',
    kind          VARCHAR(8)   NOT NULL COMMENT 'goal, know, feel or free: what the operator asked for',
    asked         TEXT         NOT NULL COMMENT 'The operator''s own words',
    notice        VARCHAR(255) NOT NULL COMMENT 'The words of the system window',
    plan          JSON         NOT NULL COMMENT 'What was applied, and what it replaced',
    state         VARCHAR(12)  NOT NULL DEFAULT 'sent' COMMENT 'sent or taken back',
    taken_back_at DATETIME     NULL,
    KEY by_guid (guid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
