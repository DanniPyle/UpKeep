"""Email templates for Keeply Home notifications."""

# Keeply Home logo hosted on Brevo
LOGO_URL = "https://img.mailinblue.com/9919553/images/content_library/original/68e17f9d8976a4ddf55c87fb.png"

def overdue_tasks_email(username: str, tasks: list, app_url: str = "http://localhost:5000") -> tuple[str, str]:
    """
    Generate HTML and text email for overdue tasks notification.
    
    Args:
        username: User's name
        tasks: List of overdue task dicts with keys: id, title, description, next_due_date, priority
        app_url: Base URL of the app
    
    Returns:
        (html_content, text_content)
    """
    task_count = len(tasks)
    
    # Text version
    text = f"""Hi {username},

You have {task_count} overdue task{'s' if task_count != 1 else ''} that need attention:

"""
    for task in tasks[:5]:  # Limit to 5 in email
        text += f"• {task['title']}\n"
        if task.get('description'):
            text += f"  {task['description'][:80]}...\n" if len(task.get('description', '')) > 80 else f"  {task['description']}\n"
        text += f"  Due: {task.get('next_due_date', 'N/A')}\n\n"
    
    if task_count > 5:
        text += f"...and {task_count - 5} more.\n\n"
    
    text += f"View all tasks: {app_url}/dashboard\n\nStay on top of your home maintenance!\n- Keeply Home"
    
    # HTML version
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #2d2f3a;
            background-color: #f2f2f2;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 600px;
            margin: 20px auto;
            background: #ffffff !important;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .header {{
            background: #ffffff !important;
            padding: 24px;
            text-align: center;
            border-bottom: 2px solid #f2f2f2;
        }}
        .header img {{
            max-width: 280px;
            height: auto;
        }}
        .content {{
            padding: 32px 24px;
            background: #ffffff !important;
        }}
        .greeting {{
            font-size: 18px;
            margin-bottom: 16px;
            color: #2d2f3a;
        }}
        .task-list {{
            margin: 24px 0;
        }}
        .task-item {{
            background: #fbf6ef !important;
            border-left: 4px solid #c6453d;
            padding: 16px;
            margin-bottom: 12px;
            border-radius: 4px;
        }}
        .task-item.high {{
            border-left-color: #c6453d;
        }}
        .task-item.medium {{
            border-left-color: #dfae3d;
        }}
        .task-item.low {{
            border-left-color: #9db89d;
        }}
        .task-title {{
            font-weight: 600;
            font-size: 16px;
            margin-bottom: 4px;
            color: #2d2f3a !important;
        }}
        .task-desc {{
            font-size: 14px;
            color: #7a8a94 !important;
            margin-bottom: 8px;
        }}
        .task-meta {{
            font-size: 13px;
            color: #7a8a94 !important;
        }}
        .cta {{
            text-align: center;
            margin: 32px 0;
        }}
        .btn {{
            display: inline-block;
            background: #2f3e56;
            color: #ffffff;
            padding: 12px 32px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
        }}
        .footer {{
            background: #f2f2f2 !important;
            padding: 20px 24px;
            text-align: center;
            font-size: 13px;
            color: #7a8a94 !important;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="{LOGO_URL}" alt="Keeply Home" />
        </div>
        <div class="content">
            <div class="greeting">Hi {username},</div>
            <p>You have <strong>{task_count} overdue task{'s' if task_count != 1 else ''}</strong> that need attention:</p>
            
            <div class="task-list">
"""
    
    for task in tasks[:5]:
        priority = (task.get('priority') or 'low').lower()
        html += f"""
                <div class="task-item {priority}">
                    <div class="task-title">{task['title']}</div>
"""
        if task.get('description'):
            desc = task['description'][:120] + '...' if len(task.get('description', '')) > 120 else task['description']
            html += f'                    <div class="task-desc">{desc}</div>\n'
        
        html += f"""                    <div class="task-meta">Due: {task.get('next_due_date', 'N/A')}</div>
                </div>
"""
    
    if task_count > 5:
        html += f'                <p style="text-align: center; color: #7a8a94;">...and {task_count - 5} more task{"s" if task_count - 5 != 1 else ""}.</p>\n'
    
    html += f"""
            </div>
            
            <div class="cta">
                <a href="{app_url}/dashboard" class="btn">View All Tasks</a>
            </div>
            
            <p style="color: #7a8a94; font-size: 14px;">Stay on top of your home maintenance and keep your home in great shape!</p>
        </div>
        <div class="footer">
            <p>You're receiving this because you have overdue tasks in Keeply Home.</p>
            <p><a href="{app_url}/settings" style="color: #7a8a94;">Manage notification preferences</a></p>
        </div>
    </div>
</body>
</html>
"""
    
    return html, text


def weekly_home_checkin(username: str, stats: dict, top_tasks: list, app_url: str = "http://localhost:5000") -> tuple[str, str]:
    """
    Generate HTML and text email for weekly home check-in.
    
    Args:
        username: User's name
        stats: Dict with keys: completed_this_month, upcoming_this_week, overdue_count
        top_tasks: List of top 3-5 task dicts for this week (with title, next_due_date)
        app_url: Base URL of the app
    
    Returns:
        (html_content, text_content)
    """
    completed = stats.get('completed_this_month', 0)
    upcoming = stats.get('upcoming_this_week', 0)
    overdue = stats.get('overdue_count', 0)
    
    # Text version
    text = f"""Hi {username},

Here's your home's snapshot for the week. See what's in great shape, and what could use a little attention.

🧭 Your Home Health Overview
✅ {completed} tasks completed this month
🔧 {upcoming} upcoming tasks this week
⚠️ {overdue} overdue tasks need a quick look

You're doing great — small steps keep your home happy and healthy.

🗓️ This Week's To-Dos
Here are your top tasks to focus on:

"""
    for task in top_tasks[:5]:
        text += f"• {task['title']} – due {task.get('next_due_date', 'N/A')}\n"
    
    text += f"""
View My Tasks: {app_url}/dashboard

You're taking great care of your home, one step at a time.
Keeply's here to make it easier, not overwhelming.

💛 The Keeply Team"""
    
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #2d2f3a;
            background-color: #f2f2f2;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 600px;
            margin: 20px auto;
            background: #ffffff;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .header {{
            background: #ffffff;
            padding: 24px;
            text-align: center;
            border-bottom: 2px solid #f2f2f2;
        }}
        .header img {{
            max-width: 280px;
            height: auto;
        }}
        .content {{
            padding: 32px 24px;
        }}
        .greeting {{
            font-size: 18px;
            margin-bottom: 8px;
            color: #2d2f3a;
        }}
        .subheading {{
            font-size: 15px;
            color: #7a8a94;
            margin-bottom: 24px;
            line-height: 1.5;
        }}
        .section-title {{
            font-size: 16px;
            font-weight: 600;
            color: #2d2f3a;
            margin: 32px 0 16px 0;
        }}
        .stats-grid {{
            display: table;
            width: 100%;
            margin: 20px 0;
            border-radius: 8px;
            background: #fbf6ef !important;
            padding: 20px;
        }}
        .stat-item {{
            margin-bottom: 12px;
            font-size: 15px;
        }}
        .stat-item:last-child {{
            margin-bottom: 0;
        }}
        .encouragement {{
            font-size: 15px;
            color: #7a8a94;
            font-style: italic;
            margin: 16px 0 24px 0;
        }}
        .task-list {{
            margin: 20px 0;
        }}
        .task-item {{
            display: block;
            padding: 14px 16px;
            margin-bottom: 10px;
            background: #fbf6ef !important;
            border-left: 3px solid #dfae3d;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            text-decoration: none;
            color: inherit;
        }}
        .task-item:hover {{
            background: #f5f0e5 !important;
        }}
        .task-title {{
            font-weight: 600;
            color: #2d2f3a !important;
            margin-bottom: 4px;
        }}
        .task-due {{
            font-size: 13px;
            color: #7a8a94 !important;
        }}
        .cta {{
            text-align: center;
            margin: 32px 0;
        }}
        .btn {{
            display: inline-block;
            background: #2f3e56;
            color: #ffffff;
            padding: 14px 36px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 15px;
        }}
        .footer {{
            background: #f2f2f2 !important;
            padding: 24px;
            text-align: center;
        }}
        .footer-message {{
            font-size: 15px;
            color: #2d2f3a !important;
            margin-bottom: 8px;
            line-height: 1.6;
        }}
        .footer-signature {{
            font-size: 16px;
            color: #2d2f3a !important;
            margin-top: 12px;
        }}
        .footer-links {{
            margin-top: 16px;
            font-size: 13px;
        }}
        .footer-links a {{
            color: #7a8a94;
            text-decoration: none;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="{LOGO_URL}" alt="Keeply Home" />
        </div>
        <div class="content">
            <div class="greeting">Hi {username},</div>
            <div class="subheading">Here's your home's snapshot for the week. See what's in great shape, and what could use a little attention.</div>
            
            <div class="section-title">🧭 Your Home Health Overview</div>
            <div class="stats-grid">
                <div class="stat-item">✅ <strong>{completed}</strong> tasks completed this month</div>
                <div class="stat-item">🔧 <strong>{upcoming}</strong> upcoming tasks this week</div>
                <div class="stat-item">⚠️ <strong>{overdue}</strong> overdue tasks need a quick look</div>
            </div>
            <div class="encouragement">You're doing great — small steps keep your home happy and healthy.</div>
            
            <div class="section-title">🗓️ This Week's To-Dos</div>
            <p style="color: #7a8a94; margin-bottom: 16px;">Here are your top tasks to focus on:</p>
            <div class="task-list">
"""
    
    for task in top_tasks[:5]:
        due_date = task.get('next_due_date', 'N/A')
        task_id = task.get('id', '')
        task_url = f"{app_url}/tasks/{task_id}" if task_id else f"{app_url}/dashboard"
        html += f"""
                <a href="{task_url}" class="task-item">
                    <div class="task-title">{task['title']}</div>
                    <div class="task-due">Due: {due_date}</div>
                </a>
"""
    
    html += f"""
            </div>
            
            <div class="cta">
                <a href="{app_url}/dashboard" class="btn">View My Tasks</a>
            </div>
        </div>
        <div class="footer">
            <div class="footer-message">
                You're taking great care of your home, one step at a time.<br>
                Keeply's here to make it easier, not overwhelming.
            </div>
            <div class="footer-signature">💛 The Keeply Team</div>
            <div class="footer-links">
                <a href="{app_url}/settings">Manage notification preferences</a>
            </div>
        </div>
    </div>
</body>
</html>
"""
    
    return html, text
