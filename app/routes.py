"""
Web routes for the CHAI Health Publications Tracker.

This file defines all the website pages and handles user actions:
- Home page
- Browse/Search publications
- User registration and login
- Preferences management
- Unsubscribe functionality
"""

import re
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_, and_, func

from .models import (
    db, User, UserProgramPreference, UserProgramPreferenceLocation, UserCountryWatch,
    Publication, PublicationProgramArea, PublicationSubtopic, PublicationRegion
)
from .config import (
    PROGRAM_AREAS, get_all_program_area_choices, get_all_program_areas_with_subtopics,
    REGIONS_AND_COUNTRIES, get_all_region_choices, get_all_country_choices,
    get_program_area_name, get_region_name, get_subtopic_name
)


def get_countries_by_region():
    """Get a dict mapping region keys to lists of countries in that region."""
    countries_by_region = {}
    for region_key, region_data in REGIONS_AND_COUNTRIES.items():
        if region_key != 'global':
            countries_by_region[region_key] = sorted(region_data.get('countries', []))
    return countries_by_region

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

    If logged in, redirect to browse page.
    Otherwise, show welcome page with login/register links.
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.browse'))
    return render_template('index.html')


# Date range presets for browse page
DATE_RANGE_PRESETS = [
    ('30', 'Last 30 days'),
    ('90', 'Last 3 months'),
    ('180', 'Last 6 months'),
    ('365', 'Last 1 year'),
    ('1095', 'Last 3 years'),
    ('custom', 'Custom range')
]

# Results per page
RESULTS_PER_PAGE = 20


@main_bp.route('/browse')
@login_required
def browse():
    """
    Browse/Search publications page.

    Allows users to explore the publication database with filters:
    - Program area and subtopic
    - Region and country
    - Source (WHO/PubMed)
    - Date range
    - Text search
    """
    # Get filter parameters from query string
    program = request.args.get('program', '')
    subtopic = request.args.get('subtopic', '')
    region = request.args.get('region', '')
    country = request.args.get('country', '')
    source = request.args.get('source', '')
    date_range = request.args.get('date_range', '30')  # Default: last 30 days
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    search = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)

    # Build base query
    query = db.session.query(Publication)

    # Apply text search filter (title or abstract)
    if search:
        search_term = f'%{search}%'
        query = query.filter(
            or_(
                Publication.title.ilike(search_term),
                Publication.abstract.ilike(search_term)
            )
        )

    # Apply program area filter
    if program:
        pub_ids_with_program = db.session.query(PublicationProgramArea.publication_id).filter(
            PublicationProgramArea.program_area_key == program
        ).scalar_subquery()
        query = query.filter(Publication.id.in_(pub_ids_with_program))

    # Apply subtopic filter
    if subtopic and program:
        pub_ids_with_subtopic = db.session.query(PublicationSubtopic.publication_id).filter(
            PublicationSubtopic.program_area_key == program,
            PublicationSubtopic.subtopic_key == subtopic
        ).scalar_subquery()
        query = query.filter(Publication.id.in_(pub_ids_with_subtopic))

    # Apply region filter
    if region:
        pub_ids_with_region = db.session.query(PublicationRegion.publication_id).filter(
            PublicationRegion.region_key == region
        ).scalar_subquery()
        query = query.filter(Publication.id.in_(pub_ids_with_region))

    # Apply country filter (search in matched_terms)
    if country:
        pub_ids_with_country = db.session.query(PublicationRegion.publication_id).filter(
            PublicationRegion.matched_terms.ilike(f'%{country}%')
        ).scalar_subquery()
        query = query.filter(Publication.id.in_(pub_ids_with_country))

    # Apply source filter
    if source:
        query = query.filter(Publication.source == source)

    # Apply date range filter
    if date_range == 'custom':
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                query = query.filter(Publication.publication_date >= from_date)
            except ValueError:
                pass
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                query = query.filter(Publication.publication_date <= to_date)
            except ValueError:
                pass
    elif date_range:
        try:
            days = int(date_range)
            cutoff_date = datetime.utcnow().date() - timedelta(days=days)
            query = query.filter(Publication.publication_date >= cutoff_date)
        except ValueError:
            pass

    # Order by publication date (newest first)
    query = query.order_by(Publication.publication_date.desc())

    # Get total count before pagination
    total_count = query.count()

    # Paginate
    pagination = query.paginate(page=page, per_page=RESULTS_PER_PAGE, error_out=False)
    publications = pagination.items

    # Format publications for display
    formatted_pubs = []
    for pub in publications:
        # Get program areas
        areas = PublicationProgramArea.query.filter_by(publication_id=pub.id).all()
        program_areas = [get_program_area_name(a.program_area_key) for a in areas]

        # Get subtopics
        subtopics = PublicationSubtopic.query.filter_by(publication_id=pub.id).all()
        subtopic_names = [get_subtopic_name(st.program_area_key, st.subtopic_key) for st in subtopics]

        # Get regions
        regions = PublicationRegion.query.filter_by(publication_id=pub.id).all()
        region_names = [get_region_name(r.region_key) for r in regions]

        # Truncate abstract
        abstract_preview = pub.abstract[:200] + '...' if pub.abstract and len(pub.abstract) > 200 else pub.abstract

        formatted_pubs.append({
            'id': pub.id,
            'title': pub.title,
            'url': pub.url,
            'source': pub.source,
            'date': pub.publication_date,
            'abstract': abstract_preview,
            'program_areas': program_areas,
            'subtopics': subtopic_names,
            'regions': region_names,
            'is_ahead_of_print': pub.is_ahead_of_print
        })

    # Get database date range for info message
    earliest_pub = Publication.query.filter(Publication.publication_date.isnot(None)).order_by(Publication.publication_date.asc()).first()
    latest_pub = Publication.query.filter(Publication.publication_date.isnot(None)).order_by(Publication.publication_date.desc()).first()
    db_date_range = None
    if earliest_pub and latest_pub and earliest_pub.publication_date and latest_pub.publication_date:
        db_date_range = {
            'earliest': earliest_pub.publication_date,
            'latest': latest_pub.publication_date
        }

    # Get filter options
    program_choices = get_all_program_area_choices()
    program_areas_with_subtopics = get_all_program_areas_with_subtopics()
    region_choices = get_all_region_choices()
    country_choices = get_all_country_choices()
    countries_by_region = get_countries_by_region()

    return render_template(
        'browse.html',
        publications=formatted_pubs,
        pagination=pagination,
        total_count=total_count,
        # Current filter values
        current_program=program,
        current_subtopic=subtopic,
        current_region=region,
        current_country=country,
        current_source=source,
        current_date_range=date_range,
        current_date_from=date_from,
        current_date_to=date_to,
        current_search=search,
        # Filter options
        program_choices=program_choices,
        program_areas_with_subtopics=program_areas_with_subtopics,
        region_choices=region_choices,
        country_choices=country_choices,
        countries_by_region=countries_by_region,
        date_range_presets=DATE_RANGE_PRESETS,
        db_date_range=db_date_range
    )


