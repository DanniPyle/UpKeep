from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.utils import secure_filename
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
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
from mailer import send_email
from email_templates import overdue_tasks_email, weekly_home_checkin, LOGO_URL

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Load configuration based on environment
env = os.getenv('FLASK_ENV', 'development')
if env == 'production':
    from config import ProductionConfig
    app.config.from_object(ProductionConfig)
else:
    from config import DevelopmentConfig
    app.config.from_object(DevelopmentConfig)

# Verify secret key is set
if not app.config.get('SECRET_KEY'):
    raise ValueError("FLASK_SECRET_KEY must be set in environment variables for security")

# CSRF Protection
csrf = CSRFProtect(app)

# CORS Configuration - Restrict to your domain
# In development, allow localhost. In production, set FRONTEND_URL to your domain
allowed_origins = []
if env == 'production':
    frontend_url = os.getenv('FRONTEND_URL')
    if frontend_url:
        allowed_origins = [frontend_url]
    else:
        # If no FRONTEND_URL set, only allow same-origin
        allowed_origins = []
else:
    # Development: allow localhost
    allowed_origins = [
        'http://localhost:5000',
        'http://127.0.0.1:5000',
        'http://localhost:3000',  # If you have a separate frontend
    ]

CORS(app, resources={
    r"/*": {
        "origins": allowed_origins if allowed_origins else False,
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "X-CSRFToken"],
        "supports_credentials": True
    }
})

