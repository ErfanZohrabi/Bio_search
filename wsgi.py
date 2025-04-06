"""
WSGI entry point for Render.com and other production deployments.
This file loads the Flask application with proper initialization.
"""

import os
import logging
import sys

# Configure logging before importing the app
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Set environment variables for production
os.environ.setdefault('FLASK_ENV', 'production')
os.environ.setdefault('USE_AIOREDIS', 'false')  # Explicitly disable aioredis
os.environ.setdefault('BIOSEARCH_LOG_LEVEL', 'INFO')

# Log startup information
logger = logging.getLogger('wsgi')
logger.info("Starting BioSearch application in production mode")
logger.info(f"Python version: {sys.version}")
logger.info(f"Current working directory: {os.getcwd()}")

# Import the Flask app
from app import app as flask_app

# For Gunicorn
app = flask_app

# Log configuration
logger.info("Application initialized successfully")
logger.info(f"FLASK_ENV: {os.environ.get('FLASK_ENV')}")
logger.info(f"USE_AIOREDIS: {os.environ.get('USE_AIOREDIS')}")
logger.info(f"BIOSEARCH_MOCK_MODE: {os.environ.get('BIOSEARCH_MOCK_MODE', 'false')}")

if __name__ == "__main__":
    # For running this file directly (not via Gunicorn)
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting development server on port {port}")
    flask_app.run(host='0.0.0.0', port=port) 