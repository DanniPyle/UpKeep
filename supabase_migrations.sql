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

-- 5) Seasonal metadata on tasks (used for seasonal icons and scheduling)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'seasonal'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN seasonal boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'seasonal_anchor_type'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN seasonal_anchor_type text; -- 'season_start' | 'fixed_date'
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'season_code'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN season_code text; -- 'winter'|'spring'|'summer'|'autumn'
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'season_anchor_month'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN season_anchor_month integer;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'season_anchor_day'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN season_anchor_day integer;
    END IF;
END$$;

-- 4) Extended questionnaire fields on home_features
DO $$
BEGIN
    -- Basic home attributes
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'home_type') THEN
        ALTER TABLE public.home_features ADD COLUMN home_type text;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'year_built') THEN
        ALTER TABLE public.home_features ADD COLUMN year_built text; -- 'pre1950' | '1950s' | ...
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'home_size') THEN
        ALTER TABLE public.home_features ADD COLUMN home_size text; -- 'lt_1000' | '1000_2000' | ...
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_yard') THEN
        ALTER TABLE public.home_features ADD COLUMN has_yard boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'carpet') THEN
        ALTER TABLE public.home_features ADD COLUMN carpet text; -- 'yes' | 'no' | 'some'
    END IF;

    -- Additional HVAC/system flags
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_window_units') THEN
        ALTER TABLE public.home_features ADD COLUMN has_window_units boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_radiator_boiler') THEN
        ALTER TABLE public.home_features ADD COLUMN has_radiator_boiler boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'no_central_hvac') THEN
        ALTER TABLE public.home_features ADD COLUMN no_central_hvac boolean NOT NULL DEFAULT false;
    END IF;

    -- Types
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'fireplace_type') THEN
        ALTER TABLE public.home_features ADD COLUMN fireplace_type text; -- 'wood' | 'gas' | 'none'
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'garage_type') THEN
        ALTER TABLE public.home_features ADD COLUMN garage_type text; -- 'attached' | 'detached' | 'none'
    END IF;

    -- Appliances
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_refrigerator_ice') THEN
        ALTER TABLE public.home_features ADD COLUMN has_refrigerator_ice boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_range_hood') THEN
        ALTER TABLE public.home_features ADD COLUMN has_range_hood boolean NOT NULL DEFAULT false;
    END IF;

    -- Exterior extras
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_deck_patio') THEN
        ALTER TABLE public.home_features ADD COLUMN has_deck_patio boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_pool_hot_tub') THEN
        ALTER TABLE public.home_features ADD COLUMN has_pool_hot_tub boolean NOT NULL DEFAULT false;
    END IF;

    -- Seasons & climate
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'freezes') THEN
        ALTER TABLE public.home_features ADD COLUMN freezes boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'season_spring') THEN
        ALTER TABLE public.home_features ADD COLUMN season_spring date;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'season_summer') THEN
        ALTER TABLE public.home_features ADD COLUMN season_summer date;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'season_autumn') THEN
        ALTER TABLE public.home_features ADD COLUMN season_autumn date;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'season_winter') THEN
        ALTER TABLE public.home_features ADD COLUMN season_winter date;
    END IF;

    -- Lifestyle
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'has_pets') THEN
        ALTER TABLE public.home_features ADD COLUMN has_pets boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'pet_dog') THEN
        ALTER TABLE public.home_features ADD COLUMN pet_dog boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'pet_cat') THEN
        ALTER TABLE public.home_features ADD COLUMN pet_cat boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'pet_other') THEN
        ALTER TABLE public.home_features ADD COLUMN pet_other boolean NOT NULL DEFAULT false;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'home_features' AND column_name = 'travel_often') THEN
        ALTER TABLE public.home_features ADD COLUMN travel_often boolean NOT NULL DEFAULT false;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_tasks_priority ON public.tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_category ON public.tasks(category);
CREATE INDEX IF NOT EXISTS idx_tasks_next_due ON public.tasks(next_due_date);
-- Soft archive flag for tasks
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'archived'
    ) THEN
        ALTER TABLE public.tasks ADD COLUMN archived boolean NOT NULL DEFAULT false;
        CREATE INDEX IF NOT EXISTS idx_tasks_archived ON public.tasks(archived);
    END IF;
END$$;

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

-- 6) Backfill existing tasks' seasonal fields from known task titles
DO $$
DECLARE
    r record;
BEGIN
    -- Create a temporary mapping table of seasonal metadata keyed by human title
    CREATE TEMP TABLE IF NOT EXISTS tmp_task_season_map_title (
        title text primary key,
        seasonal boolean,
        seasonal_anchor_type text,
        season_code text,
        season_anchor_month integer,
        season_anchor_day integer
    ) ON COMMIT DROP;

    -- Known rows from static/tasks_catalog.csv
    INSERT INTO tmp_task_season_map_title(title, seasonal, seasonal_anchor_type, season_code, season_anchor_month, season_anchor_day) VALUES
      ('Replace Smoke Detector Batteries', true, 'fixed_date', NULL, 11, 1),
      ('Winterize Outdoor Faucets', true, 'season_start', 'autumn', NULL, NULL)
    ON CONFLICT (title) DO NOTHING;

    -- Backfill by joining on the exact title
    UPDATE public.tasks t
    SET seasonal = COALESCE(t.seasonal, m.seasonal),
        seasonal_anchor_type = COALESCE(t.seasonal_anchor_type, m.seasonal_anchor_type),
        season_code = COALESCE(t.season_code, m.season_code),
        season_anchor_month = COALESCE(t.season_anchor_month, m.season_anchor_month),
        season_anchor_day = COALESCE(t.season_anchor_day, m.season_anchor_day)
    FROM tmp_task_season_map_title m
    WHERE lower(t.title) = lower(m.title);
END$$;