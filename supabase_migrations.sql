-- Supabase schema updates for new features
-- Run these in Supabase SQL editor (or psql) before deploying the new app version.

-- 1) Optional priority and category on tasks
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'priority'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN priority text CHECK (priority IN ('low','medium','high'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'category'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN category text;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_tasks_priority ON public.tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_category ON public.tasks(category);
CREATE INDEX IF NOT EXISTS idx_tasks_next_due ON public.tasks(next_due_date);

-- 2) Task history table
CREATE TABLE IF NOT EXISTS public.task_history (
    id bigserial PRIMARY KEY,
    user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    task_id integer NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    action text NOT NULL CHECK (action IN ('completed','snoozed')),
    delta_days integer,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_task_history_task ON public.task_history(task_id);
CREATE INDEX IF NOT EXISTS idx_task_history_user ON public.task_history(user_id);
CREATE INDEX IF NOT EXISTS idx_task_history_created ON public.task_history(created_at DESC);

-- 3) Add new home feature flags to home_features (booleans, default false)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_water_softener'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_water_softener boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_garbage_disposal'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_garbage_disposal boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_washer_dryer'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_washer_dryer boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_sump_pump'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_sump_pump boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_well'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_well boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_fireplace'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_fireplace boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_septic'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_septic boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'home_features' AND column_name = 'has_garage'
    ) THEN
        ALTER TABLE public.home_features ADD COLUMN has_garage boolean NOT NULL DEFAULT false;
    END IF;
END$$;
