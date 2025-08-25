from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'  # Change this in production!

# Database initialization
def init_db():
    conn = sqlite3.connect('home_maintenance.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Home features table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS home_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            has_hvac BOOLEAN DEFAULT 0,
            has_gutters BOOLEAN DEFAULT 0,
            has_dishwasher BOOLEAN DEFAULT 0,
            has_smoke_detectors BOOLEAN DEFAULT 0,
            has_water_heater BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Tasks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            frequency_days INTEGER,
            next_due_date DATE,
            last_completed DATE,
            is_completed BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Helper function to get database connection
def get_db_connection():
    conn = sqlite3.connect('home_maintenance.db')
    conn.row_factory = sqlite3.Row
    return conn

# Task templates based on home features
TASK_TEMPLATES = {
    'has_hvac': [
        {'title': 'Replace HVAC Filter', 'description': 'Replace air filter for better air quality and efficiency', 'frequency_days': 30},
        {'title': 'Schedule HVAC Maintenance', 'description': 'Annual professional HVAC system inspection and cleaning', 'frequency_days': 365}
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
        
        conn = get_db_connection()
        
        # Check if user already exists
        existing_user = conn.execute(
            'SELECT id FROM users WHERE username = ? OR email = ?',
            (username, email)
        ).fetchone()
        
        if existing_user:
            flash('Username or email already exists!')
            conn.close()
            return render_template('register.html')
        
        # Create new user
        password_hash = generate_password_hash(password)
        cursor = conn.execute(
            'INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)',
            (username, email, password_hash)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        session['user_id'] = user_id
        session['username'] = username
        
        flash('Registration successful!')
        return redirect(url_for('questionnaire'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password!')
    
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
        
        # Save home features
        conn = get_db_connection()
        
        # Check if features already exist for this user
        existing = conn.execute(
            'SELECT id FROM home_features WHERE user_id = ?', (user_id,)
        ).fetchone()
        
        features = {
            'has_hvac': 1 if 'has_hvac' in request.form else 0,
            'has_gutters': 1 if 'has_gutters' in request.form else 0,
            'has_dishwasher': 1 if 'has_dishwasher' in request.form else 0,
            'has_smoke_detectors': 1 if 'has_smoke_detectors' in request.form else 0,
            'has_water_heater': 1 if 'has_water_heater' in request.form else 0,
        }
        
        if existing:
            # Update existing features
            conn.execute('''
                UPDATE home_features 
                SET has_hvac=?, has_gutters=?, has_dishwasher=?, has_smoke_detectors=?, has_water_heater=?
                WHERE user_id=?
            ''', (*features.values(), user_id))
        else:
            # Insert new features
            conn.execute('''
                INSERT INTO home_features (user_id, has_hvac, has_gutters, has_dishwasher, has_smoke_detectors, has_water_heater)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, *features.values()))
        
        # Generate tasks based on features
        generate_tasks_for_user(user_id, features, conn)
        
        conn.commit()
        conn.close()
        
        flash('Home features saved and tasks generated!')
        return redirect(url_for('dashboard'))
    
    return render_template('questionnaire.html')

def generate_tasks_for_user(user_id, features, conn):
    # Clear existing tasks for this user
    conn.execute('DELETE FROM tasks WHERE user_id = ?', (user_id,))
    
    # Generate tasks based on features
    for feature, has_feature in features.items():
        if has_feature and feature in TASK_TEMPLATES:
            for task_template in TASK_TEMPLATES[feature]:
                next_due = datetime.now() + timedelta(days=task_template['frequency_days'])
                conn.execute('''
                    INSERT INTO tasks (user_id, title, description, frequency_days, next_due_date)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    user_id,
                    task_template['title'],
                    task_template['description'],
                    task_template['frequency_days'],
                    next_due.date()
                ))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    
    # Get all active tasks (not marked as completed in current cycle)
    tasks = conn.execute('''
        SELECT * FROM tasks 
        WHERE user_id = ? AND is_completed = 0
        ORDER BY next_due_date ASC
    ''', (user_id,)).fetchall()
    
    # Get recently completed tasks
    completed_tasks = conn.execute('''
        SELECT * FROM tasks 
        WHERE user_id = ? AND is_completed = 1
        ORDER BY last_completed DESC
        LIMIT 10
    ''', (user_id,)).fetchall()
    
    conn.close()
    
    # Categorize tasks
    overdue = []
    upcoming = []  # Due within next 30 days
    future = []    # Due beyond 30 days
    today = datetime.now().date()
    next_month = today + timedelta(days=30)
    
    for task in tasks:
        task_date = datetime.strptime(task['next_due_date'], '%Y-%m-%d').date()
        if task_date < today:
            days_overdue = (today - task_date).days
            overdue.append({**dict(task), 'days_overdue': days_overdue})
        elif task_date <= next_month:
            upcoming.append(task)
        else:
            future.append(task)
    
    return render_template('dashboard.html', 
                         overdue_tasks=overdue, 
                         upcoming_tasks=upcoming,
                         future_tasks=future,
                         completed_tasks=completed_tasks)

@app.route('/complete_task/<int:task_id>')
def complete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    
    # Get task details
    task = conn.execute(
        'SELECT * FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id)
    ).fetchone()
    
    if task:
        today = datetime.now().date()
        next_due = today + timedelta(days=task['frequency_days'])
        
        # Update the existing task: mark as completed, set completion date, and update next due date
        conn.execute('''
            UPDATE tasks 
            SET is_completed = 1, 
                last_completed = ?,
                next_due_date = ?
            WHERE id = ?
        ''', (today, next_due, task_id))
        
        conn.commit()
        flash(f'Task "{task["title"]}" completed! Next due: {next_due}')
    
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/reset_task/<int:task_id>')
def reset_task(task_id):
    """Reset a completed task back to active status"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    conn = get_db_connection()
    
    # Get task details
    task = conn.execute(
        'SELECT * FROM tasks WHERE id = ? AND user_id = ?', (task_id, user_id)
    ).fetchone()
    
    if task:
        # Reset the task to active status
        conn.execute('''
            UPDATE tasks 
            SET is_completed = 0,
                last_completed = NULL
            WHERE id = ?
        ''', (task_id,))
        
        conn.commit()
        flash(f'Task "{task["title"]}" has been reset to active status')
    
    conn.close()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)