@main_bp.route('/api/subtopics/<program_key>')
@login_required
def get_subtopics(program_key):
    """API endpoint to get subtopics for a program area (for dynamic dropdown)."""
    if program_key in PROGRAM_AREAS:
        subtopics = PROGRAM_AREAS[program_key].get('subtopics', {})
        return jsonify([
            {'key': key, 'name': data['name']}
            for key, data in subtopics.items()
        ])
    return jsonify([])


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
            return redirect(url_for('main.browse'))
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
    User preferences page with two subscription types:

    1. Program Subscriptions: Subscribe to health topics with optional multi-location filter
    2. Country Watch: Get ALL publications about specific countries/regions

    GET: Show current preferences
    POST: Save updated preferences
    """
    if request.method == 'POST':
        # ========== Section 1: Program Subscriptions ==========
        # Format: "program_key" for all subtopics, "program_key__subtopic_key" for specific subtopic
        selected_programs = request.form.getlist('programs')

        # ========== Section 2: Country Watch ==========
        selected_watch_regions = request.form.getlist('watch_regions')
        selected_watch_countries = request.form.getlist('watch_countries')

        # ========== Digest Settings ==========
        frequency = request.form.get('frequency', 'weekly')
        if frequency not in [f[0] for f in FREQUENCY_OPTIONS]:
            frequency = 'weekly'

        # Clear existing program preferences (must delete individually to trigger cascade)
        existing_prefs = UserProgramPreference.query.filter_by(user_id=current_user.id).all()
        for pref in existing_prefs:
            db.session.delete(pref)
        db.session.flush()  # Ensure deletes are applied before inserting new prefs

        # Track which programs we've created preferences for
        created_prefs = {}  # {program_key: UserProgramPreference}

        # Save new program preferences with subtopic support
        for selection in selected_programs:
            if '__' in selection:
                # Specific subtopic selected: "program_key__subtopic_key"
                parts = selection.split('__', 1)
                program_key = parts[0]
                subtopic_key = parts[1]
                if program_key in PROGRAM_AREAS:
                    subtopics = PROGRAM_AREAS[program_key].get('subtopics', {})
                    if subtopic_key in subtopics:
                        pref = UserProgramPreference(
                            user_id=current_user.id,
                            program_area_key=program_key,
                            subtopic_key=subtopic_key
                        )
                        db.session.add(pref)
                        db.session.flush()  # Get the ID
                        created_prefs[f"{program_key}__{subtopic_key}"] = pref
            else:
                # Entire program area selected (all subtopics)
                program_key = selection
                if program_key in PROGRAM_AREAS:
                    pref = UserProgramPreference(
                        user_id=current_user.id,
                        program_area_key=program_key,
                        subtopic_key=None
                    )
                    db.session.add(pref)
                    db.session.flush()  # Get the ID
                    created_prefs[program_key] = pref

        # Now handle location filters for each program
        all_countries = get_all_country_choices()
        added_locations = set()  # Track (pref_id, location_type, location_value) to prevent duplicates
        for program_key in PROGRAM_AREAS.keys():
            location_type = request.form.get(f'{program_key}__location_type', 'all')
            locations = list(set(request.form.getlist(f'{program_key}__locations')))  # Deduplicate

            if location_type != 'all' and locations:
                # Find all preferences for this program
                for pref_key, pref in created_prefs.items():
                    if pref.program_area_key == program_key:
                        # Add location filters
                        for loc_value in locations:
                            loc_key = (pref.id, location_type, loc_value)
                            if loc_key in added_locations:
                                continue  # Skip duplicate
                            # Validate location value
                            if location_type == 'region' and loc_value in REGIONS_AND_COUNTRIES:
                                loc = UserProgramPreferenceLocation(
                                    program_preference_id=pref.id,
                                    location_type='region',
                                    location_value=loc_value
                                )
                                db.session.add(loc)
                                added_locations.add(loc_key)
                            elif location_type == 'country' and loc_value in all_countries:
                                loc = UserProgramPreferenceLocation(
                                    program_preference_id=pref.id,
                                    location_type='country',
                                    location_value=loc_value
                                )
                                db.session.add(loc)
                                added_locations.add(loc_key)

        # Clear existing country watches (must delete individually to be consistent)
        existing_watches = UserCountryWatch.query.filter_by(user_id=current_user.id).all()
        for watch in existing_watches:
            db.session.delete(watch)

        # Save new country watches - entire regions
        for region_key in selected_watch_regions:
            if region_key in REGIONS_AND_COUNTRIES and region_key != 'global':
                watch = UserCountryWatch(
                    user_id=current_user.id,
                    region_key=region_key,
                    country_name=None
                )
                db.session.add(watch)

        # Save new country watches - specific countries
        for country_name in selected_watch_countries:
            if country_name in all_countries:
                watch = UserCountryWatch(
                    user_id=current_user.id,
                    region_key=None,
                    country_name=country_name
                )
                db.session.add(watch)

        # Update user settings
        current_user.digest_frequency = frequency
        db.session.commit()

        flash('Preferences saved successfully!', 'success')
        return redirect(url_for('main.preferences'))

    # GET request - show current preferences
    program_choices = get_all_program_area_choices()
    region_choices = get_all_region_choices()
    country_choices = get_all_country_choices()
    countries_by_region = get_countries_by_region()

    # Get program areas with subtopics organized by category
    program_areas_with_subtopics = get_all_program_areas_with_subtopics()

    # Get user's detailed preferences (which subtopics and location filters are selected)
    user_program_prefs = current_user.get_program_preferences_detail()

    # Get user's country watches
    user_country_watches = current_user.get_country_watches()
    selected_watch_regions = [w['region_key'] for w in user_country_watches if w['region_key'] and not w['country_name']]
    selected_watch_countries = [w['country_name'] for w in user_country_watches if w['country_name']]

    return render_template(
        'preferences.html',
        program_choices=program_choices,
        region_choices=region_choices,
        country_choices=country_choices,
        countries_by_region=countries_by_region,
        frequency_options=FREQUENCY_OPTIONS,
        current_frequency=current_user.digest_frequency,
        program_areas_with_subtopics=program_areas_with_subtopics,
        user_program_prefs=user_program_prefs,
        selected_watch_regions=selected_watch_regions,
        selected_watch_countries=selected_watch_countries
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
