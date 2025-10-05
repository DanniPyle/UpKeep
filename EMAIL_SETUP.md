# Email Notifications Setup

## ✅ What's Already Done

- ✅ `mailer.py` configured for Brevo SMTP
- ✅ Email templates created (`email_templates.py`)
- ✅ Notification functions added to `app.py`
- ✅ Test route available

## 🔧 Setup Steps

### 1. Add Environment Variables

Add these to your `.env` file:

```bash
# Brevo SMTP Configuration
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=your-brevo-email@example.com
SMTP_PASS=your-brevo-smtp-key
FROM_EMAIL=noreply@yourdomain.com
FROM_NAME=Keeply Home

# App URL (for email links)
APP_URL=http://localhost:5000  # Change to your production URL
```

**Where to find your Brevo credentials:**
1. Log into Brevo
2. Go to Settings → SMTP & API
3. Copy your SMTP credentials

### 2. Test Email Sending

**Option A: Test Route (Easiest)**

1. Make sure you have at least one overdue task
2. Visit: `http://localhost:5000/test_email`
3. Check your inbox!

**Option B: Python Console**

```python
from mailer import send_email

send_email(
    to_email="your-email@example.com",
    subject="Test from Keeply Home",
    html="<h1>It works!</h1>",
    text="It works!"
)
```

### 3. Schedule Automated Notifications

**Option A: Cron (Linux/Mac)**

```bash
# Make script executable
chmod +x send_notifications.py

# Edit crontab
crontab -e

# Add this line (sends every Saturday at 8am)
0 8 * * 6 cd /path/to/HomeList && /path/to/venv/bin/python send_notifications.py >> /var/log/homelist_notifications.log 2>&1
```

**Cron schedule options:**
- `0 8 * * 6` - Every Saturday at 8am (recommended - weekend home tasks)
- `0 8 * * 0` - Every Sunday at 8am
- `0 8 * * 1` - Every Monday at 8am

**Option B: Manual Trigger**

Visit: `POST /admin/send_notifications` (requires login)

**Option C: APScheduler (Python-based)**

Install: `pip install apscheduler`

Add to `app.py`:

```python
from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()
scheduler.add_job(
    func=send_overdue_notifications,
    trigger="cron",
    hour=8,  # 8am daily
    minute=0
)
scheduler.start()
```

## 📧 Email Types

### 1. Weekly Home Check-In (Primary)
- **Subject**: "Your home check-in for the week 🧹"
- **Frequency**: Weekly (Saturday mornings recommended - weekend home tasks!)
- **Content**: 
  - Home health overview (completed, upcoming, overdue counts)
  - Top 5 tasks for the week
  - Warm, encouraging tone
- **Template**: `weekly_home_checkin()`

### 2. Overdue Tasks Notification (Optional)
- **Trigger**: User has overdue tasks
- **Frequency**: Can be used for urgent reminders
- **Content**: List of overdue tasks with links to dashboard
- **Template**: `overdue_tasks_email()`

## 🎨 Customizing Email Templates

Edit `email_templates.py`:

- **Colors**: Update inline styles (currently uses brand colors)
- **Logo**: Add `<img>` tag in header
- **Content**: Modify HTML/text in functions

## 🔍 Troubleshooting

### "SMTP configuration missing"
- Check `.env` has all SMTP variables
- Restart Flask app after adding variables

### "Authentication failed"
- Verify SMTP_USER and SMTP_PASS are correct
- Check Brevo dashboard for API key status

### "Connection refused"
- Verify SMTP_HOST and SMTP_PORT
- Check firewall settings

### Emails not sending
1. Check Flask console for error messages
2. Verify email addresses exist in `users` table
3. Check Brevo sending limits (free tier has daily limits)

## 📊 Monitoring

Check logs:
```bash
# If using cron
tail -f /var/log/homelist_notifications.log

# If running Flask
# Check Flask console output
```

## 🚀 Production Recommendations

1. **Use a real domain** for `FROM_EMAIL` (improves deliverability)
2. **Set up SPF/DKIM** records in DNS (Brevo provides these)
3. **Monitor bounce rates** in Brevo dashboard
4. **Add unsubscribe link** (required for bulk emails)
5. **Rate limit** notifications (don't spam users)

## 🎯 Next Steps

- [ ] Test email sending with `/test_email`
- [ ] Set up cron job for daily notifications
- [ ] Add notification preferences to user settings
- [ ] Add weekly digest option
- [ ] Track email open rates (Brevo provides this)
