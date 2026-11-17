CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                reasoning_content TEXT NOT NULL DEFAULT '',
                attachments_json TEXT NOT NULL DEFAULT '',
                tool_trace_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

CREATE TABLE IF NOT EXISTS group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_key TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                user_key TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                reasoning_content TEXT NOT NULL DEFAULT '',
                attachments_json TEXT NOT NULL DEFAULT '',
                tool_trace_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

CREATE TABLE IF NOT EXISTS group_chat_meta (
                group_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

CREATE TABLE IF NOT EXISTS group_conversation_backgrounds (
                group_key TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                temporary_background TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (group_key, conversation_id, user_key)
            );

CREATE TABLE IF NOT EXISTS relationship_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                affection INTEGER NOT NULL DEFAULT 50,
                trust INTEGER NOT NULL DEFAULT 50,
                familiarity INTEGER NOT NULL DEFAULT 0,
                mood TEXT NOT NULL DEFAULT 'calm',
                mood_intensity INTEGER NOT NULL DEFAULT 20,
                summary TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(character, user_key)
            );

CREATE TABLE IF NOT EXISTS character_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'note',
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 50,
                source_message_id INTEGER,
                source_group_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(character, user_key, content)
            );

CREATE TABLE IF NOT EXISTS mood_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'interaction',
                affection_delta INTEGER NOT NULL DEFAULT 0,
                trust_delta INTEGER NOT NULL DEFAULT 0,
                familiarity_delta INTEGER NOT NULL DEFAULT 0,
                affection INTEGER,
                trust INTEGER,
                familiarity INTEGER,
                mood TEXT NOT NULL DEFAULT '',
                mood_intensity INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

CREATE TABLE IF NOT EXISTS usage_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                end_time TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0
            );

CREATE TABLE IF NOT EXISTS external_chat_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                thread_name TEXT NOT NULL DEFAULT '',
                chat_type TEXT NOT NULL DEFAULT '',
                unread_count INTEGER NOT NULL DEFAULT 0,
                last_message_id INTEGER,
                last_message_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(platform, thread_id)
            );

CREATE TABLE IF NOT EXISTS external_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                external_message_id TEXT NOT NULL DEFAULT '',
                sender_id TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL DEFAULT 'inbound' CHECK(direction IN ('inbound', 'outbound', 'draft')),
                content TEXT NOT NULL,
                unread INTEGER NOT NULL DEFAULT 1,
                chat_type TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
