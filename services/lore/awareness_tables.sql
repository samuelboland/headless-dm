-- Awareness (isekai branch): who learned that this world is a game, from whom, and on what evidence.
-- Written by services/lore/awareness.py; lives in acore_characters beside lore_character. The current
-- level itself is lore_character.knows_game / knows_game_from; this is the record of how it got there.

CREATE TABLE IF NOT EXISTS awareness_event (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    learner_guid INT UNSIGNED NOT NULL,
    teller_guid  INT UNSIGNED NOT NULL,
    from_level  TINYINT      NOT NULL COMMENT 'What the learner knew before: 0',
    to_level    TINYINT      NOT NULL COMMENT 'What they know now: 1, heard it from the teller',
    evidence    VARCHAR(120) NOT NULL COMMENT 'Why these two count as having talked',
    KEY by_learner (learner_guid),
    KEY by_teller (teller_guid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- How far the service has read: regard_log and bot_talk ids, so a restart does not replay old
-- conversations, and the day (as a date ordinal) the bios were last projected.
CREATE TABLE IF NOT EXISTS awareness_cursor (
    source  VARCHAR(16)     NOT NULL PRIMARY KEY COMMENT 'regard_log, bot_talk or project',
    last_id BIGINT UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
