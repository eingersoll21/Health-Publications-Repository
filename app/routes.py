"""
Web routes for the Global Health Publications Tracker.

This file defines all the website pages and handles user actions:
- Home/Dashboard page
- Browse/Search publications
- User registration and login
- Preferences management
- Suggestions/Feedback
- Unsubscribe functionality
"""

import re
import secrets
from datetime import datetime, timedelta, time
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_, and_, func

from .models import (
    db, User, UserProgramPreference, UserProgramPreferenceLocation, UserCountryWatch,
    Publication, PublicationProgramArea, PublicationSubtopic, PublicationRegion,
    DigestLog, ScraperLog, UserSuggestion, ReadingFolder, SavedPublication
)
from .config import (
    PROGRAM_AREAS, get_all_program_area_choices, get_all_program_areas_with_subtopics,
    get_program_subtopics_for_dropdown,
    REGIONS_AND_COUNTRIES, get_all_region_choices, get_all_country_choices,
    get_program_area_name, get_region_name, get_subtopic_name
)
from .services.publication_queries import (
    get_matching_publications, get_publication_counts_by_program, get_user_preference_structure
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
    Landing page.

    If logged in, redirect to home dashboard.
    Otherwise, show welcome page with login/register links.
    """
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))
    return render_template('index.html')


@main_bp.route('/home')
@login_required
def home():
    """
    Home dashboard page for logged-in users.

    Shows subscription summary, new publications count, database stats,
    recent matching publications, and topics at a glance.
    """
    # Get user's subscription counts
    program_subscription_count = current_user.program_preferences.count()
    country_watch_count = current_user.country_watches.count()

    # Get user's preference structure (for checking if they have subscriptions)
    prefs_by_program = get_user_preference_structure(current_user)
    user_program_keys = list(prefs_by_program.keys())

    # Count new publications since last digest (using correct subtopic-aware filtering)
    new_publications_count = 0
    if current_user.last_digest_sent and prefs_by_program:
        # Use the shared helper to get accurate count
        days_since_digest = (datetime.utcnow() - current_user.last_digest_sent).days
        matching_pubs = get_matching_publications(
            current_user,
            days_back=max(days_since_digest, 1),
            max_publications=100,  # Just for counting
            exclude_sent=False
        )
        # Filter to only those scraped after last digest
        new_publications_count = sum(
            1 for p in matching_pubs
            if p['publication'].scraped_at > current_user.last_digest_sent
        )

    # Get database stats
    total_publications = Publication.query.count()
    who_count = Publication.query.filter_by(source='WHO').count()
    pubmed_count = Publication.query.filter_by(source='PubMed').count()

    # Get date range
    earliest_pub = Publication.query.filter(
        Publication.publication_date.isnot(None)
    ).order_by(Publication.publication_date.asc()).first()
    latest_pub = Publication.query.filter(
        Publication.publication_date.isnot(None)
    ).order_by(Publication.publication_date.desc()).first()

    date_range = None
    if earliest_pub and latest_pub:
        date_range = {
            'earliest': earliest_pub.publication_date,
            'latest': latest_pub.publication_date
        }

    # Get last scraper run
    last_scraper_run = ScraperLog.query.order_by(ScraperLog.run_at.desc()).first()

    # Calculate next digest info
    next_digest_info = _calculate_next_digest_info(current_user)

    # === Get recent publications matching user's topics (last 7 days) ===
    # Uses CORRECT subtopic-aware filtering via shared helper
    recent_matching_publications = []
    recent_matching_count = 0

    if prefs_by_program:
        # Get all matching publications from last 7 days (for count)
        all_matching = get_matching_publications(
            current_user,
            days_back=7,
            max_publications=100,
            exclude_sent=False
        )
        recent_matching_count = len(all_matching)

        # Get top 6 for display
        matching_pubs = get_matching_publications(
            current_user,
            days_back=7,
            max_publications=6,
            exclude_sent=False
        )

        # Format for template - include subtopics
        for pub_data in matching_pubs:
            primary_program = pub_data['program_areas'][0] if pub_data['program_areas'] else None
            recent_matching_publications.append({
                'publication': pub_data['publication'],
                'primary_program_key': primary_program['key'] if primary_program else None,
                'primary_program_name': primary_program['name'] if primary_program else None,
                'subtopics': pub_data.get('subtopics', []),  # Include subtopics
                'program_areas': pub_data.get('program_areas', [])  # Include all program areas
            })

    # === Get publication counts by subscribed program area ===
    program_counts = get_publication_counts_by_program(current_user)

    # === Get user's subscribed regions/countries ===
    user_country_watches = []
    for watch in current_user.country_watches:
        if watch.country_name:
            user_country_watches.append(watch.country_name)
        elif watch.region_key:
            user_country_watches.append(get_region_name(watch.region_key))

    # === Get reading list stats ===
    reading_list_total = current_user.saved_publications.count()
    reading_list_unread = current_user.saved_publications.filter_by(is_read=False).count()
    reading_list_folders = []
    for folder in current_user.reading_folders.order_by(ReadingFolder.name).limit(3):
        reading_list_folders.append({
            'name': folder.name,
            'count': folder.saved_publications.count()
        })

    return render_template(
        'home.html',
        program_subscription_count=program_subscription_count,
        country_watch_count=country_watch_count,
        new_publications_count=new_publications_count,
        total_publications=total_publications,
        who_count=who_count,
        pubmed_count=pubmed_count,
        date_range=date_range,
        last_scraper_run=last_scraper_run,
        next_digest_info=next_digest_info,
        recent_matching_publications=recent_matching_publications,
        recent_matching_count=recent_matching_count,
        program_counts=program_counts,
        user_program_keys=user_program_keys,
        user_country_watches=user_country_watches,
        reading_list_total=reading_list_total,
        reading_list_unread=reading_list_unread,
        reading_list_folders=reading_list_folders
    )


def _calculate_next_digest_info(user):
    """
    Calculate when the user's next digest will be sent.

    Returns dict with: day_name, date_str, time_str, timezone_str
    """
    from datetime import datetime
    import calendar

    frequency = user.digest_frequency
    preferred_day = user.preferred_day
    preferred_time = user.preferred_time or time(8, 0)
    timezone_str = user.timezone or 'UTC'

    # Format the time
    hour = preferred_time.hour
    am_pm = 'AM' if hour < 12 else 'PM'
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12
    time_str = f"{display_hour}:00 {am_pm}"

    # Get timezone display name
    timezone_display = _get_timezone_display_name(timezone_str)

    if frequency == 'daily':
        return {
            'frequency': 'Daily',
            'schedule_text': f"Every day at {time_str}",
            'timezone': timezone_display
        }
    elif frequency == 'weekly':
        day_name = (preferred_day or 'monday').capitalize()
        return {
            'frequency': 'Weekly',
            'schedule_text': f"Every {day_name} at {time_str}",
            'timezone': timezone_display
        }
    elif frequency == 'biweekly':
        day_name = (preferred_day or 'monday').capitalize()
        return {
            'frequency': 'Biweekly',
            'schedule_text': f"Every other {day_name} at {time_str}",
            'timezone': timezone_display
        }
    elif frequency == 'monthly':
        day_num = preferred_day or '1'
        day_suffix = 'st' if day_num == '1' else 'th'
        return {
            'frequency': 'Monthly',
            'schedule_text': f"On the {day_num}{day_suffix} at {time_str}",
            'timezone': timezone_display
        }

    return None


def _get_timezone_display_name(tz_str):
    """Get a friendly display name for a timezone."""
    tz_names = {
        'UTC': 'UTC',
        'America/New_York': 'Eastern Time',
        'America/Chicago': 'Central Time',
        'America/Denver': 'Mountain Time',
        'America/Los_Angeles': 'Pacific Time',
        'America/Sao_Paulo': 'Brasilia Time',
        'Europe/London': 'London',
        'Europe/Paris': 'Paris',
        'Europe/Berlin': 'Berlin',
        'Africa/Johannesburg': 'Johannesburg',
        'Africa/Nairobi': 'Nairobi',
        'Asia/Dubai': 'Dubai',
        'Asia/Kolkata': 'India',
        'Asia/Bangkok': 'Bangkok',
        'Asia/Singapore': 'Singapore',
        'Asia/Tokyo': 'Tokyo',
        'Australia/Sydney': 'Sydney',
    }
    return tz_names.get(tz_str, tz_str)


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
    program_subtopics_dropdown = get_program_subtopics_for_dropdown()
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
        program_subtopics_dropdown=program_subtopics_dropdown,
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
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        errors = []

        if not first_name:
            errors.append('First name is required.')

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
            return render_template('register.html', email=email, first_name=first_name, last_name=last_name)

        # Create new user
        user = User(email=email, first_name=first_name, last_name=last_name or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Send welcome email (don't block registration if email fails)
        try:
            from app.services.email_service import send_welcome_email
            send_welcome_email(user)
        except Exception as e:
            # Log error but don't fail registration
            import logging
            logging.getLogger(__name__).error(f"Failed to send welcome email: {e}")

        # Log them in
        login_user(user)
        flash('Account created successfully! Please set up your subscriptions.', 'success')
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
            return redirect(url_for('main.home'))
        else:
            flash('Invalid email or password.', 'error')
            return render_template('login.html', email=email)

    return render_template('login.html')


@main_bp.route('/send-test-digest')
@login_required
def send_test_digest():
    """
    Send a test digest to the current user.

    This is a placeholder that will be implemented later.
    For now, it just shows a flash message.
    """
    # TODO: Implement actual test digest sending
    flash('Test digest feature coming soon! We will send a sample digest to your email.', 'info')
    return redirect(url_for('main.home'))


@main_bp.route('/suggestions', methods=['GET', 'POST'])
@login_required
def suggestions():
    """
    Suggestions and feedback page.

    GET: Show suggestion form and user's past suggestions
    POST: Submit a new suggestion
    """
    # Define suggestion types
    suggestion_types = [
        ('new_data_source', 'Suggest a new data source'),
        ('feature_request', 'Request a feature'),
        ('bug_report', 'Report a bug'),
        ('other', 'Other feedback')
    ]

    if request.method == 'POST':
        suggestion_type = request.form.get('suggestion_type', '').strip()
        description = request.form.get('description', '').strip()

        # Validation
        errors = []
        if not suggestion_type:
            errors.append('Please select a suggestion type.')
        if not description:
            errors.append('Please enter your suggestion.')
        elif len(description) < 10:
            errors.append('Please provide more detail (at least 10 characters).')

        if errors:
            for error in errors:
                flash(error, 'error')
        else:
            # Save suggestion
            suggestion = UserSuggestion(
                user_id=current_user.id,
                suggestion_type=suggestion_type,
                description=description
            )
            db.session.add(suggestion)
            db.session.commit()
            flash('Thank you for your feedback! We appreciate your input.', 'success')
            return redirect(url_for('main.suggestions'))

    # Get user's past suggestions
    user_suggestions = UserSuggestion.query.filter_by(
        user_id=current_user.id
    ).order_by(UserSuggestion.submitted_at.desc()).all()

    return render_template(
        'suggestions.html',
        suggestion_types=suggestion_types,
        user_suggestions=user_suggestions
    )


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

        # ========== Delivery Timing ==========
        preferred_day = request.form.get('preferred_day', '')
        preferred_time_str = request.form.get('preferred_time', '08:00')
        timezone = request.form.get('timezone', 'UTC')

        # Parse preferred time
        preferred_time = None
        if preferred_time_str:
            try:
                hours, minutes = map(int, preferred_time_str.split(':'))
                preferred_time = time(hours, minutes)
            except (ValueError, AttributeError):
                preferred_time = time(8, 0)  # Default to 8:00 AM

        # Validate preferred_day based on frequency
        if frequency == 'daily':
            preferred_day = None
        elif frequency in ('weekly', 'biweekly'):
            valid_days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            if preferred_day not in valid_days:
                preferred_day = 'monday'
        elif frequency == 'monthly':
            if preferred_day not in ('1', '15'):
                preferred_day = '1'

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
        current_user.preferred_day = preferred_day
        current_user.preferred_time = preferred_time
        current_user.timezone = timezone
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

    # Get current timing preferences
    current_preferred_time = current_user.preferred_time.strftime('%H:%M') if current_user.preferred_time else '08:00'

    return render_template(
        'preferences.html',
        program_choices=program_choices,
        region_choices=region_choices,
        country_choices=country_choices,
        countries_by_region=countries_by_region,
        frequency_options=FREQUENCY_OPTIONS,
        current_frequency=current_user.digest_frequency,
        current_preferred_day=current_user.preferred_day or '',
        current_preferred_time=current_preferred_time,
        current_timezone=current_user.timezone or 'UTC',
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


# ============================================================================
# READING LIST FEATURE
# ============================================================================

@main_bp.route('/reading-list')
@login_required
def reading_list():
    """
    Reading list page where users can view and manage saved publications.

    Shows folders in sidebar and publications in main area with filtering
    and sorting options.
    """
    # Get current folder filter from query params
    folder_filter = request.args.get('folder', 'all')  # 'all', 'unfiled', or folder_id
    read_filter = request.args.get('read', 'all')  # 'all', 'read', 'unread'
    sort_by = request.args.get('sort', 'saved_at')  # 'saved_at', 'publication_date', 'title'

    # Get user's folders with counts
    folders = []
    for folder in current_user.reading_folders.order_by(ReadingFolder.name):
        folders.append({
            'id': folder.id,
            'name': folder.name,
            'description': folder.description,
            'count': folder.saved_publications.count()
        })

    # Get total and unfiled counts
    total_saved = current_user.saved_publications.count()
    unfiled_count = current_user.saved_publications.filter_by(folder_id=None).count()
    unread_count = current_user.saved_publications.filter_by(is_read=False).count()

    # Build query for publications
    query = current_user.saved_publications

    # Apply folder filter
    if folder_filter == 'unfiled':
        query = query.filter_by(folder_id=None)
    elif folder_filter != 'all':
        try:
            folder_id = int(folder_filter)
            query = query.filter_by(folder_id=folder_id)
        except ValueError:
            pass

    # Apply read filter
    if read_filter == 'read':
        query = query.filter_by(is_read=True)
    elif read_filter == 'unread':
        query = query.filter_by(is_read=False)

    # Apply sorting
    if sort_by == 'publication_date':
        query = query.join(Publication).order_by(Publication.publication_date.desc())
    elif sort_by == 'title':
        query = query.join(Publication).order_by(Publication.title.asc())
    else:  # saved_at (default)
        query = query.order_by(SavedPublication.saved_at.desc())

    # Get saved publications with related data
    saved_pubs = []
    for saved in query.all():
        pub = saved.publication

        # Get program areas and subtopics for tags
        areas = PublicationProgramArea.query.filter_by(publication_id=pub.id).all()
        program_areas = [get_program_area_name(a.program_area_key) for a in areas]

        subtopics_db = PublicationSubtopic.query.filter_by(publication_id=pub.id).all()
        subtopics = [get_subtopic_name(st.program_area_key, st.subtopic_key) for st in subtopics_db]

        saved_pubs.append({
            'saved': saved,
            'publication': pub,
            'folder_name': saved.folder.name if saved.folder else None,
            'program_areas': program_areas,
            'subtopics': subtopics
        })

    return render_template(
        'reading_list.html',
        folders=folders,
        saved_publications=saved_pubs,
        total_saved=total_saved,
        unfiled_count=unfiled_count,
        unread_count=unread_count,
        current_folder=folder_filter,
        current_read_filter=read_filter,
        current_sort=sort_by
    )


# ============================================================================
# READING LIST API ENDPOINTS
# ============================================================================

@main_bp.route('/api/saved-publications', methods=['POST'])
@login_required
def api_save_publication():
    """Save a publication to the user's reading list."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    publication_id = data.get('publication_id')
    folder_id = data.get('folder_id')  # Can be None for "unfiled"

    if not publication_id:
        return jsonify({'success': False, 'error': 'publication_id is required'}), 400

    # Check if publication exists
    publication = Publication.query.get(publication_id)
    if not publication:
        return jsonify({'success': False, 'error': 'Publication not found'}), 404

    # Check if already saved
    existing = SavedPublication.query.filter_by(
        user_id=current_user.id,
        publication_id=publication_id
    ).first()

    if existing:
        return jsonify({'success': False, 'error': 'Publication already saved'}), 409

    # Validate folder if provided
    if folder_id:
        folder = ReadingFolder.query.filter_by(id=folder_id, user_id=current_user.id).first()
        if not folder:
            return jsonify({'success': False, 'error': 'Folder not found'}), 404

    # Create saved publication
    saved = SavedPublication(
        user_id=current_user.id,
        publication_id=publication_id,
        folder_id=folder_id
    )
    db.session.add(saved)
    db.session.commit()

    return jsonify({
        'success': True,
        'saved_id': saved.id,
        'folder_id': folder_id
    })


@main_bp.route('/api/saved-publications/<int:publication_id>', methods=['DELETE'])
@login_required
def api_remove_publication(publication_id):
    """Remove a publication from the user's reading list."""
    saved = SavedPublication.query.filter_by(
        user_id=current_user.id,
        publication_id=publication_id
    ).first()

    if not saved:
        return jsonify({'success': False, 'error': 'Publication not in reading list'}), 404

    db.session.delete(saved)
    db.session.commit()

    return jsonify({'success': True})


@main_bp.route('/api/saved-publications/<int:publication_id>', methods=['PUT'])
@login_required
def api_update_saved_publication(publication_id):
    """Update a saved publication (folder, notes, read status)."""
    saved = SavedPublication.query.filter_by(
        user_id=current_user.id,
        publication_id=publication_id
    ).first()

    if not saved:
        return jsonify({'success': False, 'error': 'Publication not in reading list'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    # Update folder if provided
    if 'folder_id' in data:
        folder_id = data['folder_id']
        if folder_id is not None:
            folder = ReadingFolder.query.filter_by(id=folder_id, user_id=current_user.id).first()
            if not folder:
                return jsonify({'success': False, 'error': 'Folder not found'}), 404
        saved.folder_id = folder_id

    # Update notes if provided
    if 'notes' in data:
        saved.notes = data['notes']

    # Update read status if provided
    if 'is_read' in data:
        saved.is_read = bool(data['is_read'])

    db.session.commit()

    return jsonify({
        'success': True,
        'folder_id': saved.folder_id,
        'notes': saved.notes,
        'is_read': saved.is_read
    })


@main_bp.route('/api/reading-folders', methods=['GET'])
@login_required
def api_get_folders():
    """Get all folders for the current user with publication counts."""
    folders = []
    for folder in current_user.reading_folders.order_by(ReadingFolder.name):
        folders.append({
            'id': folder.id,
            'name': folder.name,
            'description': folder.description,
            'count': folder.saved_publications.count()
        })

    return jsonify({
        'success': True,
        'folders': folders,
        'unfiled_count': current_user.saved_publications.filter_by(folder_id=None).count()
    })


@main_bp.route('/api/reading-folders', methods=['POST'])
@login_required
def api_create_folder():
    """Create a new reading folder."""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    name = data.get('name', '').strip()
    description = data.get('description', '').strip() or None

    if not name:
        return jsonify({'success': False, 'error': 'Folder name is required'}), 400

    if len(name) > 255:
        return jsonify({'success': False, 'error': 'Folder name too long (max 255 characters)'}), 400

    # Check for duplicate name
    existing = ReadingFolder.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        return jsonify({'success': False, 'error': 'A folder with this name already exists'}), 409

    folder = ReadingFolder(
        user_id=current_user.id,
        name=name,
        description=description
    )
    db.session.add(folder)
    db.session.commit()

    return jsonify({
        'success': True,
        'folder': {
            'id': folder.id,
            'name': folder.name,
            'description': folder.description,
            'count': 0
        }
    })


@main_bp.route('/api/reading-folders/<int:folder_id>', methods=['PUT'])
@login_required
def api_update_folder(folder_id):
    """Update a reading folder (rename or change description)."""
    folder = ReadingFolder.query.filter_by(id=folder_id, user_id=current_user.id).first()

    if not folder:
        return jsonify({'success': False, 'error': 'Folder not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    if 'name' in data:
        name = data['name'].strip()
        if not name:
            return jsonify({'success': False, 'error': 'Folder name is required'}), 400
        if len(name) > 255:
            return jsonify({'success': False, 'error': 'Folder name too long'}), 400

        # Check for duplicate name (excluding current folder)
        existing = ReadingFolder.query.filter(
            ReadingFolder.user_id == current_user.id,
            ReadingFolder.name == name,
            ReadingFolder.id != folder_id
        ).first()
        if existing:
            return jsonify({'success': False, 'error': 'A folder with this name already exists'}), 409

        folder.name = name

    if 'description' in data:
        folder.description = data['description'].strip() or None

    folder.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'success': True,
        'folder': {
            'id': folder.id,
            'name': folder.name,
            'description': folder.description
        }
    })


@main_bp.route('/api/reading-folders/<int:folder_id>', methods=['DELETE'])
@login_required
def api_delete_folder(folder_id):
    """Delete a folder and move its publications to unfiled."""
    folder = ReadingFolder.query.filter_by(id=folder_id, user_id=current_user.id).first()

    if not folder:
        return jsonify({'success': False, 'error': 'Folder not found'}), 404

    # Move all publications in this folder to unfiled (set folder_id to NULL)
    SavedPublication.query.filter_by(folder_id=folder_id).update({'folder_id': None})

    # Delete the folder
    db.session.delete(folder)
    db.session.commit()

    return jsonify({'success': True})


@main_bp.route('/api/publication-saved-status')
@login_required
def api_publication_saved_status():
    """Check if publications are saved (for displaying bookmark status on cards)."""
    publication_ids = request.args.getlist('ids', type=int)

    if not publication_ids:
        return jsonify({'success': True, 'saved': {}})

    saved_pubs = SavedPublication.query.filter(
        SavedPublication.user_id == current_user.id,
        SavedPublication.publication_id.in_(publication_ids)
    ).all()

    saved_map = {}
    for saved in saved_pubs:
        saved_map[saved.publication_id] = {
            'folder_id': saved.folder_id,
            'folder_name': saved.folder.name if saved.folder else None
        }

    return jsonify({'success': True, 'saved': saved_map})
