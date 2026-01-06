"""
Web routes for the CHAI Health Publications Tracker.

This file defines all the website pages and handles user actions:
- Home page
- User registration and login
- Preferences management
- Unsubscribe functionality
"""

import re
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user

from .models import db, User, UserProgramPreference, UserRegionPreference
from .config import (
    PROGRAM_AREAS, get_all_program_area_choices, get_all_program_areas_with_subtopics,
    REGIONS_AND_COUNTRIES, get_all_region_choices, FILTER_MODES
)

# Create a blueprint for organizing routes
main_bp = Blueprint('main', __name__)

# Valid digest frequency options
FREQUENCY_OPTIONS = [
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('biweekly', 'Every 2 Weeks'),
    ('monthly', 'Monthly')
]


def is_valid_email(email):
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


@main_bp.route('/')
def index():
    """
    Home page.

    If logged in, redirect to preferences.
    Otherwise, show welcome page with login/register links.
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.preferences'))
    return render_template('index.html')


@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    User registration page.

    GET: Show registration form
    POST: Create new user account
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.preferences'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        errors = []

        if not email:
            errors.append('Email is required.')
        elif not is_valid_email(email):
            errors.append('Please enter a valid email address.')

        if not password:
            errors.append('Password is required.')
        elif len(password) < 8:
            errors.append('Password must be at least 8 characters long.')

        if password != confirm_password:
            errors.append('Passwords do not match.')

        # Check if email already exists
        if User.query.filter_by(email=email).first():
            errors.append('An account with this email already exists.')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('register.html', email=email)

        # Create new user
        user = User(email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Log them in
        login_user(user)
        flash('Account created successfully! Please select your program areas.', 'success')
        return redirect(url_for('main.preferences'))

    return render_template('register.html')


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    User login page.

    GET: Show login form
    POST: Authenticate user
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.preferences'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('This account has been deactivated. Please contact support.', 'error')
                return render_template('login.html', email=email)

            login_user(user)
            flash('Logged in successfully!', 'success')

            # Redirect to next page if specified, otherwise preferences
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('main.preferences'))
        else:
            flash('Invalid email or password.', 'error')
            return render_template('login.html', email=email)

    return render_template('login.html')


@main_bp.route('/logout')
@login_required
def logout():
    """Log out the current user."""
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.index'))


@main_bp.route('/preferences', methods=['GET', 'POST'])
@login_required
def preferences():
    """
    User preferences page.

    GET: Show current preferences with checkboxes for program areas and regions
    POST: Save updated preferences
    """
    if request.method == 'POST':
        # Get selected program areas and subtopics
        # Format: "program_key" for all subtopics, "program_key__subtopic_key" for specific subtopic
        selected_programs = request.form.getlist('programs')

        # Get selected regions
        selected_regions = request.form.getlist('regions')

        # Get filter mode
        filter_mode = request.form.get('filter_mode', 'program_only')
        if filter_mode not in FILTER_MODES:
            filter_mode = 'program_only'

        # Get digest frequency
        frequency = request.form.get('frequency', 'weekly')
        if frequency not in [f[0] for f in FREQUENCY_OPTIONS]:
            frequency = 'weekly'

        # Clear existing program preferences
        UserProgramPreference.query.filter_by(user_id=current_user.id).delete()

        # Save new program preferences with subtopic support
        for selection in selected_programs:
            if '__' in selection:
                # Specific subtopic selected: "program_key__subtopic_key"
                parts = selection.split('__', 1)
                program_key = parts[0]
                subtopic_key = parts[1]
                if program_key in PROGRAM_AREAS:
                    # Verify subtopic exists
                    subtopics = PROGRAM_AREAS[program_key].get('subtopics', {})
                    if subtopic_key in subtopics:
                        pref = UserProgramPreference(
                            user_id=current_user.id,
                            program_area_key=program_key,
                            subtopic_key=subtopic_key
                        )
                        db.session.add(pref)
            else:
                # Entire program area selected (all subtopics)
                program_key = selection
                if program_key in PROGRAM_AREAS:
                    pref = UserProgramPreference(
                        user_id=current_user.id,
                        program_area_key=program_key,
                        subtopic_key=None  # NULL means all subtopics
                    )
                    db.session.add(pref)

        # Clear existing region preferences
        UserRegionPreference.query.filter_by(user_id=current_user.id).delete()

        # Save new region preferences
        for region_key in selected_regions:
            if region_key in REGIONS_AND_COUNTRIES:
                pref = UserRegionPreference(
                    user_id=current_user.id,
                    region_key=region_key
                )
                db.session.add(pref)

        # Update user settings
        current_user.digest_frequency = frequency
        current_user.filter_mode = filter_mode
        db.session.commit()

        flash('Preferences saved successfully!', 'success')
        return redirect(url_for('main.preferences'))

    # GET request - show current preferences
    selected_program_keys = current_user.get_selected_program_keys()
    selected_region_keys = current_user.get_selected_region_keys()
    program_choices = get_all_program_area_choices()
    region_choices = get_all_region_choices()

    # Get program areas with subtopics organized by category
    program_areas_with_subtopics = get_all_program_areas_with_subtopics()

    # Get user's detailed preferences (which subtopics are selected)
    user_program_prefs = current_user.get_program_preferences_detail()

    return render_template(
        'preferences.html',
        program_choices=program_choices,
        selected_program_keys=selected_program_keys,
        region_choices=region_choices,
        selected_region_keys=selected_region_keys,
        filter_modes=FILTER_MODES,
        current_filter_mode=current_user.filter_mode,
        frequency_options=FREQUENCY_OPTIONS,
        current_frequency=current_user.digest_frequency,
        program_areas_with_subtopics=program_areas_with_subtopics,
        user_program_prefs=user_program_prefs
    )


@main_bp.route('/unsubscribe/<token>')
def unsubscribe(token):
    """
    Unsubscribe a user via email link.

    The token is the user's ID encoded (simple implementation).
    In production, use a proper signed token.
    """
    try:
        # Simple token: base64 encoded user ID
        # In production, use itsdangerous or similar for signed tokens
        import base64
        user_id = int(base64.urlsafe_b64decode(token.encode()).decode())
        user = User.query.get(user_id)

        if user:
            user.is_active = False
            db.session.commit()
            flash('You have been unsubscribed from email digests.', 'success')
        else:
            flash('Invalid unsubscribe link.', 'error')

    except (ValueError, TypeError):
        flash('Invalid unsubscribe link.', 'error')

    return render_template('unsubscribe.html')


def generate_unsubscribe_token(user):
    """
    Generate an unsubscribe token for a user.

    Args:
        user: User object

    Returns:
        URL-safe token string
    """
    import base64
    return base64.urlsafe_b64encode(str(user.id).encode()).decode()
