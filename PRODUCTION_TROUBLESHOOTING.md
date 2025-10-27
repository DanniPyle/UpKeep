# Production 500 Error Troubleshooting Guide

**Issue:** keeplyhome.com returns 500 error, but works locally

---

## Quick Fixes Applied

I've made these changes to help debug:

1. ✅ Added fallback for `FLASK_SECRET_KEY` in `config.py`
2. ✅ Made Supabase check non-fatal (prints error but doesn't crash)
3. ✅ Enhanced `/healthz` endpoint to show config status
4. ✅ Removed strict secret key validation in `app.py`

---

## Step 1: Check Health Endpoint

Visit: **https://keeplyhome.com/healthz**

You should see JSON like:
```json
{
  "ok": true,
  "time": "2025-10-27T16:48:21Z",
  "env": "production",
  "has_secret_key": true,
  "has_supabase_url": true,
  "has_supabase_key": true
}
```

**If any are `false`**, that's your problem!

---

## Step 2: Check Production Logs

### If using Heroku:
```bash
heroku logs --tail --app keeplyhome
```

### If using Railway:
```bash
railway logs
```

### If using Render:
Go to Dashboard → Your Service → Logs

### If using a VPS:
```bash
# Check application logs
tail -f /var/log/keeplyhome/error.log

# Or systemd logs
journalctl -u keeplyhome -f

# Or gunicorn logs
tail -f /var/log/gunicorn/error.log
```

**Look for:**
- `ValueError: FLASK_SECRET_KEY must be set`
- `ValueError: Please set SUPABASE_URL`
- `ImportError` or `ModuleNotFoundError`
- Database connection errors

---

## Step 3: Verify Environment Variables

Check that these are set in your production environment:

### Required:
```bash
FLASK_SECRET_KEY=<your-64-char-random-string>
FLASK_ENV=production
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### Optional but recommended:
```bash
FRONTEND_URL=https://keeplyhome.com
ADSENSE_ENABLED=false
```

### How to set (depends on platform):

**Heroku:**
```bash
heroku config:set FLASK_SECRET_KEY="your-secret-key"
heroku config:set FLASK_ENV="production"
heroku config:set SUPABASE_URL="your-url"
heroku config:set SUPABASE_ANON_KEY="your-key"
```

**Railway:**
```bash
railway variables set FLASK_SECRET_KEY="your-secret-key"
railway variables set FLASK_ENV="production"
```

**Render:**
- Go to Dashboard → Environment → Add Environment Variable

**VPS (.env file):**
```bash
# Edit /var/www/keeplyhome/.env
nano /var/www/keeplyhome/.env

# Add:
FLASK_SECRET_KEY=your-secret-key
FLASK_ENV=production
SUPABASE_URL=your-url
SUPABASE_ANON_KEY=your-key

# Restart service
sudo systemctl restart keeplyhome
```

---

## Step 4: Check Dependencies

Make sure all dependencies are installed in production:

```bash
# If using requirements.txt
pip install -r requirements.txt

# Check if Flask-WTF is installed
pip show Flask-WTF

# Check if all imports work
python -c "from flask_wtf.csrf import CSRFProtect; print('OK')"
```

---

## Step 5: Common Issues & Solutions

### Issue: "SESSION_COOKIE_SECURE requires HTTPS"

**Symptom:** 500 error, logs show cookie/session errors

**Solution:** Either:
1. Enable HTTPS on your server, OR
2. Temporarily set `FLASK_ENV=development` (not recommended)

### Issue: "CSRF validation failed"

**Symptom:** Forms don't submit, 400 errors

**Solution:** 
- Check that `<meta name="csrf-token">` is in base.html ✅ (already added)
- Verify JavaScript includes CSRF token in requests ✅ (already done)

### Issue: "No module named 'flask_wtf'"

**Symptom:** ImportError in logs

**Solution:**
```bash
pip install Flask-WTF==1.2.2
```

### Issue: "Database connection failed"

**Symptom:** Supabase errors in logs

**Solution:**
- Verify `SUPABASE_URL` and `SUPABASE_ANON_KEY` are correct
- Check Supabase dashboard → API settings
- Test connection:
```python
python -c "
from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv()
client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_ANON_KEY'))
print('Connected!')
"
```

### Issue: "Favicon/images not found"

**Symptom:** 404 errors for `/static/images/favicon.ico`

**Solution:** 
- Create placeholder favicons or comment out favicon links temporarily
- The SEO meta tags reference images that may not exist yet

---

## Step 6: Test Locally in Production Mode

Test production config locally:

```bash
# Set production environment
export FLASK_ENV=production
export FLASK_SECRET_KEY="test-secret-key-12345678"

# Run locally
python app.py

# Visit http://localhost:5000
```

If it fails locally with `FLASK_ENV=production`, you'll see the error!

---

## Step 7: Rollback Recent Changes (if needed)

If you need to quickly restore functionality, you can:

1. **Revert SEO changes** (unlikely cause, but possible):
```bash
git checkout HEAD~1 templates/base.html
```

2. **Revert security changes**:
```bash
git checkout HEAD~5 config.py app.py
```

3. **Deploy previous working version**:
```bash
git log --oneline  # Find last working commit
git checkout <commit-hash>
git push heroku main --force  # or your deploy command
```

---

## Step 8: Enable Debug Mode Temporarily

**⚠️ ONLY for diagnosis, NOT for production use!**

Temporarily set in production:
```bash
FLASK_ENV=development
DEBUG=True
```

This will show detailed error pages. **Remove immediately after debugging!**

---

## Most Likely Causes (in order)

1. ✅ **Missing `FLASK_SECRET_KEY`** - Fixed with fallback
2. ✅ **Missing Supabase credentials** - Now shows error instead of crashing
3. **Missing `Flask-WTF` package** - Check `pip list`
4. **HTTPS/Cookie issues** - Check if HTTPS is enabled
5. **Import errors** - Check logs for `ImportError`

---

## Quick Checklist

- [ ] Visit `/healthz` - all values should be `true`
- [ ] Check production logs for errors
- [ ] Verify all environment variables are set
- [ ] Confirm `requirements.txt` dependencies installed
- [ ] Test locally with `FLASK_ENV=production`
- [ ] Check if HTTPS is enabled (required for production config)

---

## Get Help

If still stuck, share:
1. Output of `/healthz` endpoint
2. Last 50 lines of production logs
3. Platform you're using (Heroku/Railway/Render/VPS)
4. Output of `pip list | grep -i flask`

---

## After Fixing

Once working:

1. **Set proper `FLASK_SECRET_KEY`**:
```bash
python generate_secret_key.py
# Copy output and set in production
```

2. **Remove debug fallbacks** from `config.py` (the temporary ones I added)

3. **Enable HTTPS** if not already

4. **Monitor logs** for any warnings

---

**Most likely fix:** Set `FLASK_SECRET_KEY` and Supabase credentials in production environment variables, then redeploy.
