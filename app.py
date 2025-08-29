from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client
from datetime import datetime, timedelta
import os
import jwt
from functools import wraps
from dotenv import load_dotenv

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
        # Clear existing tasks for this user
        supabase.table('tasks').delete().eq('user_id', user_id).execute()
        
        # Generate tasks based on features
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
                        'is_completed': False
                    })
        
        if tasks_to_insert:
            supabase.table('tasks').insert(tasks_to_insert).execute()
            
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
        
        # Get all active tasks
        tasks_result = supabase.table('tasks').select('*').eq('user_id', current_user_id).eq('is_completed', False).order('next_due_date').execute()
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
            'is_completed': False
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
            'frequency_days': frequency_days
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