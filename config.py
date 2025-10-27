"""
Configuration settings for different environments.
"""
import os
from datetime import timedelta

class Config:
    """Base configuration"""
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY')
    if not SECRET_KEY:
        # Temporary fallback - REPLACE THIS IN PRODUCTION
        import sys
        print("WARNING: FLASK_SECRET_KEY not set! Using fallback.", file=sys.stderr)
        SECRET_KEY = 'temporary-fallback-key-CHANGE-THIS'
    
    # Session configuration
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # No time limit for CSRF tokens
    WTF_CSRF_SSL_STRICT = False  # Allow CSRF over HTTP in development
    
    # Supabase
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_ANON_KEY')

class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SESSION_COOKIE_SECURE = False  # Allow HTTP in development
    SESSION_COOKIE_NAME = 'session'  # Standard name for dev

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SESSION_COOKIE_SECURE = True  # Require HTTPS
    SESSION_COOKIE_NAME = '__Host-session'  # Security prefix
    WTF_CSRF_SSL_STRICT = True  # Enforce HTTPS for CSRF in production
    
    # Additional production settings
    TESTING = False

class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False  # Disable CSRF for testing

# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
