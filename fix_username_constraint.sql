-- Remove unique constraint from username field
-- Only email should be unique for user accounts

-- Drop the unique constraint on username if it exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'users_username_key'
    ) THEN
        ALTER TABLE public.users DROP CONSTRAINT users_username_key;
        RAISE NOTICE 'Dropped unique constraint on username';
    END IF;
END$$;

-- Ensure email remains unique
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'users_email_key'
    ) THEN
        ALTER TABLE public.users ADD CONSTRAINT users_email_key UNIQUE (email);
        RAISE NOTICE 'Added unique constraint on email';
    END IF;
END$$;

-- Verify the changes
SELECT 
    conname as constraint_name,
    contype as constraint_type,
    a.attname as column_name
FROM pg_constraint c
JOIN pg_attribute a ON a.attnum = ANY(c.conkey) AND a.attrelid = c.conrelid
WHERE c.conrelid = 'public.users'::regclass
    AND contype = 'u'
ORDER BY conname;
