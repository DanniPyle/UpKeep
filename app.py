from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client
from datetime import datetime, timedelta, date
import os
from os import makedirs
from os.path import join, exists
import jwt
from functools import wraps
from dotenv import load_dotenv
import csv
import io

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')
CORS(app)

# Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_ANON_KEY environment variables")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Runtime feature flag: whether the 'tasks.task_key' column exists in the DB.
# If inserts fail due to schema cache or missing column, we'll disable it and retry without.
TASK_KEY_SUPPORTED = True

# Jinja filter: render due dates as Today / N days ago / YYYY-MM-DD
@app.template_filter('due_label')
def due_label(value):
    """Format an ISO date string or date/datetime as a friendly due label.
    - Today => "Today"
    - Past => "N days ago"
    - Future => YYYY-MM-DD
    """
    try:
        if value in (None, ''):
            return '-'
        if isinstance(value, datetime):
            d = value.date()
        elif isinstance(value, date):
            d = value
        else:
            d = datetime.fromisoformat(str(value)).date()
        today = datetime.now().date()
        diff = (today - d).days
        if diff == 0:
            return 'Today'
        if diff > 0:
            return f"{diff} days ago"
        return d.isoformat()
    except Exception:
        return str(value)

# Jinja filter: conversational frequency label from days
@app.template_filter('frequency_label')
def frequency_label(days):
    try:
        if days is None:
            return '-'
        d = int(days)
    except Exception:
        return str(days)
    mapping = {
        7: 'Weekly',
        14: 'Every 2 Weeks',
        21: 'Every 3 Weeks',
        28: 'Every 4 Weeks',
        30: 'Monthly',
        60: 'Every 2 Months',
        90: 'Quarterly',
        120: 'Every 4 Months',
        180: 'Every 6 Months',
        270: 'Every 9 Months',
        365: 'Yearly',
        730: 'Every 2 Years',
        1095: 'Every 3 Years',
        1825: 'Every 5 Years',
    }
    if d in mapping:
        return mapping[d]
    # Heuristics: show common month/years when near multiples
    if d % 365 == 0:
        n = d // 365
        return f"Every {n} Year{'s' if n != 1 else ''}"
    if d % 30 == 0:
        n = d // 30
        if n == 1:
            return 'Monthly'
        return f"Every {n} Months"
    if d % 7 == 0 and d <= 84:
        n = d // 7
        return f"Every {n} Week{'s' if n != 1 else ''}"
    return f"Every {d} days"

# JWT token decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            if token.startswith('Bearer '):
                token = token[7:]
            data = jwt.decode(token, app.secret_key, algorithms=['HS256'])
            current_user_id = data['user_id']
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Token is invalid'}), 401
        
        return f(current_user_id, *args, **kwargs)
    return decorated

# Task templates based on home features
TASK_TEMPLATES = {
    'has_hvac': [
        {'title': 'Replace HVAC Filter', 'description': 'Replace air filter for better air quality and efficiency', 'frequency_days': 30},
        {'title': 'Vacuum out HVAC return grills', 'description': 'Use vacuum brush attachment to clean out debris', 'frequency_days': 180},
        {'title': 'Add vinegar to HVAC system', 'description': 'Add 1/4 cup distiled white vinegar to drain pump in HVAC to prevent mold and bacteria', 'frequency_days': 30}
    ],
    'has_gutters': [
        {'title': 'Clean Gutters', 'description': 'Remove leaves and debris from gutters and downspouts', 'frequency_days': 90},
        {'title': 'Inspect Gutters', 'description': 'Check for damage, loose connections, or clogs', 'frequency_days': 180}
    ],
    'has_dishwasher': [
        {'title': 'Clean Dishwasher Filter', 'description': 'Remove and clean the dishwasher filter', 'frequency_days': 30},
        {'title': 'Run Dishwasher Cleaning Cycle', 'description': 'Use dishwasher cleaner or vinegar to clean the interior', 'frequency_days': 90}
    ],
    'has_smoke_detectors': [
        {'title': 'Test Smoke Detectors', 'description': 'Press test button on all smoke detectors', 'frequency_days': 30},
        {'title': 'Replace Smoke Detector Batteries', 'description': 'Replace batteries in all smoke detectors', 'frequency_days': 365}
    ],
    'has_water_heater': [
        {'title': 'Flush Water Heater', 'description': 'Drain and flush water heater to remove sediment', 'frequency_days': 365},
        {'title': 'Check Water Heater Temperature', 'description': 'Ensure water heater is set to 120°F (49°C)', 'frequency_days': 180}
    ],
    # Minimal additions to reflect new fields if CSV catalog is not present
    'freezes': [
        {'title': 'Insulate Outdoor Faucets', 'description': 'Install/inspect faucet covers before freezing temps', 'frequency_days': 365},
    ],
    'has_pets': [
        {'title': 'Deep Clean Pet Areas', 'description': 'Clean pet bedding and vacuum hair in corners', 'frequency_days': 30},
    ],
    'has_range_hood': [
        {'title': 'Degrease Range Hood Filter', 'description': 'Soak and clean the hood filter to improve airflow', 'frequency_days': 60},
    ],
}

# Accept common aliases/typos from catalog and map to canonical keys
FEATURE_KEY_ALIASES = {
    'has_disposal': 'has_garbage_disposal',
    'has_washer': 'has_washer_dryer',
    'has_smoke_dectectors': 'has_smoke_detectors',  # typo variant
}

# --- Catalog import/validation constants & helpers ---
ALLOWED_FEATURE_KEYS = {
    # Core features
    'has_hvac',
    'has_gutters',
    'has_dishwasher',
    'has_smoke_detectors',
    'has_water_heater',
    'has_water_softener',
    'has_garbage_disposal',
    'has_washer_dryer',
    'has_sump_pump',
    'has_well',
    'has_fireplace',
    'has_septic',
    'has_garage',
    # Extended boolean features added by wizard
    'has_window_units',
    'has_radiator_boiler',
    'no_central_hvac',
    'has_refrigerator_ice',
    'has_range_hood',
    'has_deck_patio',
    'has_pool_hot_tub',
    'freezes',
    'has_pets',
    'pet_dog',
    'pet_cat',
    'pet_other',
    'travel_often',
    'has_yard',
}

PRIORITY_VALUES = {'low', 'medium', 'high'}

# Default meteorological season starts (Northern hemisphere). Future: user-defined seasons.
DEFAULT_SEASON_STARTS = {
    'winter': (12, 1),
    'spring': (3, 1),
    'summer': (6, 1),
    'autumn': (9, 1),
}

EXPECTED_COLUMNS = [
    'task_key', 'title', 'description', 'frequency_days', 'category', 'priority',
    'feature_requirements', 'start_offset_days', 'seasonal', 'seasonal_anchor_type',
    'season_code', 'season_anchor_month', 'season_anchor_day', 'overlap_group',
    'variant_rank', 'safety_critical', 'notes'
]

# Onboarding ramp settings to avoid flooding new users with too many immediate tasks
RAMP_SETTINGS = {
    'enabled': True,
    # Tasks with next due within this window are considered "near-term" and kept
    'near_term_days': 21,
    # How many non-critical tasks to make active immediately on first seed
    'initial_cap': 8,
    # Stagger the rest over this many weeks
    'stagger_weeks': 8,
}

def _parse_bool(val, default=None):
    if val is None:
        return default
    s = str(val).strip().lower()
    if s in ('true', '1', 'yes', 'y'):
        return True
    if s in ('false', '0', 'no', 'n'):
        return False
    return default

def _parse_int(val, default=None):
    try:
        if val is None or str(val).strip() == '':
            return default
        return int(str(val).strip())
    except Exception:
        return default

def _parse_feature_requirements(s):
    """Parse semicolon-separated key=value into dict with boolean values.
    Returns (req_dict, errors)
    """
    req = {}
    errors = []
    if not s or str(s).strip() == '':
        return req, errors
    parts = [p.strip() for p in str(s).split(';') if p.strip()]
    for part in parts:
        if '=' not in part:
            errors.append(f"invalid requirement '{part}' (expected key=value)")
            continue
        key, value = part.split('=', 1)
        key = key.strip()
        # Map alias if present
        if key in FEATURE_KEY_ALIASES:
            key = FEATURE_KEY_ALIASES[key]
        value = value.strip()
        if key not in ALLOWED_FEATURE_KEYS:
            # Ignore unknown keys gracefully instead of dropping the row
            # (keeps catalog resilient to minor naming differences)
            continue
        b = _parse_bool(value, default=None)
        if b is None:
            errors.append(f"invalid boolean for '{key}' -> '{value}'")
            continue
        req[key] = b
    return req, errors

def _valid_month_day(month, day):
    try:
        # Use leap year to allow Feb 29 in validation
        datetime(year=2024, month=month, day=day)
        return True
    except Exception:
        return False

def _validate_catalog_row(row):
    """Return list of issues for this row (empty if valid)."""
    issues = []

    task_key = (row.get('task_key') or '').strip()
    title = (row.get('title') or '').strip()
    if not task_key:
        issues.append('task_key is required')
    if not title:
        issues.append('title is required')

    priority = (row.get('priority') or '').strip().lower()
    if priority and priority not in PRIORITY_VALUES:
        issues.append(f"priority must be one of {sorted(PRIORITY_VALUES)}")

    seasonal = _parse_bool(row.get('seasonal'), default=False)
    seasonal_anchor_type = (row.get('seasonal_anchor_type') or '').strip().lower()
    season_code = (row.get('season_code') or '').strip().lower()
    season_anchor_month = _parse_int(row.get('season_anchor_month'), default=None)
    season_anchor_day = _parse_int(row.get('season_anchor_day'), default=None)

    freq = _parse_int(row.get('frequency_days'), default=None)
    if not seasonal:
        if freq is None or freq < 1:
            issues.append('frequency_days must be an integer >= 1 for non-seasonal tasks')
    else:
        if seasonal_anchor_type not in ('season_start', 'fixed_date'):
            issues.append("seasonal_anchor_type must be 'season_start' or 'fixed_date' when seasonal=true")
        if seasonal_anchor_type == 'season_start':
            if season_code not in DEFAULT_SEASON_STARTS:
                issues.append("season_code must be one of winter|spring|summer|autumn when seasonal_anchor_type=season_start")
        if seasonal_anchor_type == 'fixed_date':
            if season_anchor_month is None or season_anchor_day is None:
                issues.append('season_anchor_month and season_anchor_day are required when seasonal_anchor_type=fixed_date')
            else:
                if not _valid_month_day(season_anchor_month, season_anchor_day):
                    issues.append('season_anchor_month/day is not a valid calendar date')

    start_offset = _parse_int(row.get('start_offset_days'), default=None)
    if start_offset is not None and start_offset < 0:
        issues.append('start_offset_days must be >= 0')

    variant_rank = _parse_int(row.get('variant_rank'), default=None)
    if row.get('overlap_group') and (variant_rank is None or variant_rank < 1):
        issues.append('variant_rank must be an integer >= 1 when overlap_group is provided')

    safety = row.get('safety_critical')
    if safety not in (None, '') and _parse_bool(safety, default=None) is None:
        issues.append('safety_critical must be true/false')

    # feature requirements
    _, req_errors = _parse_feature_requirements(row.get('feature_requirements'))
    issues.extend(req_errors)

    return issues