# --- Minimal routes (root + health) ---
@app.route('/')
def index():
    """Landing: if logged in, go to dashboard; else show marketing index."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/create_task', methods=['POST'])
def create_task():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip()
    freq_raw = request.form.get('frequency_days')
    next_due_raw = (request.form.get('next_due_date') or '').strip()
    priority_raw = (request.form.get('priority') or '').strip().lower()
    category = (request.form.get('category') or '').strip() or None
    if not title:
        return ('Title is required', 400)
    try:
        frequency_days = int(freq_raw)
        if frequency_days <= 0:
            return ('Frequency must be positive', 400)
    except Exception:
        return ('Frequency must be a number', 400)
    # Normalize priority
    priority = None
    if priority_raw:
        priority = priority_raw if priority_raw in PRIORITY_VALUES else None
    # Compute next due
    try:
        if next_due_raw:
            nd = date.fromisoformat(next_due_raw)
            next_due = nd
        else:
            next_due = datetime.now().date() + timedelta(days=frequency_days)
    except Exception:
        return ('Invalid due date', 400)
    try:
        payload = {
            'user_id': user_id,
            'title': title,
            'description': description,
            'frequency_days': frequency_days,
            'next_due_date': next_due.isoformat(),
            'is_completed': False,
        }
        if category is not None:
            payload['category'] = category
        if priority is not None:
            payload['priority'] = priority
        
        # Insert task and get the created task ID
        result = supabase.table('tasks').insert(payload).execute()
        
        # Create history entry for task creation
        if result.data and len(result.data) > 0:
            task_id = result.data[0]['id']
            try:
                supabase.table('task_history').insert({
                    'task_id': task_id,
                    'user_id': user_id,
                    'action': 'created',
                    'created_at': datetime.now().isoformat()
                }).execute()
            except Exception as hist_error:
                print(f"Warning: Could not create history entry: {hist_error}")
        
        # For fetch-based caller, any 2xx is fine; return plain text
        return ('OK', 200)
    except Exception as e:
        return (f'Create failed: {e}', 500)

@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        # Ensure task belongs to user
        owned = supabase.table('tasks').select('id').eq('id', task_id).eq('user_id', user_id).execute()
        if not owned.data:
            return jsonify({'error': 'Task not found'}), 404
        # Delete task (and optionally history)
        try:
            supabase.table('task_history').delete().eq('task_id', task_id).eq('user_id', user_id).execute()
        except Exception:
            pass
        supabase.table('tasks').delete().eq('id', task_id).eq('user_id', user_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/tasks/<int:task_id>/history')
def task_history(task_id):
    """Return server-rendered HTML snippet for task history (for modal injection)."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        tres = supabase.table('tasks').select('id,title').eq('id', task_id).eq('user_id', user_id).execute()
        if not tres.data:
            return jsonify({'error': 'Task not found'}), 404
        task = tres.data[0]
        hist = supabase.table('task_history').select('*').eq('task_id', task_id).eq('user_id', user_id).order('created_at', desc=True).execute()
        history = hist.data or []
        html = render_template('partials/history_list.html', task=task, history=history)
        return html
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/edit_task/<int:task_id>', methods=['POST'])
def edit_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    title = request.form.get('title')
    description = request.form.get('description', '')
    frequency_days = request.form.get('frequency_days')
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
    except Exception:
        flash('Frequency must be a valid number!')
        return redirect(url_for('dashboard'))
    next_due_date = None
    if next_due_date_raw:
        try:
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
        # Verify task belongs to user
        task_res = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        if not task_res.data:
            flash('Task not found!')
            return redirect(url_for('dashboard'))
        row = task_res.data[0]
        payload = {}
        if 'title' in row: payload['title'] = title
        if 'description' in row: payload['description'] = description
        if 'frequency_days' in row: payload['frequency_days'] = frequency_days
        if 'category' in row and category is not None:
            payload['category'] = category
        if next_due_date is not None and 'next_due_date' in row:
            payload['next_due_date'] = next_due_date
        if priority is not None and 'priority' in row:
            payload['priority'] = priority
        
        # Update task
        supabase.table('tasks').update(payload).eq('id', task_id).eq('user_id', user_id).eq('archived', False).execute()
        
        # Create history entry
        try:
            supabase.table('task_history').insert({
                'task_id': task_id,
                'user_id': user_id,
                'action': 'updated',
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception as hist_error:
            print(f"Warning: Could not create history entry: {hist_error}")
        
        flash(f'Task "{title}" updated successfully!')
    except Exception as e:
        flash(f'Error updating task: {e}')
    return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/healthz')
def healthz():
    return jsonify({'ok': True, 'time': datetime.utcnow().isoformat()+'Z'}), 200

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
    
    # Exact matches for common frequencies
    mapping = {
        1: 'Daily',
        7: 'Weekly',
        14: 'Every 2 Weeks',
        21: 'Every 3 Weeks',
        28: 'Every 4 Weeks',
        30: 'Monthly',
        60: 'Every 2 Months',
        90: 'Every 3 Months',
        120: 'Every 4 Months',
        180: 'Every 6 Months',
        270: 'Every 9 Months',
        365: 'Yearly',
        730: 'Every 2 Years',
        1095: 'Every 3 Years',
        1460: 'Every 4 Years',
        1825: 'Every 5 Years',
        2190: 'Every 6 Years',
        2555: 'Every 7 Years',
        2920: 'Every 8 Years',
        3650: 'Every 10 Years',
    }
    if d in mapping:
        return mapping[d]
    
    # Smart rounding for near-matches (within 5 days)
    for exact_days, label in mapping.items():
        if abs(d - exact_days) <= 5 and exact_days >= 30:
            return label
    
    # Heuristics: show common month/years when near multiples
    if d % 365 == 0:
        n = d // 365
        return f"Every {n} Year{'s' if n != 1 else ''}"
    
    # Check if close to a year multiple (within 10 days)
    years = round(d / 365)
    if years > 0 and abs(d - (years * 365)) <= 10:
        return f"Every {years} Year{'s' if years != 1 else ''}"
    
    if d % 30 == 0:
        n = d // 30
        if n == 1:
            return 'Monthly'
        return f"Every {n} Months"
    
    # Check if close to a month multiple (within 3 days)
    months = round(d / 30)
    if months > 0 and abs(d - (months * 30)) <= 3 and d >= 30:
        if months == 1:
            return 'Monthly'
        return f"Every {months} Months"
    
    if d % 7 == 0 and d <= 84:
        n = d // 7
        return f"Every {n} Week{'s' if n != 1 else ''}"
    
    # Fallback to days
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
    # Map new aliases to existing questionnaire fields
    'has_outdoor': 'has_yard',  # has_outdoor -> has_yard
    'has_deck': 'has_deck_patio',  # has_deck -> has_deck_patio
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
    # Additional feature aliases
    'has_carpet',
    'has_outdoor',
    'has_deck',
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
    'initial_cap': 5,  # Reduced from 8 - gentler start
    # Stagger the rest over this many weeks
    'stagger_weeks': 12,  # Increased from 8 - slower rollout
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

def reactivate_due_tasks(user_id):
    """Mark tasks as active again if their next_due_date is now in the past (while keeping archived)."""
    today = datetime.now().date().isoformat()
    try:
        supabase.table('tasks').update({
            'is_completed': False
        }).eq('user_id', user_id).eq('is_completed', True).eq('archived', False).lte('next_due_date', today).execute()
    except Exception as e:
        print(f"Error reactivating tasks: {e}")

# -------------------------
# Auth routes
# -------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Validation
        if not name or not email or not password:
            flash('All fields are required!')
            return render_template('register.html')
        
        # Email validation
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            flash('Please enter a valid email address (e.g., user@example.com)')
            return render_template('register.html')
        
        # Password validation
        if len(password) < 8:
            flash('Password must be at least 8 characters long')
            return render_template('register.html')
        
        if not re.search(r'[A-Z]', password):
            flash('Password must contain at least one uppercase letter')
            return render_template('register.html')
        
        if not re.search(r'[a-z]', password):
            flash('Password must contain at least one lowercase letter')
            return render_template('register.html')
        
        if not re.search(r'[0-9]', password):
            flash('Password must contain at least one number')
            return render_template('register.html')
        
        try:
            existing = supabase.table('users').select('id').eq('email', email).execute()
            if existing.data:
                flash('Email already exists!')
                return render_template('register.html')
            password_hash = generate_password_hash(password)
            res = supabase.table('users').insert({
                'username': name,
                'email': email,
                'password_hash': password_hash
            }).execute()
            if res.data:
                user = res.data[0]
                session.permanent = True  # Enable session lifetime
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('Registration successful!')
                return redirect(url_for('questionnaire')) if 'questionnaire' in app.view_functions else redirect(url_for('dashboard'))
            flash('Registration failed. Please try again.')
        except Exception as e:
            flash(f'Registration error: {str(e)}')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            res = supabase.table('users').select('*').eq('email', email).execute()
            if res.data and check_password_hash(res.data[0]['password_hash'], password):
                user = res.data[0]
                session.permanent = True  # Enable session lifetime
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('dashboard'))
            flash('Invalid email or password!')
        except Exception as e:
            flash(f'Login error: {str(e)}')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        
        if not email:
            flash('Please enter your email address')
            return render_template('forgot_password.html')
        
        # Email validation
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            flash('Please enter a valid email address')
            return render_template('forgot_password.html')
        
        try:
            # Check if user exists
            user_result = supabase.table('users').select('id, username, email').eq('email', email).execute()
            
            if user_result.data:
                user = user_result.data[0]
                
                # Generate reset token (valid for 1 hour)
                reset_token = jwt.encode({
                    'user_id': user['id'],
                    'exp': datetime.utcnow() + timedelta(hours=1)
                }, app.secret_key, algorithm='HS256')
                
                # Send reset email
                app_url = os.getenv('APP_URL', 'http://localhost:5000')
                reset_url = f"{app_url}/reset-password/{reset_token}"
                
                html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #2d2f3a; background-color: #f2f2f2; margin: 0; padding: 0; }}
        .container {{ max-width: 600px; margin: 20px auto; background: #ffffff !important; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .header {{ background: #ffffff !important; padding: 24px; text-align: center; border-bottom: 2px solid #f2f2f2; }}
        .header img {{ max-width: 280px; height: auto; }}
        .content {{ padding: 32px 24px; background: #ffffff !important; }}
        .btn {{ display: inline-block; background: #2f3e56; color: #ffffff; padding: 14px 36px; text-decoration: none; border-radius: 6px; font-weight: 600; margin: 20px 0; }}
        .footer {{ background: #f2f2f2 !important; padding: 24px; text-align: center; font-size: 13px; color: #7a8a94 !important; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="{LOGO_URL}" alt="Keeply Home" />
        </div>
        <div class="content">
            <h2 style="color: #2d2f3a; margin-top: 0;">Reset Your Password</h2>
            <p>Hi {user['username']},</p>
            <p>We received a request to reset your password for your Keeply Home account.</p>
            <p>Click the button below to create a new password. This link will expire in 1 hour.</p>
            <div style="text-align: center;">
                <a href="{reset_url}" class="btn">Reset Password</a>
            </div>
            <p style="color: #7a8a94; font-size: 14px; margin-top: 24px;">If you didn't request this, you can safely ignore this email. Your password won't be changed.</p>
            <p style="color: #7a8a94; font-size: 13px;">Or copy and paste this link into your browser:<br>
            <a href="{reset_url}" style="color: #7a8a94; word-break: break-all;">{reset_url}</a></p>
        </div>
        <div class="footer">
            <p>💛 The Keeply Team</p>
        </div>
    </div>
</body>
</html>
"""
                
                text = f"""Hi {user['username']},

We received a request to reset your password for your Keeply Home account.

Click the link below to create a new password. This link will expire in 1 hour.

{reset_url}

If you didn't request this, you can safely ignore this email. Your password won't be changed.

💛 The Keeply Team
"""
                
                send_email(email, "Reset Your Keeply Home Password", html, text)
                flash('Password reset instructions have been sent to your email')
                return redirect(url_for('login'))
            else:
                # Don't reveal if email exists or not (security best practice)
                flash('If an account exists with that email, password reset instructions have been sent')
                return redirect(url_for('login'))
                
        except Exception as e:
            import traceback
            print(f"Forgot password error: {e}")
            traceback.print_exc()
            flash(f'An error occurred: {str(e)}')
            return render_template('forgot_password.html')
    
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        # Verify token
        payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
        user_id = payload['user_id']
    except jwt.ExpiredSignatureError:
        flash('Password reset link has expired. Please request a new one.')
        return redirect(url_for('forgot_password'))
    except jwt.InvalidTokenError:
        flash('Invalid password reset link.')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if not password or not confirm_password:
            flash('Please fill in all fields')
            return render_template('reset_password.html', token=token)
        
        if password != confirm_password:
            flash('Passwords do not match')
            return render_template('reset_password.html', token=token)
        
        # Password validation
        import re
        if len(password) < 8:
            flash('Password must be at least 8 characters long')
            return render_template('reset_password.html', token=token)
        
        if not re.search(r'[A-Z]', password):
            flash('Password must contain at least one uppercase letter')
            return render_template('reset_password.html', token=token)
        
        if not re.search(r'[a-z]', password):
            flash('Password must contain at least one lowercase letter')
            return render_template('reset_password.html', token=token)
        
        if not re.search(r'[0-9]', password):
            flash('Password must contain at least one number')
            return render_template('reset_password.html', token=token)
        
        try:
            # Update password
            password_hash = generate_password_hash(password)
            supabase.table('users').update({'password_hash': password_hash}).eq('id', user_id).execute()
            
            flash('Password successfully reset! You can now login with your new password.')
            return redirect(url_for('login'))
        except Exception as e:
            import traceback
            print(f"Reset password error: {e}")
            traceback.print_exc()
            flash(f'An error occurred: {str(e)}')
            return render_template('reset_password.html', token=token)
    
    return render_template('reset_password.html', token=token)

# -------------------------
# Core pages
# -------------------------
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        reactivate_due_tasks(user_id)
        try:
            tasks_res = (supabase.table('tasks')
                         .select('*')
                         .eq('user_id', user_id)
                         .eq('is_completed', False)
                         .eq('archived', False)
                         .order('next_due_date')
                         .execute())
            tasks = tasks_res.data or []
        except Exception:
            # Fallback if 'archived' column does not exist
            tasks_res = (supabase.table('tasks')
                         .select('*')
                         .eq('user_id', user_id)
                         .eq('is_completed', False)
                         .order('next_due_date')
                         .execute())
            tasks = tasks_res.data or []
        today = datetime.now().date()
        next_month = today + timedelta(days=30)
        overdue = []
        upcoming = []
        future = []
        for t in tasks:
            nd = t.get('next_due_date')
            if not nd:
                future.append(t)
                continue
            try:
                d = datetime.fromisoformat(nd).date()
            except Exception:
                future.append(t); continue
            if d < today:
                overdue.append(t)
            elif d <= next_month:
                upcoming.append(t)
            else:
                future.append(t)
        # Recently completed
        try:
            completed = (supabase.table('tasks').select('*')
                         .eq('user_id', user_id)
                         .eq('archived', False)
                         .eq('is_completed', True)
                         .order('last_completed', desc=True)
                         .limit(10)
                         .execute()).data or []
        except Exception:
            completed = (supabase.table('tasks').select('*')
                         .eq('user_id', user_id)
                         .eq('is_completed', True)
                         .order('last_completed', desc=True)
                         .limit(10)
                         .execute()).data or []
        # Pick most urgent task (highest priority overdue, or oldest overdue)
        urgent_task = None
        if overdue:
            # Sort by priority (high > medium > low > none) then by due date (oldest first)
            priority_order = {'high': 0, 'medium': 1, 'low': 2, None: 3, '': 3}
            sorted_overdue = sorted(overdue, key=lambda t: (priority_order.get((t.get('priority') or '').lower(), 3), t.get('next_due_date') or '9999-99-99'))
            urgent_task = sorted_overdue[0]
        
        overview = {
            'total_active': len(tasks),
            'overdue_count': len(overdue),
            'due_7_days': sum(1 for t in tasks if t.get('next_due_date') and today <= datetime.fromisoformat(t['next_due_date']).date() <= today + timedelta(days=7)),
            'completed_7_days': sum(1 for t in completed if t.get('last_completed') and (today - datetime.fromisoformat(t['last_completed']).date()).days <= 7)
        }
        return render_template('dashboard.html', overview=overview, overdue_tasks=overdue, upcoming_tasks=upcoming, future_tasks=future, completed_tasks=completed, urgent_task=urgent_task, baseline_done=True, baseline_dismissed=True, baseline_last_checked=None, baseline_features={})
    except Exception as e:
        flash(f'Error loading dashboard: {e}')
        return render_template('dashboard.html', overview=None, overdue_tasks=[], upcoming_tasks=[], future_tasks=[], completed_tasks=[], baseline_done=True, baseline_dismissed=True, baseline_last_checked=None, baseline_features={})

@app.route('/roadmap')
def roadmap():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        today = datetime.now().date()
        horizon = today + timedelta(days=56)
        try:
            res = (supabase.table('tasks').select('*')
                   .eq('user_id', user_id)
                   .eq('archived', False)
                   .eq('is_completed', False)
                   .gte('next_due_date', today.isoformat())
                   .lte('next_due_date', horizon.isoformat())
                   .order('next_due_date')
                   .execute())
        except Exception:
            res = (supabase.table('tasks').select('*')
                   .eq('user_id', user_id)
                   .eq('is_completed', False)
                   .gte('next_due_date', today.isoformat())
                   .lte('next_due_date', horizon.isoformat())
                   .order('next_due_date')
                   .execute())
        rows = res.data or []
        def week_start(d):
            return d - timedelta(days=d.weekday())
        weeks = {}
        for t in rows:
            try:
                due = datetime.fromisoformat((t.get('next_due_date') or '')).date()
            except Exception:
                continue
            ws = week_start(due)
            weeks.setdefault(ws, []).append(t)
        items = []
        for ws, ts in weeks.items():
            we = ws + timedelta(days=6)
            items.append({
                'week_start': ws,
                'week_end': we,
                'count': len(ts),
                'high_count': sum(1 for x in ts if (x.get('priority') or '').lower() == 'high'),
                'seasonal_count': sum(1 for x in ts if bool(x.get('seasonal'))),
                'tasks': sorted(ts, key=lambda x: (x.get('next_due_date') or '', (x.get('priority') or 'z')))
            })
        items.sort(key=lambda x: x['week_start'])
        return render_template('roadmap.html', weeks=items, today=today, horizon=horizon)
    except Exception as e:
        flash(f'Failed to load roadmap: {e}')
        return redirect(url_for('dashboard'))

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

    # Compute start (Sunday) to end (Saturday) covering the month grid
    start_weekday = first_of_month.weekday()  # Monday=0..Sunday=6
    days_back_to_sunday = (start_weekday + 1) % 7
    grid_start = first_of_month - timedelta(days=days_back_to_sunday)

    # End of month and grid end
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
        except Exception:
            tasks_result = (supabase
                            .table('tasks')
                            .select('*')
                            .eq('user_id', user_id)
                            .eq('is_completed', False)
                            .gte('next_due_date', grid_start.isoformat())
                            .lte('next_due_date', grid_end.isoformat())
                            .order('next_due_date')
                            .execute())
        tasks = tasks_result.data or []
    except Exception:
        tasks = []

    # Group tasks by date
    by_date = {}
    for t in tasks:
        try:
            d = datetime.fromisoformat(t['next_due_date']).date()
            by_date.setdefault(d.isoformat(), []).append(t)
        except Exception:
            continue

    # Build days grid
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

    # Get month name
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December']
    month_name = month_names[month - 1]
    
    return render_template('calendar.html', 
                           year=year,
                           month=month,
                           month_name=month_name,
                           days=days,
                           prev_year=prev_year,
                           prev_month=prev_month,
                           next_year=next_year,
                           next_month=next_month,
                           today_year=today.year,
                           today_month=today.month)

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        # Load user for display
        ures = supabase.table('users').select('*').eq('id', user_id).execute()
        user = ures.data[0] if ures.data else {}
        if request.method == 'POST':
            name = (request.form.get('name') or '').strip()
            email = (request.form.get('email') or '').strip()
            current_pw = request.form.get('current_password') or ''
            new_pw = request.form.get('new_password') or ''
            confirm_pw = request.form.get('confirm_password') or ''
            updates = {}
            if name and name != user.get('username'):
                updates['username'] = name
                session['username'] = name
            if email and email != user.get('email'):
                exists = supabase.table('users').select('id').eq('email', email).neq('id', user_id).execute()
                if exists.data:
                    flash('That email is already in use')
                    return redirect(url_for('settings'))
                updates['email'] = email
            if any([current_pw, new_pw, confirm_pw]):
                if not (current_pw and new_pw and confirm_pw):
                    flash('Fill all password fields to change your password')
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
                flash('Settings updated')
            else:
                flash('No changes to update')
            return redirect(url_for('settings'))
        return render_template('settings.html', user=user)
    except Exception as e:
        flash(f'Error loading settings: {e}')
        return render_template('settings.html', user={})

@app.route('/questionnaire', methods=['GET', 'POST'])
def questionnaire():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    if request.method == 'POST':
        # Save all questionnaire fields
        try:
            features = {
                'user_id': user_id,
                # Home basics
                'home_type': request.form.get('home_type'),
                'year_built': request.form.get('year_built'),
                'home_size': request.form.get('home_size'),
                'has_yard': request.form.get('has_yard') == 'yes',
                'carpet': request.form.get('carpet'),
                # Systems
                'has_hvac': bool(request.form.get('has_hvac')),
                'has_window_units': bool(request.form.get('has_window_units')),
                'has_radiator_boiler': bool(request.form.get('has_radiator_boiler')),
                'no_central_hvac': bool(request.form.get('no_central_hvac')),
                'has_water_heater': bool(request.form.get('has_water_heater')),
                'has_water_softener': bool(request.form.get('has_water_softener')),
                'has_well': bool(request.form.get('has_well')),
                'has_septic': bool(request.form.get('has_septic')),
                'has_sump_pump': request.form.get('has_sump_pump') == 'yes',
                'fireplace_type': request.form.get('fireplace_type'),
                # Appliances
                'has_dishwasher': bool(request.form.get('has_dishwasher')),
                'has_garbage_disposal': bool(request.form.get('has_garbage_disposal')),
                'has_washer_dryer': bool(request.form.get('has_washer_dryer')),
                'has_refrigerator_ice': bool(request.form.get('has_refrigerator_ice')),
                'has_range_hood': bool(request.form.get('has_range_hood')),
                # Exterior
                'has_gutters': request.form.get('has_gutters') == 'yes',
                'garage_type': request.form.get('garage_type'),
                'has_deck_patio': request.form.get('has_deck_patio') == 'yes',
                'has_pool_hot_tub': request.form.get('has_pool_hot_tub') == 'yes',
                # Climate
                'freezes': request.form.get('freezes') == 'yes',
                'season_spring': f"2024-{request.form.get('season_spring', '03')}-01" if request.form.get('season_spring') else None,
                'season_summer': f"2024-{request.form.get('season_summer', '06')}-01" if request.form.get('season_summer') else None,
                'season_autumn': f"2024-{request.form.get('season_autumn', '09')}-01" if request.form.get('season_autumn') else None,
                'season_winter': f"2024-{request.form.get('season_winter', '12')}-01" if request.form.get('season_winter') else None,
                # Lifestyle
                'has_pets': request.form.get('has_pets') == 'yes',
                'pet_dog': bool(request.form.get('pet_dog')),
                'pet_cat': bool(request.form.get('pet_cat')),
                'pet_other': bool(request.form.get('pet_other')),
                'travel_often': request.form.get('travel_often') == 'yes',
            }
            # Persist persona and time budget on the users table (NOT in home_features)
            try:
                persona = (request.form.get('persona') or '').strip().lower() or None
                tb_raw = request.form.get('time_budget')
                time_budget_minutes = None
                if tb_raw is not None and str(tb_raw).strip() != '':
                    try:
                        time_budget_minutes = int(tb_raw)
                    except Exception:
                        time_budget_minutes = None
                updates = {}
                if persona:
                    updates['persona'] = persona
                if time_budget_minutes is not None:
                    updates['time_budget_minutes_per_week'] = time_budget_minutes
                if updates:
                    updates['onboarding_started_at'] = datetime.utcnow().isoformat()+'Z'
                    supabase.table('users').update(updates).eq('id', user_id).execute()
            except Exception:
                # Non-fatal: ignore if columns do not exist yet
                pass
            existing = supabase.table('home_features').select('user_id').eq('user_id', user_id).execute()
            if existing.data:
                supabase.table('home_features').update(features).eq('user_id', user_id).execute()
            else:
                supabase.table('home_features').insert(features).execute()
            # Regenerate tasks using DB templates if available
            diag = seed_tasks_from_static_catalog_or_templates(user_id, features)
            if diag.get('source') == 'error':
                flash(f'Error creating your plan: {diag.get("error", "unknown error")}', 'error')
            else:
                # Success - redirect without debug message
                pass
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Failed to save features: {e}')
            return redirect(url_for('questionnaire'))
    # GET: prefill
    prefill = {}
    try:
        res = supabase.table('home_features').select('*').eq('user_id', user_id).execute()
        if res.data:
            prefill = res.data[0]
    except Exception:
        pass
    return render_template('questionnaire.html', prefill=prefill)

# -------------------------
# Baseline Checkup endpoints (used by dashboard modal)
# -------------------------
@app.route('/baseline/dismiss', methods=['POST'])
def baseline_dismiss():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
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
        # Also hide CTA immediately this session
        session['baseline_done'] = True
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _adjust_tasks_from_baseline(user_id, answers):
    """Lightweight adjustments based on baseline answers.
    Brings forward problem areas; defers pristine ones.
    """
    today = datetime.utcnow().date()
    try:
        res = supabase.table('tasks').select('id,title,task_key,next_due_date,priority').eq('user_id', user_id).eq('archived', False).execute()
        rows = res.data or []
        updates = []
        def bump(ids_or_substrings, days=7, priority=None):
            for t in rows:
                title = (t.get('title') or '').lower()
                if any(s in title for s in ids_or_substrings):
                    pl = {'next_due_date': (today + timedelta(days=days)).isoformat()}
                    if priority:
                        pl['priority'] = priority
                    updates.append((t['id'], pl))
        # Exterior issues
        if answers.get('siding_condition') == 'needs_repair':
            bump(['siding','exterior paint','paint'], days=7, priority='high')
        glc = answers.get('gutters_last_cleaned')
        if glc in ('over_12m','not_sure'):
            bump(['gutter','downspout'], days=7, priority='high')
        # Systems
        hvac = answers.get('hvac_filter_last')
        if hvac in ('over_6m','not_sure'):
            bump(['hvac filter','replace hvac filter','check hvac filters'], days=7, priority='medium')
        wh = answers.get('water_heater_service')
        if wh in ('over_3y','not_sure'):
            bump(['water heater','flush hot water heater'], days=10, priority='medium')
        sump = answers.get('sump_pump_tested')
        if sump in ('not_recently','not_sure'):
            bump(['sump pump'], days=14, priority='medium')
        # Appliances
        dw = answers.get('dishwasher_filter_last')
        if dw in ('over_6m','not_sure'):
            bump(['dishwasher filter'], days=10)
        dryer = answers.get('dryer_vent_last')
        if dryer in ('over_1y','not_sure'):
            bump(['dryer vent'], days=10, priority='medium')
        # Apply updates
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
        }
        _adjust_tasks_from_baseline(user_id, answers)
        # Persist flags so CTA hides
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
    
    # Get filter parameters
    search_query = request.args.get('q', '').strip()  # Search query
    show_archived = request.args.get('show_archived') == 'true'
    show_completed = request.args.get('show_completed') == 'true'
    date_filter = request.args.get('date')  # Specific date filter (YYYY-MM-DD)
    
    try:
        # Base query - get all non-archived tasks
        query = supabase.table('tasks').select('*').eq('user_id', user_id)
        
        if not show_archived:
            query = query.eq('archived', False)
        
        res = query.execute()
        all_tasks = res.data or []
        
        # Apply search filter
        if search_query:
            search_lower = search_query.lower()
            all_tasks = [t for t in all_tasks if 
                        search_lower in (t.get('title') or '').lower() or 
                        search_lower in (t.get('description') or '').lower()]
        
        # If date filter is provided, filter to that specific date
        if date_filter:
            try:
                target_date = datetime.fromisoformat(date_filter).date()
                filtered_tasks = [t for t in all_tasks if t.get('next_due_date') and 
                                 datetime.fromisoformat(t['next_due_date']).date() == target_date]
                # Return single column view for date-filtered tasks
                return render_template('tasks.html',
                                     overdue_tasks=[],
                                     this_week_tasks=[],
                                     this_month_tasks=[],
                                     later_tasks=[],
                                     completed_tasks=[],
                                     date_filtered_tasks=filtered_tasks,
                                     filter_date=target_date,
                                     show_archived=show_archived,
                                     show_completed=show_completed)
            except Exception:
                pass  # Fall through to normal kanban view
        
        # Organize tasks into kanban columns
        today = datetime.now().date()
        end_of_week = today + timedelta(days=(6 - today.weekday()))  # Sunday
        end_of_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        overdue_tasks = []
        this_week_tasks = []
        this_month_tasks = []
        later_tasks = []
        completed_tasks = []
        
        for t in all_tasks:
            # Completed tasks
            if t.get('is_completed'):
                if show_completed:
                    completed_tasks.append(t)
                continue
            
            # Active tasks - organize by due date
            nd = t.get('next_due_date')
            if not nd:
                later_tasks.append(t)
                continue
            
            try:
                due_date = datetime.fromisoformat(nd).date()
            except Exception:
                later_tasks.append(t)
                continue
            
            if due_date < today:
                overdue_tasks.append(t)
            elif due_date <= end_of_week:
                this_week_tasks.append(t)
            elif due_date <= end_of_month:
                this_month_tasks.append(t)
            else:
                later_tasks.append(t)
        
        # Sort each column by due date
        overdue_tasks.sort(key=lambda t: t.get('next_due_date') or '9999-99-99')
        this_week_tasks.sort(key=lambda t: t.get('next_due_date') or '9999-99-99')
        this_month_tasks.sort(key=lambda t: t.get('next_due_date') or '9999-99-99')
        later_tasks.sort(key=lambda t: t.get('next_due_date') or '9999-99-99')
        completed_tasks.sort(key=lambda t: t.get('last_completed') or '0000-00-00', reverse=True)
            
    except Exception as e:
        print(f"Error loading tasks: {e}")
        overdue_tasks = []
        this_week_tasks = []
        this_month_tasks = []
        later_tasks = []
        completed_tasks = []
    
    return render_template('tasks.html', 
                         overdue_tasks=overdue_tasks,
                         this_week_tasks=this_week_tasks,
                         this_month_tasks=this_month_tasks,
                         later_tasks=later_tasks,
                         completed_tasks=completed_tasks,
                         date_filtered_tasks=[],
                         filter_date=None,
                         show_archived=show_archived,
                         show_completed=show_completed)

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
        print(f"Error loading home_features: {e}")

    # Simple overview
    try:
        t_res = supabase.table('tasks').select('*').eq('user_id', user_id).eq('archived', False).execute()
        all_tasks = t_res.data or []
        today = datetime.now().date()
        overdue = []
        upcoming = []
        for t in all_tasks:
            nd = t.get('next_due_date')
            if not nd:
                continue
            try:
                d = datetime.fromisoformat(nd).date()
            except Exception:
                continue
            if d < today:
                overdue.append(t)
            elif d <= today + timedelta(days=30):
                upcoming.append(t)
        # Completed last 30 days
        completed_recent = 0
        try:
            hist = supabase.table('task_history').select('created_at').eq('user_id', user_id).eq('action', 'completed').order('created_at', desc=True).limit(200).execute()
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
        overview = {
            'overdue_count': len(overdue),
            'due_7_days': sum(1 for t in all_tasks if t.get('next_due_date') and today <= datetime.fromisoformat(t['next_due_date']).date() <= today + timedelta(days=7)),
            'completed_7_days': completed_recent,
        }
        upcoming_tasks = upcoming
    except Exception as e:
        print(f"Error computing home overview: {e}")

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
    allowed = {'.png', '.jpg', '.jpeg', '.webp'}
    name = secure_filename(file.filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in allowed:
        flash('Unsupported image type. Please upload PNG, JPG, or WEBP.')
        return redirect(url_for('home'))
    try:
        bucket = 'home-photos'
        object_path = f"user_{session['user_id']}/banner{ext}"
        file.stream.seek(0)
        data = file.read()
        supabase.storage.from_(bucket).upload(path=object_path, file=data, file_options={
            'content-type': file.mimetype or f"image/{ext.strip('.')}",
            'x-upsert': 'true'
        })
        public_url = supabase.storage.from_(bucket).get_public_url(object_path)
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

@app.route('/task/<int:task_id>')
def task_detail(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        tres = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        if not tres.data:
            flash('Task not found')
            return redirect(url_for('task_list'))
        task = tres.data[0]
        hres = supabase.table('task_history').select('*').eq('task_id', task_id).eq('user_id', user_id).order('created_at', desc=True).execute()
        history = hres.data or []
        return render_template('task_detail.html', task=task, history=history)
    except Exception as e:
        flash(f'Error loading task: {e}')
        return redirect(url_for('task_list'))

@app.route('/restore_task/<int:task_id>', methods=['POST'])
def restore_task(task_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    user_id = session['user_id']
    try:
        res = supabase.table('tasks').select('id,archived').eq('id', task_id).eq('user_id', user_id).execute()
        if not res.data:
            return jsonify({'error': 'Task not found'}), 404
        supabase.table('tasks').update({'archived': False}).eq('id', task_id).eq('user_id', user_id).execute()
        return jsonify({'message': 'Task restored'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
            headers, rows = _read_csv_upload(file)
            # Save as-is to static/tasks_catalog.csv
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
    return render_template('catalog.html')

@app.route('/tasks/regenerate', methods=['POST'])
def regenerate_tasks():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        fres = supabase.table('home_features').select('*').eq('user_id', user_id).execute()
        features_row = fres.data[0] if fres.data else {}
        feature_flags = {k: bool(features_row.get(k, False)) for k in ALLOWED_FEATURE_KEYS}
        # Seed from DB templates first, fallback to CSV
        diag = seed_tasks_from_static_catalog_or_templates(user_id, feature_flags)
        if diag.get('source') == 'error':
            flash(f'Seeding error: {diag.get("error", "unknown error")}', 'error')
        else:
            flash(f'Regenerated: {diag.get("source")} source, {diag.get("considered")} templates, {diag.get("matched")} matched, {diag.get("inserted")} tasks inserted.')
    except Exception as e:
        flash(f'Failed to regenerate tasks: {e}')
    return redirect(url_for('dashboard'))

 

@app.route('/home/basics', methods=['POST'])
def save_home_basics():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
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
            float(v)
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

@app.route('/complete_task/<int:task_id>')
def complete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        res = supabase.table('tasks').select('*').eq('id', task_id).eq('user_id', user_id).execute()
        if not res.data:
            flash('Task not found')
            return redirect(url_for('dashboard'))
        task = res.data[0]
        today = datetime.now().date()
        next_due = today + timedelta(days=task['frequency_days'])
        
        # Update task
        supabase.table('tasks').update({
            'is_completed': True, 
            'last_completed': today.isoformat(), 
            'next_due_date': next_due.isoformat()
        }).eq('id', task_id).execute()
        
        # Create history entry
        try:
            supabase.table('task_history').insert({
                'task_id': task_id,
                'user_id': user_id,
                'action': 'completed',
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception as hist_error:
            print(f"Warning: Could not create history entry: {hist_error}")
        
        flash(f'Task "{task["title"]}" completed! Next due: {next_due}')
    except Exception as e:
        flash(f'Error completing task: {e}')
    return redirect(url_for('dashboard'))

@app.route('/reset_task/<int:task_id>')
def reset_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    try:
        res = supabase.table('tasks').select('id').eq('id', task_id).eq('user_id', user_id).execute()
        if not res.data:
            flash('Task not found')
            return redirect(url_for('dashboard'))
        
        # Update task
        supabase.table('tasks').update({
            'is_completed': False, 
            'last_completed': None
        }).eq('id', task_id).execute()
        
        # Create history entry
        try:
            supabase.table('task_history').insert({
                'task_id': task_id,
                'user_id': user_id,
                'action': 'reset',
                'created_at': datetime.now().isoformat()
            }).execute()
        except Exception as hist_error:
            print(f"Warning: Could not create history entry: {hist_error}")
        
        flash('Task reset to active')
    except Exception as e:
        flash(f'Error resetting task: {e}')
    return redirect(url_for('dashboard'))

def _next_anchor_date(month, day, today=None):
    """Return the next occurrence of a given month/day anchor date from today."""
    if today is None:
        today = datetime.now().date()
    try:
        this_year = datetime(today.year, month, day).date()
        if this_year >= today:
            return this_year
        return datetime(today.year + 1, month, day).date()
    except ValueError:
        # Invalid date (e.g., Feb 30) - fallback to end of month
        if month == 2:
            return datetime(today.year, 2, 28).date()
        return today + timedelta(days=365)

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
            # Special handling for has_carpet (stored as 'yes'/'no'/'some')
            if k == 'has_carpet':
                carpet_value = features.get('carpet', '')
                has_carpet = carpet_value in ('yes', 'some')
                if has_carpet != bool(v):
                    ok = False
                    break
            else:
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
    # Ensure optional feature flag exists even if constant was removed
    global TASK_KEY_SUPPORTED
    if 'TASK_KEY_SUPPORTED' not in globals():
        TASK_KEY_SUPPORTED = False
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
        # Optional: map start_offset_days to a small stagger offset hint (days within period)
        stagger_offset = _parse_int(r.get('start_offset_days'), default=None)

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
            'seeded_from_onboarding': True,
            'estimated_minutes': _estimate_minutes(r),
        }
        if stagger_offset is not None:
            try:
                payload['stagger_offset'] = int(stagger_offset)
            except Exception:
                pass
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
                # Generic fallback: strip optional columns and retry minimal payload
                # Only include core columns that should exist in all deployments
                MIN_KEYS = {'user_id','title','description','frequency_days','next_due_date','is_completed'}
                minimal = []
                for row in batch:
                    minimal.append({k: v for k, v in row.items() if k in MIN_KEYS})
                try:
                    supabase.table('tasks').insert(minimal).execute()
                    print(f"Retried batch {i//batch_size+1} with minimal columns and succeeded.")
                except Exception as e3:
                    print(f"Retry with minimal columns failed for batch {i//batch_size+1}: {e3}")
                # Continue with remaining batches to salvage progress
                continue

def _enrich_task_rows_defaults(rows):
    """Mutate in-place: add sensible defaults for missing fields based on title/metadata.
    Sets: priority, safety_critical, category, seasonal, activation_stage if missing.
    """
    SAFETY_SURFACES = (
        'smoke detector', 'carbon monoxide', 'co detector', 'gfi', 'gfci', 'alarm',
        'natural gas', 'leak', 'dryer vent', 'shutoff', 'sump pump'
    )
    SAFETY_ACTION_TESTS = ('test', 'check', 'inspect')
    CATEGORY_MAP = {
        'hvac': ('filter', 'furnace', 'air handler', 'ac ', 'a/c', 'condenser', 'registers'),
        'plumbing': ('water heater', 'sink', 'toilet', 'leak', 'softener', 'septic', 'sump', 'shutoff'),
        'kitchen': ('dishwasher', 'range hood', 'refrigerator', 'garbage disposal'),
        'exterior': ('gutters', 'downspout', 'deck', 'patio', 'fence', 'garage door', 'roof', 'masonry', 'brick'),
        'safety': ('smoke', 'co ', 'carbon monoxide', 'alarm', 'extinguisher', 'gfi', 'gfci', 'fire '),
        'laundry': ('dryer', 'lint', 'washer'),
    }
    for r in rows:
        title = (r.get('title') or '').strip()
        t_low = title.lower()
        # Priority default
        pr = (r.get('priority') or '').strip().lower()
        # Compute safety_critical first so we can use it for priority
        # safety_critical default flag (used by ramp):
        # Only consider as safety-critical when it's a test/check/inspect of safety surfaces.
        if r.get('safety_critical') in (None, ''):
            is_safety_surface = any(k in t_low for k in SAFETY_SURFACES)
            is_test_action = any(a in t_low for a in SAFETY_ACTION_TESTS)
            r['safety_critical'] = bool(is_safety_surface and is_test_action)
        # If explicitly about replacing fire extinguishers, do NOT mark as safety-critical by default
        if 'replace' in t_low and 'extinguisher' in t_low:
            r['safety_critical'] = False

        if not pr:
            if bool(r.get('safety_critical')):
                r['priority'] = 'high'
            elif 'filter' in t_low or 'gutters' in t_low:
                r['priority'] = 'medium'
            else:
                r['priority'] = None
        # Category default
        cat = (r.get('category') or '').strip().lower()
        if not cat:
            for name, keys in CATEGORY_MAP.items():
                if any(k in t_low for k in keys):
                    r['category'] = name
                    break
        # Seasonal default
        if r.get('seasonal') in (None, ''):
            has_season_meta = bool((r.get('season_code') or '').strip() or (r.get('seasonal_anchor_type') or '').strip())
            if has_season_meta or 'winterize' in t_low or 'spring' in t_low or 'fall ' in t_low or 'autumn' in t_low:
                r['seasonal'] = True
        # Activation stage hint from frequency
        try:
            freq = int(r.get('frequency_days') or 0)
        except Exception:
            freq = 0
        if r.get('activation_stage') in (None, ''):
            if freq >= 365*2:
                r['activation_stage'] = 3  # long-interval
            elif freq >= 180:
                r['activation_stage'] = 2  # semi/annual
            else:
                r['activation_stage'] = 1  # monthly/quarterly/other
    return rows

def _apply_onboarding_ramp(user_id, rows, today=None, first_seed=False):
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

    # Defaults from global settings
    near_term_days = int(RAMP_SETTINGS.get('near_term_days', 21))
    initial_cap = int(RAMP_SETTINGS.get('initial_cap', 8))
    stagger_weeks = max(1, int(RAMP_SETTINGS.get('stagger_weeks', 8)))

    # Persona- and budget-aware overrides
    try:
        ures = supabase.table('users').select('persona,time_budget_minutes_per_week').eq('id', user_id).execute()
        if ures.data:
            persona = (ures.data[0].get('persona') or '').strip().lower()
            budget = ures.data[0].get('time_budget_minutes_per_week')
            # initial_cap: total immediate tasks allowed (seasonal count too)
            # per_day_cap: immediate tasks to schedule per day during first week
            persona_caps = {
                'buyer':       {'initial_cap': 4, 'per_day_cap': 2, 'stagger_weeks': 12, 'near_term_days': 21},
                'catching_up': {'initial_cap': 6, 'per_day_cap': 3, 'stagger_weeks': 10, 'near_term_days': 21},
                'on_top':      {'initial_cap': 8, 'per_day_cap': 3, 'stagger_weeks': 8,  'near_term_days': 21},
            }
            if persona in persona_caps:
                cfg = persona_caps[persona]
                initial_cap = cfg['initial_cap']
                stagger_weeks = cfg['stagger_weeks']
                near_term_days = cfg['near_term_days']
                per_day_cap = cfg['per_day_cap']
            else:
                per_day_cap = 3
            # Adjust caps by time budget (lighter plan for smaller budgets)
            try:
                b = int(budget) if budget is not None else None
                if b is not None:
                    if b <= 30:
                        initial_cap = max(3, initial_cap - 1)
                        stagger_weeks = max(stagger_weeks, 12)
                        per_day_cap = 2
                    elif b >= 120:
                        initial_cap = min(10, initial_cap + 1)
                        per_day_cap = min(4, per_day_cap + 1)
            except Exception:
                pass
    except Exception:
        per_day_cap = 3

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
        # Identify long-interval tasks for deferral in onboarding
        try:
            freq_days = int(r.get('frequency_days') or 0)
        except Exception:
            freq_days = 0
        score = 0
        if safety:
            score += 100
        if priority == 'high':
            score += 20
        elif priority == 'medium':
            score += 10
        if seasonal and days_out <= near_term_days:
            score += 15
        scored.append((score, days_out, freq_days, r))

    # Sort by score desc, then soonest due
    scored.sort(key=lambda t: (-t[0], t[1]))

    # Keep all safety immediate
    for _, _, freq_days, r in scored:
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

    # Defer long-interval tasks explicitly on first seed
    if first_seed:
        deferred = []
        for r in list(immediate):
            try:
                fd = int(r.get('frequency_days') or 0)
            except Exception:
                fd = 0
            if fd >= 365*2 and not _parse_bool(r.get('safety_critical'), default=False):
                # Push multi-year out by at least 180 days
                r['start_offset_days'] = str(max(_parse_int(r.get('start_offset_days'), default=0) or 0, 180))
                immediate.remove(r)
                deferred.append(r)
        later.extend(deferred)

    # Hard defer on first seed: non-safety tasks with annual or longer frequency should not be day-1
    if first_seed:
        for r in list(later):
            try:
                fd = int(r.get('frequency_days') or 0)
            except Exception:
                fd = 0
            if fd >= 365 and not _parse_bool(r.get('seasonal'), default=False):
                # push out at least ~90 days to avoid day-1 feel
                if _parse_int(r.get('start_offset_days'), default=None) is None:
                    r['start_offset_days'] = '90'

    # Fill remaining immediate up to total cap (seasonal counts too)
    remaining_slots = max(0, initial_cap - len(immediate))
    for _, _, _fd, r in scored:
        if r in immediate:
            continue
        if remaining_slots <= 0:
            break
        # Avoid pulling long-intervals into immediate on first seed
        if first_seed:
            try:
                fd = int(r.get('frequency_days') or 0)
            except Exception:
                fd = 0
            if fd >= 365 and not _parse_bool(r.get('safety_critical'), default=False):
                continue
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

    # Distribute immediate tasks across first week using per-day caps
    if immediate:
        day_cursor = 0
        daily_count = 0
        for r in immediate:
            # Safety stays day 0 but still obey per-day cap by rolling to next day if exceeded
            if daily_count >= per_day_cap:
                day_cursor += 1
                daily_count = 0
            # Only set offset if none
            if _parse_int(r.get('start_offset_days'), default=None) is None:
                r['start_offset_days'] = str( min(6, max(0, day_cursor)) )
            daily_count += 1
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
                # Build a row-like dict and enrich to set defaults similar to catalog flow
                row_like = {
                    'title': title,
                    'description': t.get('description') or None,
                    'frequency_days': freq,
                    'seasonal': t.get('seasonal'),
                    'seasonal_anchor_type': t.get('seasonal_anchor_type'),
                    'season_code': t.get('season_code'),
                    'category': t.get('category'),
                    'priority': t.get('priority'),
                }
                _enrich_task_rows_defaults([row_like])
                next_due = today + timedelta(days=freq)
                to_insert.append({
                    'user_id': user_id,
                    'title': row_like.get('title'),
                    'description': row_like.get('description'),
                    'frequency_days': row_like.get('frequency_days'),
                    'next_due_date': next_due.isoformat(),
                    'is_completed': False,
                    'priority': row_like.get('priority'),
                    'category': row_like.get('category'),
                    'seasonal': bool(row_like.get('seasonal') or False),
                    'seasonal_anchor_type': row_like.get('seasonal_anchor_type'),
                    'season_code': (row_like.get('season_code') or None),
                })
        if to_insert:
            supabase.table('tasks').insert(to_insert).execute()
    except Exception as e:
        print(f"Error backfilling templates: {e}")

def seed_tasks_from_catalog_rows(user_id, features, all_rows):
    """Clear existing tasks and seed from provided catalog rows, filtered & overlap-resolved.
    Applies onboarding ramp on first seed to avoid overwhelming the user.
    Returns a dict with diagnostics: {'considered': int, 'matched': int, 'inserted': int}
    """
    # Determine if we should apply aggressive onboarding ramp
    # Use first seed OR if onboarding_started_at is within the last 14 days
    existing = supabase.table('tasks').select('id').eq('user_id', user_id).execute()
    first_seed = not bool(existing.data)
    ramp_mode = first_seed
    try:
        ures = supabase.table('users').select('onboarding_started_at').eq('id', user_id).execute()
        if ures.data:
            started_raw = ures.data[0].get('onboarding_started_at')
            if started_raw:
                started = datetime.fromisoformat(str(started_raw).replace('Z', '+00:00'))
                account_age_days = (datetime.utcnow() - started).days
                if account_age_days <= 14:
                    ramp_mode = True
            else:
                # No onboarding_started_at yet -> treat as ramp mode
                ramp_mode = True
        else:
            ramp_mode = True
    except Exception:
        ramp_mode = True

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
    considered = len(all_rows or [])
    filtered = _filter_rows_by_features(all_rows, features)
    # During ramp mode, ignore CSV-provided start_offset_days so code drives staggering
    if ramp_mode:
        for r in filtered:
            if 'start_offset_days' in r:
                r['start_offset_days'] = None
    # Add sensible defaults before overlap resolution and ramp
    filtered = _enrich_task_rows_defaults(filtered)
    resolved = _resolve_overlaps(filtered)
    # Apply ramp in ramp_mode (first seed or within onboarding window)
    resolved = _apply_onboarding_ramp(user_id, resolved, today=datetime.now().date(), first_seed=ramp_mode)
    # Safety net: ensure annual+ non-safety tasks are not day-1 during ramp
    if ramp_mode:
        for r in resolved:
            try:
                fd = int(r.get('frequency_days') or 0)
            except Exception:
                fd = 0
            if fd >= 365 and not _parse_bool(r.get('safety_critical'), default=False):
                so = _parse_int(r.get('start_offset_days'), default=None)
                if so is None or so < 90:
                    r['start_offset_days'] = '90'
    before = 0
    try:
        br = supabase.table('tasks').select('id', count='exact').eq('user_id', user_id).execute()
        before = br.count or 0
    except Exception:
        pass
    _insert_tasks_for_user(user_id, resolved)
    after = before
    try:
        ar = supabase.table('tasks').select('id', count='exact').eq('user_id', user_id).execute()
        after = ar.count or before
    except Exception:
        pass
    inserted = max(0, after - before)
    return {'considered': considered, 'matched': len(filtered), 'inserted': inserted}

def seed_tasks_from_static_catalog_or_templates(user_id, features):
    """If a static CSV catalog exists, seed from it; otherwise use TASK_TEMPLATES.
    Returns diagnostics dict: {'source': 'db'|'csv'|'memory', 'considered': int, 'matched': int, 'inserted': int}
    """
    try:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        static_catalog = os.path.join(root_dir, 'static', 'tasks_catalog.csv')
        # Prefer DB templates (public.task_templates)
        # Try to read DB templates; do not assume an 'active' column exists
        try:
            tmpl = supabase.table('task_templates').select('*').execute()
            tmpl_rows = tmpl.data or []
        except Exception as _e:
            tmpl_rows = []

        if tmpl_rows:
            # Map DB templates to the same schema used by CSV seeding
            rows = []
            for r in tmpl_rows:
                rows.append({
                    'task_key': r.get('task_key'),
                    'title': r.get('title'),
                    'description': r.get('description'),
                    'category': r.get('category'),
                    'priority': r.get('priority'),
                    'frequency_days': r.get('frequency_days'),
                    'feature_requirements': r.get('feature_requirements'),
                    'seasonal': r.get('seasonal'),
                    'seasonal_anchor_type': r.get('seasonal_anchor_type'),
                    'season_code': r.get('season_code'),
                    'season_anchor_month': r.get('season_anchor_month'),
                    'season_anchor_day': r.get('season_anchor_day'),
                    'overlap_group': r.get('overlap_group'),
                    'variant_rank': r.get('variant_rank'),
                    'estimated_minutes': r.get('estimated_minutes'),
                })
            diag = seed_tasks_from_catalog_rows(user_id, features, rows)
            diag['source'] = 'db'
            return diag

        # Fallback to CSV if DB has no templates yet
        if os.path.isfile(static_catalog):
            with open(static_catalog, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                rows = [dict(r) for r in reader]
            seed_tasks_from_catalog_rows(user_id, features, rows)
            return True
        else:
            # Fallback to in-memory templates
            all_rows = []
            for feature, enabled in features.items():
                if not enabled:
                    continue
                for t in TASK_TEMPLATES.get(feature, []):
                    all_rows.append(dict(t))
            if all_rows:
                diag = seed_tasks_from_catalog_rows(user_id, features, all_rows)
                diag['source'] = 'memory'
                return diag
            return {'source': 'none', 'considered': 0, 'matched': 0, 'inserted': 0}
    except Exception as e:
        import traceback
        print(f"Error seeding from catalog/templates: {e}")
        traceback.print_exc()
        return {'source': 'error', 'considered': 0, 'matched': 0, 'inserted': 0, 'error': str(e)}

def generate_tasks_for_user(user_id, features):
    try:
        diag = seed_tasks_from_static_catalog_or_templates(user_id, features)
        if (diag or {}).get('inserted', 0) == 0:
            print(f"Seeding produced no inserts. Source={diag.get('source')} considered={diag.get('considered')} matched={diag.get('matched')}")
    except Exception as e:
        print(f"Error generating tasks: {e}")

# --- Estimation helpers ---
def _estimate_minutes(row):
    """Return an estimated_minutes value for a task row if not provided.
    Uses simple heuristics based on priority and category.
    """
    try:
        # Respect explicit value if present and valid
        em = row.get('estimated_minutes')
        if em is not None and str(em).strip() != '':
            v = int(em)
            if v > 0:
                return v
    except Exception:
        pass
    pri = (row.get('priority') or '').strip().lower()
    cat = (row.get('category') or '').strip().lower()
    # Priority baseline
    base = 15
    if pri == 'high':
        base = 45
    elif pri == 'medium':
        base = 30
    else:
        base = 20
    # Category adjustment
    if cat in ('exterior', 'general house checks'):
        base += 10
    if cat in ('appliances', 'interior', 'kitchen'):
        base += 0
    if cat in ('safety', 'logistics'):
        base = max(10, base - 10)
    return base

# -------------------------
# Email Notifications
# -------------------------
def send_overdue_notifications():
    """
    Send email notifications to all users with overdue tasks.
    Can be called manually or via a scheduled job (cron/scheduler).
    """
    try:
        # Get all users
        users_result = supabase.table('users').select('id, username, email').execute()
        users = users_result.data or []
        
        app_url = os.getenv('APP_URL', 'http://localhost:5000')
        sent_count = 0
        
        for user in users:
            user_id = user['id']
            email = user.get('email')
            username = user.get('username', 'there')
            
            if not email:
                continue
            
            # Get overdue tasks for this user
            today = datetime.now().date().isoformat()
            try:
                overdue_result = (supabase.table('tasks')
                                 .select('*')
                                 .eq('user_id', user_id)
                                 .eq('is_completed', False)
                                 .lt('next_due_date', today)
                                 .order('next_due_date')
                                 .execute())
                overdue_tasks = overdue_result.data or []
            except Exception:
                # Fallback without archived column
                overdue_result = (supabase.table('tasks')
                                 .select('*')
                                 .eq('user_id', user_id)
                                 .eq('is_completed', False)
                                 .lt('next_due_date', today)
                                 .order('next_due_date')
                                 .execute())
                overdue_tasks = overdue_result.data or []
            
            if not overdue_tasks:
                continue
            
            # Generate and send email
            try:
                html, text = overdue_tasks_email(username, overdue_tasks, app_url)
                subject = f"🏠 You have {len(overdue_tasks)} overdue task{'s' if len(overdue_tasks) != 1 else ''}"
                send_email(email, subject, html, text)
                sent_count += 1
                print(f"Sent overdue notification to {email} ({len(overdue_tasks)} tasks)")
            except Exception as e:
                print(f"Failed to send email to {email}: {e}")
        
        print(f"Overdue notifications complete: {sent_count} emails sent")
        return sent_count
    except Exception as e:
        print(f"Error in send_overdue_notifications: {e}")
        return 0

def send_weekly_checkin():
    """
    Send weekly home check-in emails to all users.
    Recommended schedule: Saturday mornings at 8am (when people do home tasks).
    """
    try:
        # Get all users
        users_result = supabase.table('users').select('id, username, email').execute()
        users = users_result.data or []
        
        app_url = os.getenv('APP_URL', 'http://localhost:5000')
        sent_count = 0
        today = datetime.now().date()
        week_start = today
        week_end = today + timedelta(days=7)
        month_start = today.replace(day=1)
        
        for user in users:
            user_id = user['id']
            email = user.get('email')
            username = user.get('username', 'there')
            
            if not email:
                continue
            
            try:
                # Get stats for this user
                # Completed this month
                try:
                    completed_result = (supabase.table('tasks')
                                       .select('id', count='exact')
                                       .eq('user_id', user_id)
                                       .eq('is_completed', True)
                                       .gte('last_completed', month_start.isoformat())
                                       .execute())
                    completed_count = completed_result.count or 0
                except Exception:
                    completed_count = 0
                
                # Upcoming this week
                try:
                    upcoming_result = (supabase.table('tasks')
                                      .select('id', count='exact')
                                      .eq('user_id', user_id)
                                      .eq('is_completed', False)
                                      .gte('next_due_date', week_start.isoformat())
                                      .lte('next_due_date', week_end.isoformat())
                                      .execute())
                    upcoming_count = upcoming_result.count or 0
                except Exception:
                    upcoming_count = 0
                
                # Overdue
                try:
                    overdue_result = (supabase.table('tasks')
                                     .select('id', count='exact')
                                     .eq('user_id', user_id)
                                     .eq('is_completed', False)
                                     .lt('next_due_date', today.isoformat())
                                     .execute())
                    overdue_count = overdue_result.count or 0
                except Exception:
                    overdue_count = 0
                
                # Get top tasks for this week (prioritize overdue, then high priority, then soonest)
                try:
                    tasks_result = (supabase.table('tasks')
                                   .select('*')
                                   .eq('user_id', user_id)
                                   .eq('is_completed', False)
                                   .lte('next_due_date', week_end.isoformat())
                                   .order('next_due_date')
                                   .limit(5)
                                   .execute())
                    top_tasks = tasks_result.data or []
                except Exception:
                    top_tasks = []
                
                # Sort tasks: overdue first, then by priority, then by due date
                def task_sort_key(t):
                    due = t.get('next_due_date', '9999-99-99')
                    is_overdue = due < today.isoformat()
                    priority_order = {'high': 0, 'medium': 1, 'low': 2, None: 3, '': 3}
                    pri = priority_order.get((t.get('priority') or '').lower(), 3)
                    return (0 if is_overdue else 1, pri, due)
                
                top_tasks = sorted(top_tasks, key=task_sort_key)[:5]
                
                if not top_tasks and overdue_count == 0 and upcoming_count == 0:
                    # Skip users with no tasks
                    continue
                
                stats = {
                    'completed_this_month': completed_count,
                    'upcoming_this_week': upcoming_count,
                    'overdue_count': overdue_count
                }
                
                # Generate and send email
                html, text = weekly_home_checkin(username, stats, top_tasks, app_url)
                subject = "Your home check-in for the week 🧹"
                send_email(email, subject, html, text)
                sent_count += 1
                print(f"Sent weekly check-in to {email}")
            except Exception as e:
                print(f"Failed to send weekly check-in to {email}: {e}")
        
        print(f"Weekly check-in complete: {sent_count} emails sent")
        return sent_count
    except Exception as e:
        print(f"Error in send_weekly_checkin: {e}")
        return 0

@app.route('/admin/send_notifications', methods=['POST'])
def admin_send_notifications():
    """Manual trigger for sending overdue notifications (admin only)."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    # TODO: Add admin check here if needed
    try:
        count = send_overdue_notifications()
        flash(f'Sent {count} overdue notification emails')
    except Exception as e:
        flash(f'Error sending notifications: {e}')
    
    return redirect(url_for('dashboard'))

@app.route('/debug_env')
def debug_env():
    """Debug: Check if env variables are loaded (REMOVE IN PRODUCTION)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    import os
    env_vars = {
        'SMTP_HOST': os.getenv('SMTP_HOST', 'NOT SET'),
        'SMTP_PORT': os.getenv('SMTP_PORT', 'NOT SET'),
        'SMTP_USER': os.getenv('SMTP_USER', 'NOT SET')[:10] + '...' if os.getenv('SMTP_USER') else 'NOT SET',
        'SMTP_PASS': '***' if os.getenv('SMTP_PASS') else 'NOT SET',
        'FROM_EMAIL': os.getenv('FROM_EMAIL', 'NOT SET'),
        'FROM_NAME': os.getenv('FROM_NAME', 'NOT SET'),
    }
    return f"<pre>{env_vars}</pre>"

@app.route('/test_email')
def test_email():
    """Test weekly check-in email (remove in production)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    try:
        user_result = supabase.table('users').select('username, email').eq('id', user_id).execute()
        if not user_result.data:
            flash('User not found')
            return redirect(url_for('dashboard'))
        
        user = user_result.data[0]
        email = user.get('email')
        username = user.get('username', 'there')
        
        if not email:
            flash('No email address on file')
            return redirect(url_for('dashboard'))
        
        # Get stats for test email
        today = datetime.now().date()
        week_end = today + timedelta(days=7)
        month_start = today.replace(day=1)
        
        # Completed this month
        try:
            completed_result = (supabase.table('tasks')
                               .select('id', count='exact')
                               .eq('user_id', user_id)
                               .eq('is_completed', True)
                               .gte('last_completed', month_start.isoformat())
                               .execute())
            completed_count = completed_result.count or 0
        except Exception:
            completed_count = 0
        
        # Upcoming this week
        try:
            upcoming_result = (supabase.table('tasks')
                              .select('id', count='exact')
                              .eq('user_id', user_id)
                              .eq('is_completed', False)
                              .gte('next_due_date', today.isoformat())
                              .lte('next_due_date', week_end.isoformat())
                              .execute())
            upcoming_count = upcoming_result.count or 0
        except Exception:
            upcoming_count = 0
        
        # Overdue
        try:
            overdue_result = (supabase.table('tasks')
                             .select('id', count='exact')
                             .eq('user_id', user_id)
                             .eq('is_completed', False)
                             .lt('next_due_date', today.isoformat())
                             .execute())
            overdue_count = overdue_result.count or 0
        except Exception:
            overdue_count = 0
        
        # Get top tasks
        try:
            tasks_result = (supabase.table('tasks')
                           .select('*')
                           .eq('user_id', user_id)
                           .eq('is_completed', False)
                           .lte('next_due_date', week_end.isoformat())
                           .order('next_due_date')
                           .limit(5)
                           .execute())
            top_tasks = tasks_result.data or []
        except Exception:
            top_tasks = []
        
        if not top_tasks and overdue_count == 0 and upcoming_count == 0:
            flash('No tasks to show in test email. Create some tasks first!')
            return redirect(url_for('dashboard'))
        
        stats = {
            'completed_this_month': completed_count,
            'upcoming_this_week': upcoming_count,
            'overdue_count': overdue_count
        }
        
        app_url = os.getenv('APP_URL', 'http://localhost:5000')
        html, text = weekly_home_checkin(username, stats, top_tasks, app_url)
        subject = "TEST: Your home check-in for the week 🧹"
        
        send_email(email, subject, html, text)
        flash(f'Test weekly check-in email sent to {email}!')
    except Exception as e:
        flash(f'Error sending test email: {e}')
    
    return redirect(url_for('dashboard'))

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_ENV') != 'production')