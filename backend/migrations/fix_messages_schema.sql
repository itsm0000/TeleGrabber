-- Migration: fix_messages_schema
-- Description: Add missing columns to messages table if they do not exist
-- This migration ensures all columns defined in the schema are present.

DO $$
BEGIN
    -- Add sender column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'sender'
    ) THEN
        ALTER TABLE messages ADD COLUMN sender TEXT;
        RAISE NOTICE 'Added column sender to messages table';
    END IF;

    -- Add sender_id column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'sender_id'
    ) THEN
        ALTER TABLE messages ADD COLUMN sender_id TEXT;
        RAISE NOTICE 'Added column sender_id to messages table';
    END IF;

    -- Add text column if not exists (though likely exists)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'text'
    ) THEN
        ALTER TABLE messages ADD COLUMN text TEXT;
        RAISE NOTICE 'Added column text to messages table';
    END IF;

    -- Add reply_to_msg_id column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'reply_to_msg_id'
    ) THEN
        ALTER TABLE messages ADD COLUMN reply_to_msg_id BIGINT;
        RAISE NOTICE 'Added column reply_to_msg_id to messages table';
    END IF;

    -- Add media_path column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'media_path'
    ) THEN
        ALTER TABLE messages ADD COLUMN media_path TEXT;
        RAISE NOTICE 'Added column media_path to messages table';
    END IF;

    -- Add is_transcribed column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'is_transcribed'
    ) THEN
        ALTER TABLE messages ADD COLUMN is_transcribed BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added column is_transcribed to messages table';
    END IF;

    -- Add category column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'messages' AND column_name = 'category'
    ) THEN
        ALTER TABLE messages ADD COLUMN category TEXT;
        RAISE NOTICE 'Added column category to messages table';
    END IF;

    -- Ensure indexes exist (optional, but safe)
    -- Note: CREATE INDEX IF NOT EXISTS is available in PostgreSQL 9.5+, Supabase uses newer version.
    CREATE INDEX IF NOT EXISTS idx_messages_job_id ON messages(job_id);
    CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
    CREATE INDEX IF NOT EXISTS idx_messages_reply_to ON messages(reply_to_msg_id);
    CREATE INDEX IF NOT EXISTS idx_messages_category ON messages(category);

    RAISE NOTICE 'Messages schema migration completed successfully';
END $$;