def _next_anchor_date(month, day, base_date=None):
    if base_date is None:
        base_date = datetime.now().date()
    year = base_date.year
    try:
        candidate = datetime(year=year, month=month, day=day).date()
    except Exception:
        # Should not happen if validated
        candidate = base_date
    if candidate < base_date:
        candidate = datetime(year=year + 1, month=month, day=day).date()
    return candidate

def _compute_next_due_date(row, today=None):
    if today is None:
        today = datetime.now().date()
    seasonal = _parse_bool(row.get('seasonal'), default=False)
    if seasonal:
        anchor_type = (row.get('seasonal_anchor_type') or '').strip().lower()
        if anchor_type == 'fixed_date':
            m = _parse_int(row.get('season_anchor_month'))
            d = _parse_int(row.get('season_anchor_day'))
            if m and d:
                return _next_anchor_date(m, d, today)
        elif anchor_type == 'season_start':
            code = (row.get('season_code') or '').strip().lower()
            if code in DEFAULT_SEASON_STARTS:
                m, d = DEFAULT_SEASON_STARTS[code]
                return _next_anchor_date(m, d, today)
        # Fallback
        freq = max(1, _parse_int(row.get('frequency_days'), default=365) or 365)
        return today + timedelta(days=freq)
    # Non-seasonal
    offset = _parse_int(row.get('start_offset_days'), default=None)
    if offset is not None:
        return today + timedelta(days=max(0, offset))
    freq = max(1, _parse_int(row.get('frequency_days'), default=30) or 30)
    return today + timedelta(days=freq)

def _read_csv_upload(file_storage):
    if not file_storage:
        raise ValueError('No file provided')
    content = file_storage.read()
    try:
        text = content.decode('utf-8-sig')
    except Exception:
        text = content.decode('utf-8', errors='ignore')
    sio = io.StringIO(text)
    reader = csv.DictReader(sio)
    rows = [dict(r) for r in reader]
    headers = reader.fieldnames or []
    return headers, rows

def _filter_rows_by_features(rows, features):
    """Return only rows whose feature_requirements all match the user's features."""
    kept = []
    for r in rows:
        req, req_errors = _parse_feature_requirements(r.get('feature_requirements'))
        if req_errors:
            # invalid reqs -> drop in importer (validator will report)
            continue
        ok = True
        for k, v in req.items():
            if bool(features.get(k, False)) != bool(v):
                ok = False
                break
        if ok:
            kept.append(r)
    return kept

def _resolve_overlaps(rows):
    by_group = {}
    for r in rows:
        group = (r.get('overlap_group') or '').strip()
        if not group:
            # Use unique key per row when no group
            key = f"__unique__::{r.get('task_key') or r.get('title')}::{id(r)}"
            by_group[key] = r
            continue
        rank = _parse_int(r.get('variant_rank'), default=999999)
        cur = by_group.get(group)
        if cur is None or _parse_int(cur.get('variant_rank'), default=999999) > rank:
            by_group[group] = r
    return list(by_group.values())

def _insert_tasks_for_user(user_id, rows):
    global TASK_KEY_SUPPORTED
    to_insert = []
    today = datetime.now().date()
    for r in rows:
        title = (r.get('title') or '').strip()
        if not title:
            continue
        task_key = (r.get('task_key') or '').strip() or None
        description = (r.get('description') or '').strip()
        category = (r.get('category') or '').strip() or None
        priority = (r.get('priority') or '').strip().lower() or None
        if priority and priority not in PRIORITY_VALUES:
            priority = None

        # frequency: ensure integer, default to 30 for non-seasonal, 365 for seasonal
        seasonal = _parse_bool(r.get('seasonal'), default=False)
        default_freq = 365 if seasonal else 30
        frequency_days = _parse_int(r.get('frequency_days'), default=default_freq) or default_freq
        if frequency_days < 1:
            frequency_days = default_freq

        next_due = _compute_next_due_date(r, today)

        payload = {
            'user_id': user_id,
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'next_due_date': next_due.isoformat(),
            'is_completed': False,
            'priority': priority,
            'category': category,
            # Persist seasonal metadata so UI can render icons
            'seasonal': seasonal,
            'seasonal_anchor_type': (r.get('seasonal_anchor_type') or None),
            'season_code': ((r.get('season_code') or '').strip().lower() or None),
            'season_anchor_month': _parse_int(r.get('season_anchor_month'), default=None),
            'season_anchor_day': _parse_int(r.get('season_anchor_day'), default=None),
        }
        # Only include task_key if supported (may be disabled if schema missing or cache stale)
        if TASK_KEY_SUPPORTED and task_key:
            payload['task_key'] = task_key
        to_insert.append(payload)

    if to_insert:
        # Insert in batches to avoid payload/row limits
        batch_size = 50
        for i in range(0, len(to_insert), batch_size):
            batch = to_insert[i:i+batch_size]
            try:
                supabase.table('tasks').insert(batch).execute()
            except Exception as e:
                msg = str(e)
                print(f"Error inserting batch {i//batch_size+1}: {msg}")
                # If the failure is due to missing/uncached task_key column, strip it and retry once
                if 'task_key' in msg.lower():
                    TASK_KEY_SUPPORTED = False
                    sanitized = []
                    for row in batch:
                        if 'task_key' in row:
                            row = dict(row)
                            row.pop('task_key', None)
                        sanitized.append(row)
                    try:
                        supabase.table('tasks').insert(sanitized).execute()
                        print(f"Retried batch {i//batch_size+1} without task_key and succeeded.")
                        continue
                    except Exception as e2:
                        print(f"Retry without task_key failed for batch {i//batch_size+1}: {e2}")
                # Continue with remaining batches to salvage progress
                continue

