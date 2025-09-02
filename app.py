from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client
from datetime import datetime, timedelta
import os
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
    ]
}

# --- Catalog import/validation constants & helpers ---
ALLOWED_FEATURE_KEYS = {
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
        value = value.strip()
        if key not in ALLOWED_FEATURE_KEYS:
            errors.append(f"unknown feature key '{key}'")
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
    to_insert = []
    today = datetime.now().date()
    for r in rows:
        title = (r.get('title') or '').strip()
        if not title:
            continue
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

        to_insert.append({
            'user_id': user_id,
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'next_due_date': next_due.isoformat(),
            'is_completed': False,
            'priority': priority,
            'category': category
        })

    if to_insert:
        supabase.table('tasks').insert(to_insert).execute()

def seed_tasks_from_catalog_rows(user_id, features, all_rows):
    """Clear existing tasks and seed from provided catalog rows, filtered & overlap-resolved."""
    # Clear existing tasks
    supabase.table('tasks').delete().eq('user_id', user_id).execute()
    filtered = _filter_rows_by_features(all_rows, features)
    resolved = _resolve_overlaps(filtered)
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
        }).eq('user_id', user_id).eq('is_completed', True).lte('next_due_date', today).execute()
    except Exception as e:
        print(f"Error reactivating tasks: {e}")

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
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
            # Check if user already exists
            existing_user = supabase.table('users').select('id').or_(
                f'username.eq.{username},email.eq.{email}'
            ).execute()
            
            if existing_user.data:
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

@app.route('/questionnaire', methods=['GET', 'POST'])
def questionnaire():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        user_id = session['user_id']
        
        features = {
            'has_hvac': 'has_hvac' in request.form,
            'has_gutters': 'has_gutters' in request.form,
            'has_dishwasher': 'has_dishwasher' in request.form,
            'has_smoke_detectors': 'has_smoke_detectors' in request.form,
            'has_water_heater': 'has_water_heater' in request.form,
            'has_water_softener': 'has_water_softener' in request.form,
            'has_garbage_disposal': 'has_garbage_disposal' in request.form,
            'has_washer_dryer': 'has_washer_dryer' in request.form,
            'has_sump_pump': 'has_sump_pump' in request.form,
            'has_well': 'has_well' in request.form,
            'has_fireplace': 'has_fireplace' in request.form,
            'has_septic': 'has_septic' in request.form,
            'has_garage': 'has_garage' in request.form,
        }
        
        try:
            # Check if features already exist for this user
            existing = supabase.table('home_features').select('id').eq('user_id', user_id).execute()
            
            if existing.data:
                # Update existing features
                supabase.table('home_features').update({
                    **features,
                    'user_id': user_id
                }).eq('user_id', user_id).execute()
            else:
                # Insert new features
                supabase.table('home_features').insert({
                    'user_id': user_id,
                    **features
                }).execute()
            
            # Generate tasks based on features
            generate_tasks_for_user(user_id, features)
            
            flash('Home features saved and tasks generated!')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            flash(f'Error saving features: {str(e)}')
    
    return render_template('questionnaire.html')

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
        tasks_result = supabase.table('tasks').select('*').eq('user_id', user_id).eq('is_completed', False).order('next_due_date').execute()
        tasks = tasks_result.data or []
        
        # Get recently completed tasks
        completed_result = supabase.table('tasks').select('*').eq('user_id', user_id).eq('is_completed', True).order('last_completed', desc=True).limit(10).execute()
        completed_tasks = completed_result.data or []
        
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
        
        return render_template('dashboard.html', 
                             overdue_tasks=overdue, 
                             upcoming_tasks=upcoming,
                             future_tasks=future,
                             completed_tasks=completed_tasks)
                             
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}')
        return render_template('dashboard.html', 
                             overdue_tasks=[], 
                             upcoming_tasks=[],
                             future_tasks=[],
                             completed_tasks=[])

@app.route('/complete_task/<int:task_id>')
def complete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    try:
        # Get task details
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        
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
    
    try:
        # Calculate next due date
        next_due = datetime.now() + timedelta(days=frequency_days)
        
        # Insert new task
        supabase.table('tasks').insert({
            'user_id': user_id,
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'next_due_date': next_due.date().isoformat(),
            'is_completed': False
        }).execute()
        
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
    title = request.form['title']
    description = request.form.get('description', '')
    frequency_days = request.form['frequency_days']
    
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
    
    try:
        # Verify task belongs to user
        task_result = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        
        if not task_result.data:
            flash('Task not found!')
            return redirect(url_for('dashboard'))
        
        # Update task
        supabase.table('tasks').update({
            'title': title,
            'description': description,
            'frequency_days': frequency_days
        }).eq('id', task_id).eq('user_id', user_id).execute()
        
        flash(f'Task "{title}" updated successfully!')
        
    except Exception as e:
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
        
        # Delete task
        supabase.table('tasks').delete().eq('id', task_id).eq('user_id', user_id).execute()
        
        return jsonify({'message': 'Task deleted successfully'})
        
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
        
        # Update task
        result = supabase.table('tasks').update({
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'priority': priority,
            'category': category
        }).eq('id', task_id).eq('user_id', current_user_id).execute()
        
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