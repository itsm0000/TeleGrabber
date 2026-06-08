-- Migration: add_max_messages_to_jobs
-- Description: Add max_messages column to extraction_jobs table to store the limit set when starting extraction

DO $$
BEGIN
    -- Add max_messages column if not exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'extraction_jobs' AND column_name = 'max_messages'
    ) THEN
        ALTER TABLE extraction_jobs ADD COLUMN max_messages INT;
        RAISE NOTICE 'Added column max_messages to extraction_jobs table';
    END IF;

    RAISE NOTICE 'Add max_messages migration completed successfully';
END $$;