def _apply_onboarding_ramp(rows, today=None, first_seed=False):
    """Mutate CSV row dicts in-place to add start_offset_days for non-critical tasks.
    Rules:
      - If not first_seed or ramp disabled: no-op
      - Safety-critical (safety_critical=true) always kept immediate
      - Seasonal tasks whose computed next_due is within near_term_days kept immediate
      - Up to initial_cap other tasks kept immediate (by priority/category ordering)
      - Remaining tasks are staggered across stagger_weeks by setting start_offset_days
    """
    if not first_seed or not RAMP_SETTINGS.get('enabled', True):
        return rows
    if today is None:
        today = datetime.now().date()

    near_term_days = int(RAMP_SETTINGS.get('near_term_days', 21))
    initial_cap = int(RAMP_SETTINGS.get('initial_cap', 8))
    stagger_weeks = max(1, int(RAMP_SETTINGS.get('stagger_weeks', 8)))

    # Prepare scored list
    scored = []
    immediate = []
    later = []
    for r in rows:
        seasonal = _parse_bool(r.get('seasonal'), default=False)
        priority = (r.get('priority') or '').strip().lower()
        safety = _parse_bool(r.get('safety_critical'), default=False)
        # compute next_due as if no offset
        nd = _compute_next_due_date(r, today)
        days_out = (nd - today).days
        score = 0
        if safety:
            score += 100
        if priority == 'high':
            score += 20
        elif priority == 'medium':
            score += 10
        if seasonal and days_out <= near_term_days:
            score += 15
        scored.append((score, days_out, r))

    # Sort by score desc, then soonest due
    scored.sort(key=lambda t: (-t[0], t[1]))

    # Keep all safety immediate
    for _, _, r in scored:
        if _parse_bool(r.get('safety_critical'), default=False):
            immediate.append(r)
        else:
            later.append(r)

    # Pull near-term seasonal into immediate
    near_term = [r for r in later if _parse_bool(r.get('seasonal'), default=False) and (_compute_next_due_date(r, today) - today).days <= near_term_days]
    for r in near_term:
        if r in later:
            later.remove(r)
            immediate.append(r)

    # Fill remaining immediate up to cap
    remaining_slots = max(0, initial_cap - len([r for r in immediate if not _parse_bool(r.get('seasonal'), default=False)]))
    for _, _, r in scored:
        if r in immediate:
            continue
        if remaining_slots <= 0:
            break
        immediate.append(r)
        if r in later:
            later.remove(r)
        remaining_slots -= 1

    # Stagger the rest across weeks
    if later:
        per_week = max(1, len(later) // stagger_weeks + (1 if len(later) % stagger_weeks else 0))
        week = 0
        count = 0
        for r in later:
            # Only set offset if not already defined in CSV
            if _parse_int(r.get('start_offset_days'), default=None) is None:
                r['start_offset_days'] = str(7 * week)
            count += 1
            if count >= per_week:
                count = 0
                week += 1
    return rows

def _backfill_from_templates(user_id, features):
    """Insert tasks from TASK_TEMPLATES for enabled features that are not already present.
    Uses title-based de-duplication so catalog entries win.
    """
    try:
        # Titles already present for user
        existing = supabase.table('tasks').select('title').eq('user_id', user_id).execute()
        existing_titles = { (row.get('title') or '').strip().lower() for row in (existing.data or []) }
        to_insert = []
        today = datetime.now().date()
        for feature, enabled in features.items():
            if not enabled:
                continue
            if feature not in TASK_TEMPLATES:
                continue
            for t in TASK_TEMPLATES[feature]:
                title = (t.get('title') or '').strip()
                if not title or title.lower() in existing_titles:
                    continue
                freq = int(t.get('frequency_days') or 30)
                next_due = today + timedelta(days=freq)
                to_insert.append({
                    'user_id': user_id,
                    'title': title,
                    'description': t.get('description') or None,
                    'frequency_days': freq,
                    'next_due_date': next_due.isoformat(),
                    'is_completed': False,
                    'priority': None,
                    'category': None
                })
        if to_insert:
            supabase.table('tasks').insert(to_insert).execute()
    except Exception as e:
        print(f"Error backfilling templates: {e}")

def seed_tasks_from_catalog_rows(user_id, features, all_rows):
    """Clear existing tasks and seed from provided catalog rows, filtered & overlap-resolved.
    Applies onboarding ramp on first seed to avoid overwhelming the user.
    """
    # Determine if this is the user's first seed (no tasks yet)
    existing = supabase.table('tasks').select('id').eq('user_id', user_id).limit(1).execute()
    first_seed = not bool(existing.data)

    # Clear only upcoming/future active tasks (preserve completed and overdue)
    today_iso = datetime.now().date().isoformat()
    # Delete active, non-archived tasks due today or later
    try:
        supabase.table('tasks').delete() \
            .eq('user_id', user_id) \
            .eq('archived', False) \
            .eq('is_completed', False) \
            .gte('next_due_date', today_iso) \
            .execute()
        # Also delete undated active tasks (no next_due_date)
        supabase.table('tasks').delete() \
            .eq('user_id', user_id) \
            .eq('archived', False) \
            .eq('is_completed', False) \
            .is_('next_due_date', None) \
            .execute()
    except Exception as e:
        print(f"Selective clear failed, falling back to full clear of active tasks: {e}")
        try:
            supabase.table('tasks').delete() \
                .eq('user_id', user_id) \
                .eq('archived', False) \
                .eq('is_completed', False) \
                .execute()
        except Exception as e2:
            print(f"Fallback clear failed: {e2}")
    filtered = _filter_rows_by_features(all_rows, features)
    resolved = _resolve_overlaps(filtered)
    # Apply ramp if first seed
    resolved = _apply_onboarding_ramp(resolved, today=datetime.now().date(), first_seed=first_seed)
    _insert_tasks_for_user(user_id, resolved)

def seed_tasks_from_static_catalog_or_templates(user_id, features):
    """If a static CSV catalog exists, seed from it; otherwise use TASK_TEMPLATES."""
    try:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        static_catalog = os.path.join(root_dir, 'static', 'tasks_catalog.csv')
        if os.path.isfile(static_catalog):
            with open(static_catalog, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                rows = [dict(r) for r in reader]
            seed_tasks_from_catalog_rows(user_id, features, rows)
            # After catalog seed, backfill with templates for enabled features not covered by catalog
            _backfill_from_templates(user_id, features)
            return True
    except Exception as e:
        print(f"Error seeding from static catalog: {e}")
    
    # Fallback to existing templates
    try:
        tasks_to_insert = []
        for feature, has_feature in features.items():
            if has_feature and feature in TASK_TEMPLATES:
                for task_template in TASK_TEMPLATES[feature]:
                    next_due = datetime.now() + timedelta(days=task_template['frequency_days'])
                    tasks_to_insert.append({
                        'user_id': user_id,
                        'title': task_template['title'],
                        'description': task_template['description'],
                        'frequency_days': task_template['frequency_days'],
                        'next_due_date': next_due.date().isoformat(),
                        'is_completed': False,
                        'priority': None,
                        'category': None
                    })
        if tasks_to_insert:
            supabase.table('tasks').insert(tasks_to_insert).execute()
        return True
    except Exception as e:
        print(f"Error generating tasks from templates: {e}")
        return False

def reactivate_due_tasks(user_id):
    """Reactivate completed tasks that are now due"""
    today = datetime.now().date().isoformat()
    try:
        supabase.table('tasks').update({
            'is_completed': False
        }).eq('user_id', user_id).eq('is_completed', True).eq('archived', False).lte('next_due_date', today).execute()
    except Exception as e:
        print(f"Error reactivating tasks: {e}")

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    # Not logged in: show welcome/landing page
    return render_template('index.html')

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        # Load current user
        ures = supabase.table('users').select('*').eq('id', user_id).execute()
        if not ures.data:
            flash('User not found')
            return redirect(url_for('dashboard'))
        user = ures.data[0]

        if request.method == 'POST':
            name = (request.form.get('username') or '').strip()
            email = (request.form.get('email') or '').strip()
            current_pw = request.form.get('current_password') or ''
            new_pw = request.form.get('new_password') or ''
            confirm_pw = request.form.get('confirm_password') or ''

            updates = {}

            # Update username
            if name and name != user.get('username'):
                # Ensure unique
                exists = supabase.table('users').select('id').eq('username', name).neq('id', user_id).execute()
                if exists.data:
                    flash('That username is already taken')
                    return redirect(url_for('settings'))
                updates['username'] = name

            # Update email
            if email and email != user.get('email'):
                exists = supabase.table('users').select('id').eq('email', email).neq('id', user_id).execute()
                if exists.data:
                    flash('That email is already in use')
                    return redirect(url_for('settings'))
                updates['email'] = email

            # Update password
            if any([current_pw, new_pw, confirm_pw]):
                if not (current_pw and new_pw and confirm_pw):
                    flash('To change your password, fill out all password fields')
                    return redirect(url_for('settings'))
                if new_pw != confirm_pw:
                    flash('New password and confirmation do not match')
                    return redirect(url_for('settings'))
                # Verify current password
                if not check_password_hash(user.get('password_hash', ''), current_pw):
                    flash('Current password is incorrect')
                    return redirect(url_for('settings'))
                updates['password_hash'] = generate_password_hash(new_pw)

            if updates:
                supabase.table('users').update(updates).eq('id', user_id).execute()
                # Update session username if changed
                if 'username' in updates:
                    session['username'] = updates['username']
                flash('Settings updated')
                return redirect(url_for('settings'))

            flash('No changes to update')
            return redirect(url_for('settings'))

        # GET request: render settings page
        return render_template('settings.html', user=user)
    except Exception as e:
        flash(f'Error loading settings: {str(e)}')
        return redirect(url_for('dashboard'))
    # Not logged in: show welcome/landing page
    return render_template('index.html')

@app.route('/api/debug/features')
def api_debug_features():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        res = supabase.table('home_features').select('*').eq('user_id', user_id).execute()
        return jsonify({'user_id': user_id, 'features': (res.data[0] if res.data else {})})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug/tasks')
def api_debug_tasks():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        res = supabase.table('tasks').select('id,title,category,priority,next_due_date,seasonal').eq('user_id', user_id).order('title').execute()
        return jsonify({'count': len(res.data or []), 'tasks': res.data or []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug/seed_preview')
def api_debug_seed_preview():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        # Load features
        features_row = {}
        fres = supabase.table('home_features').select('*').eq('user_id', user_id).execute()
        if fres.data:
            features_row = fres.data[0]
        # Normalize to boolean flags only that are recognized
        feature_flags = {k: bool(features_row.get(k, False)) for k in ALLOWED_FEATURE_KEYS}

        # Load static catalog
        root_dir = os.path.dirname(os.path.abspath(__file__))
        static_catalog = os.path.join(root_dir, 'static', 'tasks_catalog.csv')
        if not os.path.isfile(static_catalog):
            return jsonify({'error': 'static/tasks_catalog.csv not found'}), 404
        with open(static_catalog, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]

        # Filter and resolve overlaps using the same logic as seeding
        filtered = _filter_rows_by_features(rows, feature_flags)
        resolved = _resolve_overlaps(filtered)
        titles = [r.get('title') for r in resolved]
        return jsonify({
            'user_id': user_id,
            'features': feature_flags,
            'catalog_rows': len(rows),
            'matched_before_overlap': len(filtered),
            'matched_after_overlap': len(resolved),
            'titles': titles,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    features = {}
    overview = None
    upcoming_tasks = []
    try:
        res = supabase.table('home_features').select('*').eq('user_id', user_id).execute()
        if res.data:
            features = res.data[0]
    except Exception as e:
        # Non-fatal: just show page without features if load fails
        print(f"Error loading home_features: {e}")

    # Compute lightweight overview metrics (reuse logic from dashboard simplified)
    try:
        t_res = supabase.table('tasks').select('*').eq('user_id', user_id).eq('archived', False).execute()
        all_tasks = t_res.data or []
        today = datetime.now().date()
        overdue = []
        upcoming = []
        future = []
        completed_recent = 0
        # Completed in last 30 days via history
        try:
            hist = supabase.table('task_history').select('created_at').eq('user_id', user_id).eq('action', 'completed').order('created_at', desc=True).limit(500).execute()
            cutoff = datetime.now() - timedelta(days=30)
            for h in (hist.data or []):
                try:
                    ts = datetime.fromisoformat(h['created_at'].replace('Z','+00:00'))
                    if ts >= cutoff:
                        completed_recent += 1
                except Exception:
                    pass
        except Exception:
            pass

        for t in all_tasks:
            nd = t.get('next_due_date')
            if not nd:
                future.append(t)
                continue
            try:
                d = datetime.fromisoformat(nd).date()
            except Exception:
                future.append(t)
                continue
            if d < today:
                overdue.append(t)
            else:
                # next 30 days count for upcoming list here, but preview tile uses 7 in dashboard; we will keep 30-day upcoming list length separately
                if d <= today + timedelta(days=30):
                    upcoming.append(t)
                else:
                    future.append(t)

        # Due in next 7 days for tile parity
        next_week = today + timedelta(days=7)
        due_7 = 0
        for t in all_tasks:
            nd = t.get('next_due_date')
            if not nd:
                continue
            try:
                d = datetime.fromisoformat(nd).date()
                if today <= d <= next_week:
                    due_7 += 1
            except Exception:
                continue
        overview = {
            'total_active': len(all_tasks),
            'overdue_count': len(overdue),
            'due_7_days': due_7,
            'completed_7_days': completed_recent,  # using 30 days if 7 unavailable; conservative preview
        }
        upcoming_tasks = upcoming
    except Exception as e:
        print(f"Error computing home overview: {e}")
    # Banner photo now persisted in DB (home_features.banner_url)
    banner_url = (features or {}).get('banner_url')
    return render_template('home.html', features=features, banner_url=banner_url, overview=overview, upcoming_tasks=upcoming_tasks)

@app.route('/home/photo', methods=['POST'])
def upload_home_photo():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    file = request.files.get('photo')
    if not file or file.filename == '':
        flash('Please choose an image to upload')
        return redirect(url_for('home'))
    # Basic extension whitelist
    allowed = {'.png', '.jpg', '.jpeg', '.webp'}
    name = secure_filename(file.filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in allowed:
        flash('Unsupported image type. Please upload PNG, JPG, or WEBP.')
        return redirect(url_for('home'))
    # Upload to Supabase Storage (bucket must exist and be public-read)
    try:
        bucket = 'home-photos'
        object_path = f"user_{session['user_id']}/banner{ext}"
        # Upload file bytes
        file.stream.seek(0)
        data = file.read()
        supabase.storage.from_(bucket).upload(path=object_path, file=data, file_options={
            'content-type': file.mimetype or f"image/{ext.strip('.')}",
            'x-upsert': 'true'
        })
        public_url = supabase.storage.from_(bucket).get_public_url(object_path)
        # Persist URL in home_features
        user_id = session['user_id']
        existing = supabase.table('home_features').select('user_id').eq('user_id', user_id).execute()
        if existing.data:
            supabase.table('home_features').update({'banner_url': public_url, 'user_id': user_id}).eq('user_id', user_id).execute()
        else:
            supabase.table('home_features').insert({'user_id': user_id, 'banner_url': public_url}).execute()
        flash('Photo updated!')
    except Exception as e:
        flash(f'Upload failed. Ensure bucket "home-photos" exists and is public. Error: {e}')
    return redirect(url_for('home'))
@app.route('/home/basics', methods=['POST'])
def save_home_basics():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    # Read and normalize inputs
    address = (request.form.get('address') or '').strip() or None
    year_built = (request.form.get('year_built') or '').strip() or None
    def _to_int(val):
        try:
            return int(val) if val not in (None, '') else None
        except Exception:
            return None
    def _to_decimal_str(val):
        try:
            v = str(val).strip()
            if v == '':
                return None
            float(v)  # validate
            return v
        except Exception:
            return None
    square_feet = _to_int(request.form.get('square_feet'))
    beds = _to_int(request.form.get('beds'))
    baths = _to_decimal_str(request.form.get('baths'))

    payload = {
        'user_id': user_id,
        'address': address,
        'year_built': year_built,
        'square_feet': square_feet,
        'beds': beds,
        'baths': baths,
    }
    try:
        existing = supabase.table('home_features').select('id').eq('user_id', user_id).execute()
        if existing.data:
            supabase.table('home_features').update(payload).eq('user_id', user_id).execute()
        else:
            supabase.table('home_features').insert(payload).execute()
        flash('Home basics saved')
    except Exception as e:
        flash(f'Failed to save basics: {e}')
    return redirect(url_for('home'))

@app.route('/tasks/<int:task_id>/history')
def task_history(task_id):
    """Server-rendered partial for task history suitable to inject into modal body."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    user_id = session['user_id']
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    try:
        # Verify task belongs to user and get minimal details
        task_result = supabase.table('tasks').select('id,title').eq('id', task_id).eq('user_id', user_id).execute()
        if not task_result.data:
            return jsonify({'error': 'Task not found'}), 404
        task = task_result.data[0]

        # Load history entries (most recent first)
        hist = supabase.table('task_history').select('*').eq('task_id', task_id).eq('user_id', user_id).order('created_at', desc=True).execute()
        history = hist.data or []

        # Render a small HTML snippet
        html = render_template('partials/history_list.html', task=task, history=history)
        return html
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if not username or not email or not password:
            flash('All fields are required!')
            return render_template('register.html')
        
        try:
            # Check if user already exists (username or email)
            existing_user = None
            try:
                by_username = supabase.table('users').select('id').eq('username', username).execute()
                if by_username.data:
                    existing_user = by_username
                else:
                    by_email = supabase.table('users').select('id').eq('email', email).execute()
                    if by_email.data:
                        existing_user = by_email
            except Exception:
                existing_user = None

            if existing_user and existing_user.data:
                flash('Username or email already exists!')
                return render_template('register.html')
            
            # Create new user
            password_hash = generate_password_hash(password)
            result = supabase.table('users').insert({
                'username': username,
                'email': email,
                'password_hash': password_hash
            }).execute()
            
            if result.data:
                user_id = result.data[0]['id']
                session['user_id'] = user_id
                session['username'] = username
                
                flash('Registration successful!')
                return redirect(url_for('questionnaire'))
            else:
                flash('Registration failed. Please try again.')
                
        except Exception as e:
            flash(f'Registration error: {str(e)}')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        try:
            result = supabase.table('users').select('*').eq('username', username).execute()
            
            if result.data and check_password_hash(result.data[0]['password_hash'], password):
                user = result.data[0]
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password!')
                
        except Exception as e:
            flash(f'Login error: {str(e)}')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/catalog', methods=['GET', 'POST'])
def catalog_admin():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename == '':
            flash('Please choose a CSV file.')
            return redirect(url_for('catalog_admin'))
        try:
            # Basic check: ensure it looks like CSV with EXPECTED_COLUMNS subset
            headers, rows = _read_csv_upload(file)
            missing = [c for c in ('task_key','title','feature_requirements') if c not in (headers or [])]
            if missing:
                flash(f'CSV is missing required columns: {", ".join(missing)}')
                return redirect(url_for('catalog_admin'))
            # Save to static/tasks_catalog.csv
            target = os.path.join(app.root_path, 'static', 'tasks_catalog.csv')
            with open(target, 'w', encoding='utf-8') as out:
                writer = csv.DictWriter(out, fieldnames=headers)
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
            flash(f'Catalog updated: {len(rows)} rows written.')
            return redirect(url_for('catalog_admin'))
        except Exception as e:
            flash(f'Failed to update catalog: {e}')
            return redirect(url_for('catalog_admin'))
    # GET
    return render_template('catalog.html')

@app.route('/tasks/regenerate', methods=['POST'])
def regenerate_tasks():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        fres = supabase.table('home_features').select('*').eq('user_id', user_id).execute()
        if not fres.data:
            flash('No home features found. Complete the questionnaire first.')
            return redirect(url_for('dashboard'))
        features_row = fres.data[0]
        feature_flags = {k: bool(features_row.get(k, False)) for k in ALLOWED_FEATURE_KEYS}
        generate_tasks_for_user(user_id, feature_flags)
        flash('Tasks regenerated from current catalog and features.')
    except Exception as e:
        flash(f'Failed to regenerate tasks: {e}')
    return redirect(url_for('dashboard'))
@app.route('/questionnaire', methods=['GET', 'POST'])
def questionnaire():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        user_id = session['user_id']
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Helper to interpret checkbox/radio values uniformly
        def _is_checked(name, default=False):
            v = request.form.get(name)
            if v is None:
                return default
            s = str(v).strip().lower()
            return s in ('on', 'true', '1', 'yes', 'y')

        # Helper to normalize season values into ISO date strings for DB date columns
        # Accepts values like '03' (month), 'march' (name), or an ISO date already
        def _normalize_season_value(val):
            if val is None:
                return None
            s = str(val).strip()
            if not s:
                return None
            # If already a full ISO date, return a safe isoformat
            try:
                # Handle cases like '2024-03-01' or '2024-03-01T00:00:00'
                d = datetime.fromisoformat(s.replace('Z', '+00:00'))
                return d.date().isoformat()
            except Exception:
                pass
            # Two-digit month like '03' or '10'
            if len(s) == 2 and s.isdigit():
                return f"2000-{s}-01"
            # Month names
            month_map = {
                'january': '01', 'february': '02', 'march': '03', 'april': '04',
                'may': '05', 'june': '06', 'july': '07', 'august': '08',
                'september': '09', 'october': '10', 'november': '11', 'december': '12',
            }
            key = s.lower()
            if key in month_map:
                return f"2000-{month_map[key]}-01"
            # As a last resort, leave null rather than storing invalid
            return None

        # Map new wizard inputs (including radios) to existing boolean feature flags
        fireplace_type = (request.form.get('fireplace_type') or 'none').strip().lower()
        garage_type = (request.form.get('garage_type') or 'none').strip().lower()

        features = {
            'has_hvac': _is_checked('has_hvac'),
            'has_gutters': _is_checked('has_gutters'),  # supports radio yes/no
            'has_dishwasher': _is_checked('has_dishwasher'),
            'has_smoke_detectors': _is_checked('has_smoke_detectors'),
            'has_water_heater': _is_checked('has_water_heater'),
            'has_water_softener': _is_checked('has_water_softener'),
            'has_garbage_disposal': _is_checked('has_garbage_disposal'),
            'has_washer_dryer': _is_checked('has_washer_dryer'),
            'has_sump_pump': _is_checked('has_sump_pump'),  # supports radio yes/no
            'has_well': _is_checked('has_well'),
            # Fireplace true if wood/gas selected or legacy checkbox provided
            'has_fireplace': (fireplace_type in ('wood', 'gas')) or _is_checked('has_fireplace'),
            'has_septic': _is_checked('has_septic'),
            # Garage true if attached/detached selected or legacy checkbox provided
            'has_garage': (garage_type in ('attached', 'detached')) or _is_checked('has_garage'),
        }

        # Extended fields to persist
        extended = {
            # Step 1: basics
            'home_type': (request.form.get('home_type') or '').strip() or None,
            'year_built': (request.form.get('year_built') or '').strip() or None,
            'home_size': (request.form.get('home_size') or '').strip() or None,
            'has_yard': _is_checked('has_yard'),
            'carpet': (request.form.get('carpet') or '').strip() or None,
            # Step 2: systems
            'has_window_units': _is_checked('has_window_units'),
            'has_radiator_boiler': _is_checked('has_radiator_boiler'),
            'no_central_hvac': _is_checked('no_central_hvac'),
            'fireplace_type': fireplace_type or None,
            # Step 3: appliances
            'has_refrigerator_ice': _is_checked('has_refrigerator_ice'),
            'has_range_hood': _is_checked('has_range_hood'),
            # Step 4: exterior
            'garage_type': garage_type or None,
            'has_deck_patio': _is_checked('has_deck_patio'),
            'has_pool_hot_tub': _is_checked('has_pool_hot_tub'),
            # Step 5: seasons & climate
            'freezes': _is_checked('freezes'),
            'season_spring': (request.form.get('season_spring') or None),
            'season_summer': (request.form.get('season_summer') or None),
            'season_autumn': (request.form.get('season_autumn') or None),
            'season_winter': (request.form.get('season_winter') or None),
            # Step 6: lifestyle
            'has_pets': _is_checked('has_pets'),
            'pet_dog': _is_checked('pet_dog'),
            'pet_cat': _is_checked('pet_cat'),
            'pet_other': _is_checked('pet_other'),
            'travel_often': _is_checked('travel_often'),
        }

        # Normalize season fields to full ISO dates if the DB columns are of type DATE
        for k in ('season_spring', 'season_summer', 'season_autumn', 'season_winter'):
            extended[k] = _normalize_season_value(extended.get(k))
        
        try:
            # Check if features already exist for this user
            existing_full = supabase.table('home_features').select('*').eq('user_id', user_id).execute()

            # Build a combined dict of inputs
            combined_input = {**features, **extended}

            if existing_full.data:
                # Filter to only columns that exist on this row to avoid schema errors (e.g., no 'carpet' col)
                row = existing_full.data[0]
                allowed_keys = set(row.keys())
                safe_payload = {k: v for k, v in combined_input.items() if k in allowed_keys}
                # Always keep user_id filter/update
                safe_payload['user_id'] = user_id

                supabase.table('home_features').update(safe_payload).eq('user_id', user_id).execute()
            else:
                # Safe allowed columns for insert: all boolean feature flags + known text/date columns
                SAFE_TEXT_COLS = {
                    'home_type', 'year_built', 'home_size', 'fireplace_type', 'garage_type',
                    'season_spring', 'season_summer', 'season_autumn', 'season_winter'
                }
                insert_allowed = set(ALLOWED_FEATURE_KEYS) | SAFE_TEXT_COLS
                safe_payload = {k: v for k, v in combined_input.items() if k in insert_allowed}
                safe_payload['user_id'] = user_id

                supabase.table('home_features').insert(safe_payload).execute()
            
            # Generate tasks based on features (include extended boolean flags)
            combined_features = dict(features)
            for k in ALLOWED_FEATURE_KEYS:
                if k in combined_features:
                    continue
                v = extended.get(k)
                if isinstance(v, bool):
                    combined_features[k] = v
            generate_tasks_for_user(user_id, combined_features)
            
            if is_ajax:
                return jsonify({'ok': True, 'redirect': url_for('dashboard')}), 200
            flash('Home features saved and tasks generated!')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            if is_ajax:
                return jsonify({'ok': False, 'error': str(e)}), 400
            flash(f'Error saving features: {str(e)}')
    
    # GET: prefill
    user_id = session['user_id']
    prefill = {}
    try:
        res = supabase.table('home_features').select('*').eq('user_id', user_id).execute()
        if res.data:
            prefill = res.data[0]
    except Exception as e:
        print(f"Error loading home_features for prefill: {e}")
    return render_template('questionnaire.html', prefill=prefill)

def generate_tasks_for_user(user_id, features):
    try:
        # Primary: seed from static catalog if present, else fallback to templates
        seeded = seed_tasks_from_static_catalog_or_templates(user_id, features)
        if not seeded:
            print('No tasks seeded (catalog and templates both failed).')
    except Exception as e:
        print(f"Error generating tasks: {e}")

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    try:
        # Reactivate tasks that are now due
        reactivate_due_tasks(user_id)
        
        # Get all active tasks (not marked as completed in current cycle)
        tasks_result = supabase.table('tasks').select('*').eq('user_id', user_id).eq('is_completed', False).eq('archived', False).order('next_due_date').execute()
        tasks = tasks_result.data or []
        # Load baseline flags and feature booleans for conditional questions
        features_row = {}
        baseline_features = {}
        # If user just completed/dismissed baseline in this session, hide CTA immediately
        baseline_done_session = bool(session.pop('baseline_done', False))
        try:
            # Select only guaranteed columns to avoid exceptions that would hide saved flags
            fres = (supabase
                    .table('home_features')
                    .select('baseline_checkup_dismissed,baseline_last_checked')
                    .eq('user_id', user_id)
                    .execute())
            if fres.data:
                features_row = fres.data[0]
            # Optional: try to load feature booleans, but ignore errors if columns don't exist yet
            try:
                f2 = (supabase
                      .table('home_features')
                      .select('has_gutters,has_hvac,has_sump_pump,has_dishwasher,has_washer_dryer,has_fireplace,has_carpets')
                      .eq('user_id', user_id)
                      .execute())
                if f2.data:
                    r2 = f2.data[0]
                    baseline_features = {
                        'has_gutters': bool(r2.get('has_gutters', False)),
                        'has_hvac': bool(r2.get('has_hvac', False)),
                        'has_sump_pump': bool(r2.get('has_sump_pump', False)),
                        'has_dishwasher': bool(r2.get('has_dishwasher', False)),
                        'has_washer_dryer': bool(r2.get('has_washer_dryer', False)),
                        'has_fireplace': bool(r2.get('has_fireplace', False)),
                        'has_carpets': bool(r2.get('has_carpets', True)),
                    }
            except Exception:
                pass
        except Exception:
            features_row = {}
            baseline_features = {}
        
        # Get recently completed tasks
        completed_result = supabase.table('tasks').select('*').eq('user_id', user_id).eq('is_completed', True).eq('archived', False).order('last_completed', desc=True).limit(10).execute()
        completed_tasks = completed_result.data or []

        # Optional search filter from querystring
        q = (request.args.get('q') or '').strip()
        if q:
            q_lower = q.lower()
            def _match(t):
                title = (t.get('title') or '').lower()
                desc = (t.get('description') or '').lower()
                return (q_lower in title) or (q_lower in desc)
            tasks = [t for t in tasks if _match(t)]
            completed_tasks = [t for t in completed_tasks if _match(t)]
        
        # Categorize tasks
        overdue = []
        upcoming = []  # Due within next 30 days
        future = []    # Due beyond 30 days
        today = datetime.now().date()
        next_month = today + timedelta(days=30)
        
        for task in tasks:
            task_date = datetime.fromisoformat(task['next_due_date']).date()
            if task_date < today:
                overdue.append(task)
            elif task_date <= next_month:
                upcoming.append(task)
            else:
                future.append(task)
        # Overview metrics
        next_week = today + timedelta(days=7)
        upcoming_7 = [t for t in tasks if datetime.fromisoformat(t['next_due_date']).date() <= next_week and datetime.fromisoformat(t['next_due_date']).date() >= today]
        # Completed in last 7 days
        completed_last_7 = 0
        for t in completed_tasks:
            try:
                if t.get('last_completed'):
                    lc = datetime.fromisoformat(t['last_completed']).date()
                    if (today - lc).days <= 7:
                        completed_last_7 += 1
            except Exception:
                pass

        overview = {
            'total_active': len(tasks),
            'overdue_count': len(overdue),
            'due_7_days': len(upcoming_7),
            'completed_7_days': completed_last_7,
        }

        # Urgent task: show only when there are overdue tasks
        urgent_task = None
        urgent_task_overdue = False
        try:
            if overdue:
                urgent_task = sorted(overdue, key=lambda t: datetime.fromisoformat(t['next_due_date']))[0]
                urgent_task_overdue = True
        except Exception:
            urgent_task = overdue[0] if overdue else None
            urgent_task_overdue = bool(overdue)

        # Derive a robust baseline_done flag
        baseline_dismissed_flag = bool(features_row.get('baseline_checkup_dismissed'))
        baseline_last_checked_flag = bool(features_row.get('baseline_last_checked'))
        baseline_done = baseline_done_session or baseline_dismissed_flag or baseline_last_checked_flag

        return render_template('dashboard.html', 
                             overview=overview,
                             urgent_task=urgent_task,
                             urgent_task_overdue=urgent_task_overdue,
                             overdue_tasks=overdue, 
                             upcoming_tasks=upcoming,
                             future_tasks=future,
                             completed_tasks=completed_tasks,
                             baseline_done=baseline_done,
                             baseline_dismissed=baseline_dismissed_flag,
                             baseline_last_checked=features_row.get('baseline_last_checked'),
                             baseline_features=baseline_features)
                             
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}')
        return render_template('dashboard.html', 
                             overdue_tasks=[], 
                             upcoming_tasks=[],
                             future_tasks=[],
                             completed_tasks=[],
                             baseline_dismissed=True,
                             baseline_last_checked=None)

@app.route('/calendar')
def calendar_view():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    # Determine target month
    try:
        year = int(request.args.get('year') or datetime.now().year)
        month = int(request.args.get('month') or datetime.now().month)
        first_of_month = datetime(year, month, 1).date()
    except Exception:
        first_of_month = datetime.now().date().replace(day=1)
        year = first_of_month.year
        month = first_of_month.month

    # Compute start (Sunday) to end (Saturday) range covering the month grid
    start_weekday = first_of_month.weekday()  # Monday=0..Sunday=6
    # We want Sunday as first column: compute days back to Sunday
    days_back_to_sunday = (start_weekday + 1) % 7
    grid_start = first_of_month - timedelta(days=days_back_to_sunday)
    # End of month
    if month == 12:
        first_next_month = datetime(year + 1, 1, 1).date()
    else:
        first_next_month = datetime(year, month + 1, 1).date()
    last_of_month = first_next_month - timedelta(days=1)
    end_weekday = last_of_month.weekday()
    days_forward_to_saturday = (6 - end_weekday)
    grid_end = last_of_month + timedelta(days=days_forward_to_saturday)

    # Fetch active tasks due within grid window
    try:
        tasks_result = (supabase
                        .table('tasks')
                        .select('*')
                        .eq('user_id', user_id)
                        .eq('is_completed', False)
                        .eq('archived', False)
                        .gte('next_due_date', grid_start.isoformat())
                        .lte('next_due_date', grid_end.isoformat())
                        .order('next_due_date')
                        .execute())
        tasks = tasks_result.data or []
    except Exception:
        tasks = []

    # Group tasks by next_due_date
    by_date = {}
    for t in tasks:
        try:
            d = datetime.fromisoformat(t['next_due_date']).date()
            by_date.setdefault(d.isoformat(), []).append(t)
        except Exception:
            continue

    # Build days list for grid
    days = []
    cur = grid_start
    today = datetime.now().date()
    while cur <= grid_end:
        days.append({
            'date': cur,
            'in_month': (cur.month == month),
            'items': by_date.get(cur.isoformat(), []),
            'is_today': (cur == today),
            'is_past': (cur < today),
        })
        cur += timedelta(days=1)

    # Prev/next month params
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    next_year = year if month < 12 else year + 1
    next_month = month + 1 if month < 12 else 1

    return render_template('calendar.html', 
                           year=year,
                           month=month,
                           days=days,
                           prev_year=prev_year,
                           prev_month=prev_month,
                           next_year=next_year,
                           next_month=next_month,
                           today_year=today.year,
                           today_month=today.month)

# --- Baseline Checkup Endpoints ---
@app.route('/baseline/dismiss', methods=['POST'])
def baseline_dismiss():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        # Update if exists, else insert (avoid ON CONFLICT constraint requirement)
        existing = supabase.table('home_features').select('user_id').eq('user_id', user_id).execute()
        payload = {
            'baseline_checkup_dismissed': True,
            'baseline_last_checked': datetime.utcnow().isoformat()+'Z'
        }
        if existing.data:
            supabase.table('home_features').update(payload).eq('user_id', user_id).execute()
        else:
            payload['user_id'] = user_id
            supabase.table('home_features').insert(payload).execute()
        # Hide CTA immediately on next dashboard render
        session['baseline_done'] = True
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _adjust_tasks_from_baseline(user_id, answers):
    """Apply simple adjustments: bring forward problem areas, defer pristine ones.
    Prefer task_key-based matching when available, otherwise title substring matching.
    """
    today = datetime.utcnow().date()
    try:
        # Fetch tasks once
        res = supabase.table('tasks').select('id,task_key,title,next_due_date,priority').eq('user_id', user_id).eq('archived', False).execute()
        rows = res.data or []

        def _title_matches(title, substrings):
            t = (title or '').lower()
            return any(s in t for s in substrings)

        def _targets(task, key_list=None, substrings=None):
            if key_list:
                tk = (task.get('task_key') or '').strip()
                if tk and tk in key_list:
                    return True
            if substrings:
                return _title_matches(task.get('title'), substrings)
            return False

        updates = []
        # --- Step 1: Exterior ---
        if answers.get('siding_condition') == 'needs_repair':
            for t in rows:
                if _targets(t, key_list={'inspect_siding','exterior_painting','trim_siding_touchup'}, substrings=['siding','exterior paint','paint']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=7)).isoformat(), 'priority': 'high'}))
        glc = answers.get('gutters_last_cleaned')
        if glc in ('over_12m','not_sure'):
            for t in rows:
                if _targets(t, key_list={'gutters_clean','fall_gutter_check','check_gutters_drains'}, substrings=['gutter','downspout']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=7)).isoformat(), 'priority': 'high'}))

        # --- Step 2: Systems ---
        hvac = answers.get('hvac_filter_last')
        if hvac in ('over_6m','not_sure'):
            for t in rows:
                if _targets(t, key_list={'hvac_filter','check_hvac_filters'}, substrings=['hvac filter','replace hvac filter','check hvac filters']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=7)).isoformat(), 'priority': 'medium'}))
        wh = answers.get('water_heater_service')
        if wh in ('over_3y','not_sure'):
            for t in rows:
                if _targets(t, key_list={'water_heater_flush','water_heater_pressure_valve'}, substrings=['water heater','flush hot water heater']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=10)).isoformat(), 'priority': 'medium'}))
        sump = answers.get('sump_pump_tested')
        if sump in ('not_recently','not_sure'):
            for t in rows:
                if _targets(t, key_list={'check_sump_pump_spring','winter_sump_pump_check'}, substrings=['sump pump']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=14)).isoformat(), 'priority': 'medium'}))

        # --- Step 3: Appliances ---
        dw = answers.get('dishwasher_filter_last')
        if dw in ('over_6m','not_sure'):
            for t in rows:
                if _targets(t, key_list={'dishwasher_filter'}, substrings=['dishwasher filter']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=10)).isoformat()}))
        dryer = answers.get('dryer_vent_last')
        if dryer in ('over_1y','not_sure'):
            for t in rows:
                if _targets(t, key_list={'clean_dryer_vents'}, substrings=['dryer vent']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=10)).isoformat(), 'priority': 'medium'}))

        # --- Step 4: Interior ---
        carpet = answers.get('carpet_age')
        if carpet == 'lt_1':
            for t in rows:
                if _targets(t, key_list={'clean_carpets','carpet_clean_pro','replace_carpet'}, substrings=['carpet']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=365)).isoformat()}))
        elif carpet == 'gt_5':
            for t in rows:
                if _targets(t, key_list={'clean_carpets','carpet_clean_pro'}, substrings=['carpet']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=21)).isoformat()}))
        fp = answers.get('fireplace_inspection')
        if fp in ('not_past_year','not_sure'):
            for t in rows:
                if _targets(t, key_list={'chimney_fireplace_check','inspect_roof_pro','reseal_chimney_masonry'}, substrings=['chimney','fireplace']):
                    updates.append((t['id'], {'next_due_date': (today + timedelta(days=21)).isoformat(), 'priority': 'medium'}))

        for tid, payload in updates:
            try:
                supabase.table('tasks').update(payload).eq('user_id', user_id).eq('id', tid).execute()
            except Exception:
                continue
    except Exception as e:
        print(f"Baseline adjust error: {e}")

@app.route('/baseline/apply', methods=['POST'])
def baseline_apply():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        answers = {
            # Step 1
            'siding_condition': (request.form.get('siding_condition') or '').strip(),
            'gutters_last_cleaned': (request.form.get('gutters_last_cleaned') or '').strip(),
            # Step 2
            'hvac_filter_last': (request.form.get('hvac_filter_last') or '').strip(),
            'water_heater_service': (request.form.get('water_heater_service') or '').strip(),
            'sump_pump_tested': (request.form.get('sump_pump_tested') or '').strip(),
            # Step 3
            'dishwasher_filter_last': (request.form.get('dishwasher_filter_last') or '').strip(),
            'dryer_vent_last': (request.form.get('dryer_vent_last') or '').strip(),
            # Step 4
            'carpet_age': (request.form.get('carpet_age') or '').strip(),
            'fireplace_inspection': (request.form.get('fireplace_inspection') or '').strip(),
        }
        # Enhance adjustments per new answers
        _adjust_tasks_from_baseline(user_id, answers)
        # Update if exists, else insert (avoid ON CONFLICT constraint requirement)
        existing = supabase.table('home_features').select('user_id').eq('user_id', user_id).execute()
        payload = {
            'baseline_checkup_dismissed': True,
            'baseline_last_checked': datetime.utcnow().isoformat()+'Z'
        }
        if existing.data:
            supabase.table('home_features').update(payload).eq('user_id', user_id).execute()
        else:
            payload['user_id'] = user_id
            supabase.table('home_features').insert(payload).execute()
        # Hide CTA immediately on next dashboard render
        session['baseline_done'] = True
        flash('Baseline checkup applied to your tasks!')
        return redirect(url_for('dashboard'))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/tasks')
def task_list():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    q = (request.args.get('q') or '').strip().lower()
    sort = (request.args.get('sort') or 'due').strip().lower()
    status = (request.args.get('status') or 'all').strip().lower()  # all | active | completed | archived
    due_filter = (request.args.get('due') or '').strip().lower()    # '' | overdue | upcoming30 | future
    date_filter = (request.args.get('date') or '').strip()          # YYYY-MM-DD
    show_archived = (str(request.args.get('show_archived') or 'false').lower() in ('1','true','yes','y'))
    try:
        # Fetch tasks; include archived if requested
        qb = (supabase
              .table('tasks')
              .select('*')
              .eq('user_id', user_id))
        # Always fetch archived too so we can filter locally for counts; we'll filter display below
        res = qb.execute()
        tasks = res.data or []
        # Compute counts for visibility
        active_tasks = [t for t in tasks if not t.get('archived') and not t.get('is_completed')]
        completed_tasks = [t for t in tasks if not t.get('archived') and t.get('is_completed')]
        archived_tasks = [t for t in tasks if t.get('archived')]
        counts = {
            'active': len(active_tasks),
            'completed': len(completed_tasks),
            'archived': len(archived_tasks),
            'total': len(tasks)
        }
        # Apply status filter for display
        if status == 'active':
            tasks = active_tasks
        elif status == 'completed':
            tasks = completed_tasks
        elif status == 'archived':
            tasks = archived_tasks
        else:  # all (default): show active + completed, optionally include archived if checkbox set
            tasks = active_tasks + completed_tasks
            if show_archived:
                tasks += archived_tasks
        if q:
            def _match(t):
                return q in (t.get('title','').lower()) or q in (t.get('description','').lower())
            tasks = [t for t in tasks if _match(t)]
        # Apply optional exact date filter first (restricts to a single day)
        if date_filter:
            try:
                target = datetime.fromisoformat(date_filter).date()
                def _is_on_date(t):
                    try:
                        d = t.get('next_due_date')
                        if not d:
                            return False
                        dd = datetime.fromisoformat(d).date()
                        return dd == target
                    except Exception:
                        return False
                tasks = [t for t in tasks if _is_on_date(t)]
            except Exception:
                # Ignore invalid date
                pass

        # Apply optional due window filter
        if due_filter in ('overdue', 'upcoming30', 'future'):
            from datetime import date as _date
            today = _date.today()
            horizon = today + timedelta(days=30)
            def _in_overdue(t):
                try:
                    d = t.get('next_due_date')
                    if not d:
                        return False
                    dd = datetime.fromisoformat(d).date()
                    return dd < today
                except Exception:
                    return False
            def _in_upcoming_30(t):
                try:
                    d = t.get('next_due_date')
                    if not d:
                        return False
                    dd = datetime.fromisoformat(d).date()
                    return dd >= today and dd <= horizon
                except Exception:
                    return False
            def _in_future(t):
                try:
                    d = t.get('next_due_date')
                    if not d:
                        return False
                    dd = datetime.fromisoformat(d).date()
                    return dd > horizon
                except Exception:
                    return False
            if due_filter == 'overdue':
                tasks = [t for t in tasks if _in_overdue(t)]
            elif due_filter == 'upcoming30':
                tasks = [t for t in tasks if _in_upcoming_30(t)]
            else:
                tasks = [t for t in tasks if _in_future(t)]

        # Apply sort
        if sort == 'title':
            tasks.sort(key=lambda t: (t.get('title') or '').lower())
        elif sort == 'priority':
            order = {'high': 0, 'medium': 1, 'low': 2}
            tasks.sort(key=lambda t: (order.get((t.get('priority') or '').lower(), 99), (t.get('title') or '').lower()))
        else:  # due
            from datetime import date as _date
            far = _date.max
            def _due(t):
                d = t.get('next_due_date')
                try:
                    return datetime.fromisoformat(d).date() if d else far
                except Exception:
                    return far
            tasks.sort(key=lambda t: (_due(t), (t.get('title') or '').lower()))

        # Annotate tasks with a display_state for accent styling on the All Tasks page
        try:
            from datetime import date as _date
            today = _date.today()
            horizon = today + timedelta(days=30)
            for t in tasks:
                if t.get('archived'):
                    t['display_state'] = ''
                    continue
                if t.get('is_completed'):
                    t['display_state'] = 'completed'
                    continue
                d = t.get('next_due_date')
                try:
                    dd = datetime.fromisoformat(d).date() if d else None
                except Exception:
                    dd = None
                if dd is None:
                    t['display_state'] = 'future'
                elif dd < today:
                    t['display_state'] = 'overdue'
                elif today <= dd <= horizon:
                    t['display_state'] = 'upcoming'
                else:
                    t['display_state'] = 'future'
        except Exception:
            # Non-fatal: accents just won't render if this fails
            pass
    except Exception as e:
        flash(f'Error loading tasks: {str(e)}')
        tasks = []
    
    return render_template('tasks.html', tasks=tasks, sort=sort, show_archived=show_archived, status=status, counts=counts)

@app.route('/task/<int:task_id>')
def task_detail(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        # Load the task, allow viewing even if archived (owner-only)
        tres = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        if not tres.data:
            flash('Task not found')
            return redirect(url_for('task_list'))
        task = tres.data[0]
        # Load history (newest first)
        hres = supabase.table('task_history').select('*').eq('task_id', task_id).eq('user_id', user_id).order('created_at', desc=True).execute()
        history = hres.data or []
        return render_template('task_detail.html', task=task, history=history)
    except Exception as e:
        flash(f'Error loading task: {str(e)}')
        return redirect(url_for('task_list'))

@app.route('/restore_task/<int:task_id>', methods=['POST'])
def restore_task(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        # Ensure the task belongs to the user and is archived
        res = supabase.table('tasks').select('id,archived').eq('id', task_id).eq('user_id', user_id).execute()
        if not res.data:
            return jsonify({'error': 'Task not found'}), 404
        supabase.table('tasks').update({'archived': False}).eq('id', task_id).eq('user_id', user_id).execute()
        return jsonify({'message': 'Task restored'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/complete_task/<int:task_id>')
def complete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    try:
        # Get task details
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).eq('archived', False).execute()
        
        if task_result.data:
            task = task_result.data[0]
            today = datetime.now().date()
            next_due = today + timedelta(days=task['frequency_days'])
            
            # Update the existing task: mark as completed, set completion date, and update next due date
            supabase.table('tasks').update({
                'is_completed': True,
                'last_completed': today.isoformat(),
                'next_due_date': next_due.isoformat()
            }).eq('id', task_id).execute()
            
            flash(f'Task "{task["title"]}" completed! Next due: {next_due}')
        else:
            flash('Task not found!')
            
    except Exception as e:
        flash(f'Error completing task: {str(e)}')
    
    return redirect(url_for('dashboard'))

@app.route('/reset_task/<int:task_id>')
def reset_task(task_id):
    """Reset a completed task back to active status"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    try:
        # Get task details
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        
        if task_result.data:
            task = task_result.data[0]
            
            # Reset the task to active status
            supabase.table('tasks').update({
                'is_completed': False,
                'last_completed': None
            }).eq('id', task_id).execute()
            
            flash(f'Task "{task["title"]}" has been reset to active status')
        else:
            flash('Task not found!')
            
    except Exception as e:
        flash(f'Error resetting task: {str(e)}')
    
    return redirect(url_for('dashboard'))

@app.route('/create_task', methods=['POST'])
def create_task():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    title = request.form['title']
    description = request.form.get('description', '')
    frequency_days = request.form['frequency_days']
    next_due_date_raw = request.form.get('next_due_date')
    priority_raw = (request.form.get('priority') or '').strip().lower()
    category = (request.form.get('category') or '').strip() or None
    
    if not title or not frequency_days:
        flash('Title and frequency are required!')
        return redirect(url_for('dashboard'))
    
    try:
        frequency_days = int(frequency_days)
        if frequency_days <= 0:
            flash('Frequency must be a positive number!')
            return redirect(url_for('dashboard'))
    except ValueError:
        flash('Frequency must be a valid number!')
        return redirect(url_for('dashboard'))

    # Validate/normalize optional fields
    next_due_date = None
    if next_due_date_raw is not None:
        try:
            # Expecting YYYY-MM-DD from <input type="date">; allow empty to clear skip update
            if next_due_date_raw.strip():
                d = date.fromisoformat(next_due_date_raw.strip())
                next_due_date = d.isoformat()
        except Exception:
            flash('Due date must be a valid date (YYYY-MM-DD).')
            return redirect(url_for('dashboard'))

    priority = None
    if priority_raw:
        if priority_raw in PRIORITY_VALUES:
            priority = priority_raw
        else:
            flash(f"Priority must be one of {sorted(PRIORITY_VALUES)}")
            return redirect(url_for('dashboard'))
    
    try:
        # Determine next due date: prefer user-provided, else compute from frequency
        next_due_iso = next_due_date or (datetime.now() + timedelta(days=frequency_days)).date().isoformat()
        # Insert new task
        payload = {
            'user_id': user_id,
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'next_due_date': next_due_iso,
            'is_completed': False,
        }
        if priority is not None:
            payload['priority'] = priority
        if category is not None:
            payload['category'] = category
        supabase.table('tasks').insert(payload).execute()
        
        flash(f'Task "{title}" created successfully!')
        
    except Exception as e:
        flash(f'Error creating task: {str(e)}')
    
    return redirect(url_for('dashboard'))

@app.route('/get_task/<int:task_id>')
def get_task(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    
    try:
        result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        
        if result.data:
            return jsonify({'task': result.data[0]})
        else:
            return jsonify({'error': 'Task not found'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Tasks Catalog CSV Validation & Import ---
@app.route('/api/tasks_catalog/validate', methods=['POST'])
@token_required
def api_validate_tasks_catalog(current_user_id):
    try:
        file = request.files.get('file')
        if not file:
            return jsonify({'error': 'CSV file is required (form field "file")'}), 400

        headers, rows = _read_csv_upload(file)
        missing = [c for c in EXPECTED_COLUMNS if c not in (headers or [])]
        unknown_cols = [c for c in (headers or []) if c not in EXPECTED_COLUMNS]

        # Row-level validation
        issues = []
        seen_keys = set()
        for idx, row in enumerate(rows, start=2):  # header is line 1
            row_issues = _validate_catalog_row(row)
            tk = (row.get('task_key') or '').strip()
            if tk:
                if tk in seen_keys:
                    row_issues.append('duplicate task_key in file')
                else:
                    seen_keys.add(tk)
            if row_issues:
                issues.append({'row': idx, 'task_key': tk, 'title': (row.get('title') or '').strip(), 'issues': row_issues})

        return jsonify({
            'headers_ok': len(missing) == 0,
            'missing_columns': missing,
            'unknown_columns': unknown_cols,
            'row_count': len(rows),
            'issue_count': len(issues),
            'row_issues': issues
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks_catalog/import', methods=['POST'])
@token_required
def api_import_tasks_catalog(current_user_id):
    try:
        file = request.files.get('file')
        replace = (request.form.get('replace', 'true').lower() in ('true', '1', 'yes', 'y'))
        dry_run = (request.form.get('dry_run', 'false').lower() in ('true', '1', 'yes', 'y'))
        if not file:
            return jsonify({'error': 'CSV file is required (form field "file")'}), 400

        headers, rows = _read_csv_upload(file)
        missing = [c for c in EXPECTED_COLUMNS if c not in (headers or [])]
        issues = []
        seen_keys = set()
        for idx, row in enumerate(rows, start=2):
            row_issues = _validate_catalog_row(row)
            tk = (row.get('task_key') or '').strip()
            if tk:
                if tk in seen_keys:
                    row_issues.append('duplicate task_key in file')
                else:
                    seen_keys.add(tk)
            if row_issues:
                issues.append({'row': idx, 'task_key': tk, 'title': (row.get('title') or '').strip(), 'issues': row_issues})

        # Load user features for filtering
        features_res = supabase.table('home_features').select('*').eq('user_id', current_user_id).execute()
        base_features = {k: False for k in ALLOWED_FEATURE_KEYS}
        if features_res.data:
            dbf = features_res.data[0]
            for k in ALLOWED_FEATURE_KEYS:
                base_features[k] = bool(dbf.get(k, False))

        filtered = _filter_rows_by_features(rows, base_features)
        resolved = _resolve_overlaps(filtered)

        preview = []
        for r in resolved[:10]:
            preview.append({
                'task_key': (r.get('task_key') or '').strip(),
                'title': (r.get('title') or '').strip(),
                'next_due_date': _compute_next_due_date(r).isoformat()
            })

        report = {
            'headers_ok': len(missing) == 0,
            'missing_columns': missing,
            'row_count': len(rows),
            'issue_count': len(issues),
            'row_issues': issues,
            'filtered_count': len(filtered),
            'resolved_count': len(resolved),
            'preview_first_10': preview
        }

        if dry_run or missing or issues:
            # Do not import if any issues or dry_run
            status = 200 if dry_run and not missing else 400 if (missing or issues) else 200
            return jsonify(report), status

        # Proceed with import
        if replace:
            supabase.table('tasks').delete().eq('user_id', current_user_id).execute()
        _insert_tasks_for_user(current_user_id, resolved)

        report['imported'] = True
        report['replace'] = replace
        return jsonify(report)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/task_history/<int:task_id>')
@token_required
def api_task_history(current_user_id, task_id):
    """Return task history entries for a task"""
    try:
        # Ensure task belongs to user
        task_result = supabase.table('tasks').select('id').eq('id', task_id).eq('user_id', current_user_id).execute()
        if not task_result.data:
            return jsonify({'error': 'Task not found'}), 404
        hist = supabase.table('task_history').select('*').eq('task_id', task_id).eq('user_id', current_user_id).order('created_at', desc=True).execute()
        return jsonify({'history': hist.data or []})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/snooze_task/<int:task_id>', methods=['POST'])
@token_required
def api_snooze_task(current_user_id, task_id):
    """Postpone a task by N days without marking it completed"""
    try:
        data = request.get_json() or {}
        days = data.get('days')
        try:
            days = int(days)
            if days <= 0:
                return jsonify({'error': 'days must be a positive integer'}), 400
        except Exception:
            return jsonify({'error': 'days must be a positive integer'}), 400

        # Get task
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', current_user_id).execute()
        if not task_result.data:
            return jsonify({'error': 'Task not found'}), 404
        task = task_result.data[0]

        # Compute new next_due_date
        current_next_due = datetime.fromisoformat(task['next_due_date']).date()
        new_next_due = current_next_due + timedelta(days=days)

        supabase.table('tasks').update({
            'next_due_date': new_next_due.isoformat()
        }).eq('id', task_id).execute()

        # Record history
        try:
            supabase.table('task_history').insert({
                'user_id': current_user_id,
                'task_id': task_id,
                'action': 'snoozed',
                'delta_days': days,
                'created_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception as _:
            pass

        return jsonify({'message': f'Task "{task["title"]}" snoozed by {days} days', 'next_due_date': new_next_due.isoformat()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/edit_task/<int:task_id>', methods=['POST'])
def edit_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    title = request.form['title']
    description = request.form.get('description', '')
    frequency_days = request.form['frequency_days']
    # Optional fields
    next_due_date_raw = request.form.get('next_due_date')
    priority_raw = (request.form.get('priority') or '').strip().lower()
    category = (request.form.get('category') or '').strip() or None
    
    if not title or not frequency_days:
        flash('Title and frequency are required!')
        return redirect(url_for('dashboard'))
    
    try:
        frequency_days = int(frequency_days)
        if frequency_days <= 0:
            flash('Frequency must be a positive number!')
            return redirect(url_for('dashboard'))
    except ValueError:
        flash('Frequency must be a valid number!')
        return redirect(url_for('dashboard'))
    
    # Normalize optional fields prior to DB update
    next_due_date = None
    if next_due_date_raw is not None:
        try:
            if next_due_date_raw.strip():
                d = date.fromisoformat(next_due_date_raw.strip())
                next_due_date = d.isoformat()
        except Exception:
            if is_ajax:
                return jsonify({'ok': False, 'error': 'Due date must be a valid date (YYYY-MM-DD).'}), 400
            flash('Due date must be a valid date (YYYY-MM-DD).')
            return redirect(url_for('dashboard'))

    priority = None
    if priority_raw:
        if priority_raw in PRIORITY_VALUES:
            priority = priority_raw
        else:
            if is_ajax:
                return jsonify({'ok': False, 'error': f'Priority must be one of {sorted(PRIORITY_VALUES)}'}), 400
            flash(f"Priority must be one of {sorted(PRIORITY_VALUES)}")
            return redirect(url_for('dashboard'))

    try:
        # Verify task belongs to user
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        
        if not task_result.data:
            flash('Task not found!')
            return redirect(url_for('dashboard'))
        
        # Build update payload, only including keys that exist on the task record
        row = task_result.data[0]
        payload = {}
        if 'title' in row: payload['title'] = title
        if 'description' in row: payload['description'] = description
        if 'frequency_days' in row: payload['frequency_days'] = frequency_days
        if 'category' in row and category is not None:
            payload['category'] = category
        if next_due_date is not None and 'next_due_date' in row:
            payload['next_due_date'] = next_due_date
        # Only include priority if explicitly provided and valid and column exists
        if priority is not None and 'priority' in row:
            payload['priority'] = priority

        # Update task
        db_res = supabase.table('tasks').update(payload).eq('id', task_id).eq('user_id', user_id).eq('archived', False).execute()

        if is_ajax:
            # Include a snapshot of incoming form to debug client/server mismatch
            form_snapshot = {k: v for k, v in request.form.items()}
            return jsonify({
                'ok': True,
                'task_id': task_id,
                'payload': payload,
                'form': form_snapshot,
                'db_result_count': len(db_res.data or []),
                'columns_present': list(row.keys()),
            })

        flash(f'Task "{title}" updated successfully!')
        
    except Exception as e:
        if is_ajax:
            return jsonify({'ok': False, 'error': str(e)}), 500
        flash(f'Error updating task: {str(e)}')
    
    return redirect(url_for('dashboard'))

@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    
    try:
        # Verify task belongs to user
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        
        if not task_result.data:
            return jsonify({'error': 'Task not found'}), 404
        
        # Soft archive task
        supabase.table('tasks').update({'archived': True}).eq('id', task_id).eq('user_id', user_id).execute()
        # Optional: record an entry in history as a neutral action (using 'snoozed' slot)
        try:
            supabase.table('task_history').insert({
                'user_id': user_id,
                'task_id': task_id,
                'action': 'snoozed',
                'delta_days': None,
                'created_at': datetime.utcnow().isoformat()
            }).execute()
        except Exception:
            pass
        return jsonify({'message': 'Task archived'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# API Endpoints for frontend
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not username or not email or not password:
        return jsonify({'error': 'All fields are required'}), 400
    
    try:
        # Check if user already exists
        existing_user = supabase.table('users').select('id').or_(
            f'username.eq.{username},email.eq.{email}'
        ).execute()
        
        if existing_user.data:
            return jsonify({'error': 'Username or email already exists'}), 400
        
        # Create new user
        password_hash = generate_password_hash(password)
        result = supabase.table('users').insert({
            'username': username,
            'email': email,
            'password_hash': password_hash
        }).execute()
        
        if result.data:
            user = result.data[0]
            token = jwt.encode({
                'user_id': user['id'],
                'exp': datetime.utcnow() + timedelta(days=30)
            }, app.secret_key, algorithm='HS256')
            
            return jsonify({
                'token': token,
                'user': {'id': user['id'], 'username': user['username']}
            })
        else:
            return jsonify({'error': 'Registration failed'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    try:
        result = supabase.table('users').select('*').eq('username', username).execute()
        
        if result.data and check_password_hash(result.data[0]['password_hash'], password):
            user = result.data[0]
            token = jwt.encode({
                'user_id': user['id'],
                'exp': datetime.utcnow() + timedelta(days=30)
            }, app.secret_key, algorithm='HS256')
            
            return jsonify({
                'token': token,
                'user': {'id': user['id'], 'username': user['username']}
            })
        else:
            return jsonify({'error': 'Invalid username or password'}), 401
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/dashboard')
@token_required
def api_dashboard(current_user_id):
    try:
        # Reactivate tasks that are now due
        reactivate_due_tasks(current_user_id)

        # Filters
        search = request.args.get('search')
        category = request.args.get('category')
        priority = request.args.get('priority')
        min_freq = request.args.get('min_freq', type=int)
        max_freq = request.args.get('max_freq', type=int)

        # Build query with filters
        query = supabase.table('tasks').select('*').eq('user_id', current_user_id).eq('is_completed', False)
        if category:
            query = query.eq('category', category)
        if priority:
            query = query.eq('priority', priority)
        if min_freq is not None:
            query = query.gte('frequency_days', min_freq)
        if max_freq is not None:
            query = query.lte('frequency_days', max_freq)
        if search:
            # PostgREST ilike uses '*' wildcards, not SQL '%'
            like = f"*{search}*"
            # OR ilike across title and description
            query = query.or_(f"title.ilike.{like},description.ilike.{like}")

        tasks_result = query.order('next_due_date').execute()
        tasks = tasks_result.data or []

        # Get recently completed tasks
        completed_result = supabase.table('tasks').select('*').eq('user_id', current_user_id).eq('is_completed', True).order('last_completed', desc=True).limit(10).execute()
        completed_tasks = completed_result.data or []
        
        # Categorize tasks
        overdue = []
        upcoming = []
        future = []
        today = datetime.now().date()
        next_month = today + timedelta(days=30)
        
        for task in tasks:
            task_date = datetime.fromisoformat(task['next_due_date']).date()
            if task_date < today:
                overdue.append(task)
            elif task_date <= next_month:
                upcoming.append(task)
            else:
                future.append(task)
        
        return jsonify({
            'overdue_tasks': overdue,
            'upcoming_tasks': upcoming,
            'future_tasks': future,
            'completed_tasks': completed_tasks
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/complete_task/<int:task_id>', methods=['POST'])
@token_required
def api_complete_task(current_user_id, task_id):
    try:
        # Get task details
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', current_user_id).execute()
        
        if task_result.data:
            task = task_result.data[0]
            today = datetime.now().date()
            next_due = today + timedelta(days=task['frequency_days'])
            
            # Update the task
            supabase.table('tasks').update({
                'is_completed': True,
                'last_completed': today.isoformat(),
                'next_due_date': next_due.isoformat()
            }).eq('id', task_id).execute()
            
            # Record history
            try:
                supabase.table('task_history').insert({
                    'user_id': current_user_id,
                    'task_id': task_id,
                    'action': 'completed',
                    'delta_days': task['frequency_days'],
                    'created_at': datetime.utcnow().isoformat()
                }).execute()
            except Exception as _:
                pass
            
            return jsonify({'message': f'Task "{task["title"]}" completed! Next due: {next_due}'})
        else:
            return jsonify({'error': 'Task not found'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reset_task/<int:task_id>', methods=['POST'])
@token_required
def api_reset_task(current_user_id, task_id):
    try:
        # Get task details
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', current_user_id).execute()
        
        if task_result.data:
            task = task_result.data[0]
            
            # Reset the task
            supabase.table('tasks').update({
                'is_completed': False,
                'last_completed': None
            }).eq('id', task_id).execute()
            
            return jsonify({'message': f'Task "{task["title"]}" has been reset to active status'})
        else:
            return jsonify({'error': 'Task not found'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/questionnaire', methods=['POST'])
@token_required
def api_questionnaire(current_user_id):
    try:
        data = request.get_json()
        features = {
            'has_hvac': data.get('has_hvac', False),
            'has_gutters': data.get('has_gutters', False),
            'has_dishwasher': data.get('has_dishwasher', False),
            'has_smoke_detectors': data.get('has_smoke_detectors', False),
            'has_water_heater': data.get('has_water_heater', False),
            'has_water_softener': data.get('has_water_softener', False),
            'has_garbage_disposal': data.get('has_garbage_disposal', False),
            'has_washer_dryer': data.get('has_washer_dryer', False),
            'has_sump_pump': data.get('has_sump_pump', False),
            'has_well': data.get('has_well', False),
            'has_fireplace': data.get('has_fireplace', False),
            'has_septic': data.get('has_septic', False),
            'has_garage': data.get('has_garage', False),
        }
        
        # Check if features already exist
        existing = supabase.table('home_features').select('id').eq('user_id', current_user_id).execute()
        
        if existing.data:
            # Update existing features
            supabase.table('home_features').update({
                **features,
                'user_id': current_user_id
            }).eq('user_id', current_user_id).execute()
        else:
            # Insert new features
            supabase.table('home_features').insert({
                'user_id': current_user_id,
                **features
            }).execute()
        
        # Generate tasks based on features
        generate_tasks_for_user(current_user_id, features)
        
        return jsonify({'message': 'Home features saved and tasks generated!'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/home_features')
@token_required
def api_home_features(current_user_id):
    try:
        result = supabase.table('home_features').select('*').eq('user_id', current_user_id).execute()
        
        if result.data:
            features = result.data[0]
            return jsonify({'features': features})
        else:
            return jsonify({'features': None})
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks', methods=['POST'])
@token_required
def api_create_task(current_user_id):
    """Create a new custom task"""
    try:
        data = request.get_json()
        title = data.get('title')
        description = data.get('description', '')
        frequency_days = data.get('frequency_days')
        priority = data.get('priority')  # optional: 'low' | 'medium' | 'high'
        category = data.get('category')  # optional string
        
        if not title or not frequency_days:
            return jsonify({'error': 'Title and frequency are required'}), 400
        
        try:
            frequency_days = int(frequency_days)
            if frequency_days <= 0:
                return jsonify({'error': 'Frequency must be a positive number'}), 400
        except ValueError:
            return jsonify({'error': 'Frequency must be a valid number'}), 400
        
        # Calculate next due date
        next_due = datetime.now() + timedelta(days=frequency_days)
        
        # Insert new task
        result = supabase.table('tasks').insert({
            'user_id': current_user_id,
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'next_due_date': next_due.date().isoformat(),
            'is_completed': False,
            'priority': priority,
            'category': category
        }).execute()
        
        if result.data:
            return jsonify({'message': 'Task created successfully', 'task': result.data[0]})
        else:
            return jsonify({'error': 'Failed to create task'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@token_required
def api_update_task(current_user_id, task_id):
    """Update an existing task"""
    try:
        data = request.get_json()
        title = data.get('title')
        description = data.get('description', '')
        frequency_days = data.get('frequency_days')
        priority = data.get('priority')
        category = data.get('category')
        next_due_date = data.get('next_due_date')  # optional ISO date string YYYY-MM-DD
        
        if not title or not frequency_days:
            return jsonify({'error': 'Title and frequency are required'}), 400
        
        try:
            frequency_days = int(frequency_days)
            if frequency_days <= 0:
                return jsonify({'error': 'Frequency must be a positive number'}), 400
        except ValueError:
            return jsonify({'error': 'Frequency must be a valid number'}), 400
        
        # Verify task belongs to user
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', current_user_id).execute()
        
        if not task_result.data:
            return jsonify({'error': 'Task not found'}), 404
        
        # Validate optional next_due_date if provided
        update_payload = {
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'priority': priority,
            'category': category
        }
        if next_due_date:
            try:
                # Normalize to date ISO format
                nd = datetime.fromisoformat(next_due_date)
                update_payload['next_due_date'] = nd.date().isoformat()
            except ValueError:
                try:
                    nd = datetime.strptime(next_due_date, '%Y-%m-%d')
                    update_payload['next_due_date'] = nd.date().isoformat()
                except ValueError:
                    return jsonify({'error': 'next_due_date must be an ISO date (YYYY-MM-DD)'}), 400

        # Update task
        result = supabase.table('tasks').update(update_payload).eq('id', task_id).eq('user_id', current_user_id).execute()
        
        if result.data:
            return jsonify({'message': 'Task updated successfully', 'task': result.data[0]})
        else:
            return jsonify({'error': 'Failed to update task'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@token_required
def api_delete_task(current_user_id, task_id):
    """Delete a task"""
    try:
        # Verify task belongs to user
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', current_user_id).execute()
        
        if not task_result.data:
            return jsonify({'error': 'Task not found'}), 404
        
        # Delete task
        result = supabase.table('tasks').delete().eq('id', task_id).eq('user_id', current_user_id).execute()
        
        return jsonify({'message': 'Task deleted successfully'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/tasks/<int:task_id>', methods=['GET'])
@token_required
def api_get_task(current_user_id, task_id):
    """Get a specific task for editing"""
    try:
        result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', current_user_id).execute()
        
        if result.data:
            return jsonify({'task': result.data[0]})
        else:
            return jsonify({'error': 'Task not found'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# SPA static file serving (frontend/) with history API fallback
@app.route('/app/')
@app.route('/app/<path:path>')
def spa(path='index.html'):
    root_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend')
    file_path = os.path.join(root_dir, path)
    if os.path.isfile(file_path):
        return send_from_directory(root_dir, path)
    # History API fallback to index.html for client-side routing
    return send_from_directory(root_dir, 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') != 'production')