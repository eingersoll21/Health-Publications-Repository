"""
Flask application factory for the CHAI Health Publications Tracker.

This module creates and configures the Flask application instance,
initializes the database, and sets up Flask-Login for user authentication.
"""

from flask import Flask
from flask_login import LoginManager
from .config import Config
from .models import db, User

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.login_view = 'main.login'
login_manager.login_message = 'Please log in to access this page.'


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login session management."""
    return User.query.get(int(user_id))


def create_app(config_class=Config):
    """
    Application factory function.

    Creates and configures a new Flask application instance.

    Args:
        config_class: Configuration class to use (default: Config)

    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app
    db.init_app(app)
    login_manager.init_app(app)

    # Register blueprints (routes)
    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app


def init_db(app):
    """
    Create all database tables if they don't exist.

    Call this function after creating the app to ensure
    the database is ready for use.

    Args:
        app: Flask application instance
    """
    with app.app_context():
        db.create_all()


# Create app instance for gunicorn (gunicorn app:app)
app = create_app()

# Initialize database tables (create if they don't exist)
# This runs once when the app starts
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        import logging
        logging.warning(f"Could not create database tables: {e}")
