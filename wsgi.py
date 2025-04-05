"""
WSGI entry point for Render.com and other production deployments.
This file loads the Flask application with proper initialization.
"""

import os
from app import app as flask_app

# Set environment variables if needed
os.environ.setdefault('FLASK_ENV', 'production')
os.environ.setdefault('USE_AIOREDIS', 'false')  # Explicitly disable aioredis

# For Gunicorn
app = flask_app

if __name__ == "__main__":
    # For running this file directly (not via Gunicorn)
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000))) 