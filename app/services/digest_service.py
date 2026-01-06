"""
Digest Service for the CHAI Health Publications Tracker.

This module handles creating and sending email digests:
- Finding relevant publications for each user based on two subscription types:
  1. Program Subscriptions - publications matching selected health topics
  2. Country Watch - ALL publications about selected countries/regions
- Creating personalized digest content with two sections:
  1. "New This Week" - publications not yet sent to the user
  2. "In Case You Missed It" - top previously sent publications
- Tracking what has been sent
- Managing digest scheduling
"""

import logging
import uuid
from datetime import datetime, timedelta, date
from flask import render_template, url_for

from app.models import db, User, Publication, PublicationProgramArea, PublicationSubtopic, PublicationRegion, DigestLog
from app.config import (
    Config, PROGRAM_AREAS, REGIONS_AND_COUNTRIES,
    get_program_area_name, get_region_name, get_subtopic_name,
    get_all_searchable_terms_for_region
)
from app.services.email_service import send_email
from app.routes import generate_unsubscribe_token

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for digest sections - separate caps per subscription type
# New This Week section
MAX_NEW_PROGRAM_PUBS = 10      # Program Subscriptions cap
MAX_NEW_COUNTRY_WATCH_PUBS = 10  # Country Watch cap

# In Case You Missed It section
MAX_ICYMI_PROGRAM_PUBS = 5     # Program Subscriptions cap
MAX_ICYMI_COUNTRY_WATCH_PUBS = 5  # Country Watch cap

# Total maximum per digest
TOTAL_MAX_PUBLICATIONS = 30

# Lookback periods for "In Case You Missed It" section (in days)
ICYMI_LOOKBACK = {
    'daily': 14,      # 2 weeks
    'weekly': 14,     # 2 weeks
    'biweekly': 28,   # 4 weeks
    'monthly': 28     # 4 weeks
}

# "No new publications" messages based on frequency
NO_NEW_PUBS_MESSAGE = {
    'daily': 'No new publications today matching your preferences.',
    'weekly': 'No new publications this week matching your preferences.',
    'biweekly': 'No new publications in the last two weeks matching your preferences.',
    'monthly': 'No new publications this month matching your preferences.'
}

# ICYMI header text based on frequency
ICYMI_HEADER = {
    'daily': 'In Case You Missed It (Past 2 Weeks)',
    'weekly': 'In Case You Missed It (Past 2 Weeks)',
    'biweekly': 'In Case You Missed It (Past 4 Weeks)',
    'monthly': 'In Case You Missed It (Past 4 Weeks)'
}


def get_program_subscription_publications(user, days_back=30, max_publications=None):
    """
    Find publications matching user's PROGRAM SUBSCRIPTIONS that haven't been sent yet.

    Program Subscriptions match by:
    - Program area (and optionally specific subtopics)
    - Optional region filter (only get publications about a specific region)

    Args:
        user: User object
        days_back: Only include publications from the last N days
        max_publications: Maximum number of publications to return

    Returns:
        List of dicts with publication data, program areas, subtopics, and regions
    """
    if max_publications is None:
        max_publications = Config.MAX_PUBLICATIONS_PER_DIGEST

    # Get detailed program preferences (with subtopic and region info)
    program_prefs = user.get_program_preferences_detail()

    if not program_prefs:
        return []

    # Organize preferences by what they want
    # {program_key: {'subtopics': set(), 'want_all': bool, 'location_type': str, 'location_values': set()}}
    prefs_by_program = {}
    for pref in program_prefs:
        program_key = pref['program_area_key']
        subtopic_key = pref['subtopic_key']
        locations = pref.get('locations', [])

        if program_key not in prefs_by_program:
            prefs_by_program[program_key] = {
                'subtopics': set(),
                'want_all': False,
                'location_type': 'all',
                'location_values': set()
            }

        if subtopic_key is None:
            prefs_by_program[program_key]['want_all'] = True
        else:
            prefs_by_program[program_key]['subtopics'].add(subtopic_key)

        # Handle location filters (all locations for a program should have same type)
        for loc in locations:
            prefs_by_program[program_key]['location_type'] = loc['location_type']
            prefs_by_program[program_key]['location_values'].add(loc['location_value'])

    # Calculate date cutoff
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)

    # Get publication IDs already sent to this user
    sent_pub_ids = db.session.query(DigestLog.publication_id).filter(
        DigestLog.user_id == user.id
    ).scalar_subquery()

    pub_dict = {}

    for program_key, pref_data in prefs_by_program.items():
        # Determine which publications match this program subscription
        if pref_data['want_all']:
            # Get all publications for this program area
            matching_pubs = db.session.query(
                Publication,
                PublicationProgramArea
            ).join(
                PublicationProgramArea,
                Publication.id == PublicationProgramArea.publication_id
            ).filter(
                PublicationProgramArea.program_area_key == program_key,
                Publication.scraped_at >= cutoff_date,
                ~Publication.id.in_(sent_pub_ids)
            ).all()

            for pub, pub_area in matching_pubs:
                _add_publication_to_dict(pub_dict, pub, pub_area, pref_data['location_type'], pref_data['location_values'])

        # Get publications matching specific subtopics
        for subtopic_key in pref_data['subtopics']:
            subtopic_pubs = db.session.query(
                Publication,
                PublicationSubtopic
            ).join(
                PublicationSubtopic,
                Publication.id == PublicationSubtopic.publication_id
            ).filter(
                PublicationSubtopic.program_area_key == program_key,
                PublicationSubtopic.subtopic_key == subtopic_key,
                Publication.scraped_at >= cutoff_date,
                ~Publication.id.in_(sent_pub_ids)
            ).all()

            for pub, pub_subtopic in subtopic_pubs:
                _add_subtopic_publication_to_dict(pub_dict, pub, pub_subtopic, pref_data['location_type'], pref_data['location_values'])

    # Apply location filter if specified (remove publications not matching location)
    if any(pref_data['location_values'] for pref_data in prefs_by_program.values()):
        pub_dict = _filter_by_location(pub_dict, prefs_by_program)

    # Add region info for display
    for pub_id, pub_data in pub_dict.items():
        if not pub_data['regions']:
            regions = PublicationRegion.query.filter_by(publication_id=pub_id).all()
            for region in regions:
                pub_data['regions'].append({
                    'key': region.region_key,
                    'name': get_region_name(region.region_key),
                    'matched_terms': region.matched_terms
                })

    # Convert to list, sort by relevance score, and limit
    results = list(pub_dict.values())
    results.sort(key=_get_max_score, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} program subscription publications for user {user.email}")
    return results


def _add_publication_to_dict(pub_dict, pub, pub_area, location_type, location_values):
    """Add a publication matched by program area to the dict."""
    if pub.id not in pub_dict:
        pub_dict[pub.id] = {
            'publication': pub,
            'program_areas': [],
            'subtopics': [],
            'regions': [],
            'location_type': location_type,
            'location_values': location_values
        }
    pub_dict[pub.id]['program_areas'].append({
        'key': pub_area.program_area_key,
        'name': get_program_area_name(pub_area.program_area_key),
        'score': pub_area.relevance_score
    })


def _add_subtopic_publication_to_dict(pub_dict, pub, pub_subtopic, location_type, location_values):
    """Add a publication matched by subtopic to the dict."""
    if pub.id not in pub_dict:
        pub_dict[pub.id] = {
            'publication': pub,
            'program_areas': [],
            'subtopics': [],
            'regions': [],
            'location_type': location_type,
            'location_values': location_values
        }
        # Also get program area info
        area = PublicationProgramArea.query.filter_by(
            publication_id=pub.id,
            program_area_key=pub_subtopic.program_area_key
        ).first()
        if area:
            pub_dict[pub.id]['program_areas'].append({
                'key': area.program_area_key,
                'name': get_program_area_name(area.program_area_key),
                'score': area.relevance_score
            })
    pub_dict[pub.id]['subtopics'].append({
        'program_key': pub_subtopic.program_area_key,
        'subtopic_key': pub_subtopic.subtopic_key,
        'name': get_subtopic_name(pub_subtopic.program_area_key, pub_subtopic.subtopic_key),
        'score': pub_subtopic.relevance_score
    })


def _filter_by_location(pub_dict, prefs_by_program):
    """Filter publications to only include those matching location filters (region or country)."""
    filtered_dict = {}

    for pub_id, pub_data in pub_dict.items():
        location_type = pub_data.get('location_type', 'all')
        location_values = pub_data.get('location_values', set())

        # If no location filter (type='all'), include the publication
        if location_type == 'all' or not location_values:
            filtered_dict[pub_id] = pub_data
            continue

        # Get all regions for this publication
        pub_regions = PublicationRegion.query.filter_by(publication_id=pub_id).all()

        if location_type == 'region':
            # Filter by region - publication must match ANY of the selected regions
            pub_region_keys = set(r.region_key for r in pub_regions)
            if pub_region_keys.intersection(location_values):
                filtered_dict[pub_id] = pub_data
                # Add matching region info
                for region in pub_regions:
                    if region.region_key in location_values:
                        pub_data['regions'].append({
                            'key': region.region_key,
                            'name': get_region_name(region.region_key),
                            'matched_terms': region.matched_terms
                        })

        elif location_type == 'country':
            # Filter by country - publication must mention ANY of the selected countries
            matched = False
            for region in pub_regions:
                if region.matched_terms:
                    matched_terms = set(region.matched_terms.split(', '))
                    if matched_terms.intersection(location_values):
                        matched = True
                        if pub_id not in filtered_dict:
                            filtered_dict[pub_id] = pub_data
                        # Add region info with matched countries highlighted
                        if not any(r['key'] == region.region_key for r in pub_data['regions']):
                            pub_data['regions'].append({
                                'key': region.region_key,
                                'name': get_region_name(region.region_key),
                                'matched_terms': region.matched_terms
                            })

    return filtered_dict


def get_country_watch_publications(user, days_back=30, max_publications=None):
    """
    Find ALL publications matching user's COUNTRY WATCH subscriptions
    that haven't been sent yet.

    Country Watch returns all health publications about:
    - Entire regions (all countries in that region)
    - Specific countries

    Args:
        user: User object
        days_back: Only include publications from the last N days
        max_publications: Maximum number of publications to return

    Returns:
        List of dicts with publication data, program areas, subtopics, and regions
    """
    if max_publications is None:
        max_publications = Config.MAX_PUBLICATIONS_PER_DIGEST

    # Get user's country watches
    country_watches = user.get_country_watches()

    if not country_watches:
        return []

    # Collect all region keys and country names to watch
    watch_regions = set()
    watch_countries = set()

    for watch in country_watches:
        if watch['region_key'] and not watch['country_name']:
            # Watching entire region
            watch_regions.add(watch['region_key'])
        elif watch['country_name']:
            # Watching specific country
            watch_countries.add(watch['country_name'])

    # Calculate date cutoff
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)

    # Get publication IDs already sent to this user
    sent_pub_ids = db.session.query(DigestLog.publication_id).filter(
        DigestLog.user_id == user.id
    ).scalar_subquery()

    pub_dict = {}

    # Get publications matching watched regions
    if watch_regions:
        region_pubs = db.session.query(
            Publication,
            PublicationRegion
        ).join(
            PublicationRegion,
            Publication.id == PublicationRegion.publication_id
        ).filter(
            PublicationRegion.region_key.in_(watch_regions),
            Publication.scraped_at >= cutoff_date,
            ~Publication.id.in_(sent_pub_ids)
        ).all()

        for pub, pub_region in region_pubs:
            if pub.id not in pub_dict:
                pub_dict[pub.id] = {
                    'publication': pub,
                    'program_areas': [],
                    'subtopics': [],
                    'regions': [],
                    'from_country_watch': True
                }
            pub_dict[pub.id]['regions'].append({
                'key': pub_region.region_key,
                'name': get_region_name(pub_region.region_key),
                'matched_terms': pub_region.matched_terms
            })

    # Get publications matching watched countries
    # This requires checking matched_terms in PublicationRegion
    if watch_countries:
        # Get all publications with regions, then filter by matched_terms containing country
        all_region_pubs = db.session.query(
            Publication,
            PublicationRegion
        ).join(
            PublicationRegion,
            Publication.id == PublicationRegion.publication_id
        ).filter(
            Publication.scraped_at >= cutoff_date,
            ~Publication.id.in_(sent_pub_ids)
        ).all()

        for pub, pub_region in all_region_pubs:
            if pub_region.matched_terms:
                matched_terms = set(pub_region.matched_terms.split(', '))
                if matched_terms.intersection(watch_countries):
                    if pub.id not in pub_dict:
                        pub_dict[pub.id] = {
                            'publication': pub,
                            'program_areas': [],
                            'subtopics': [],
                            'regions': [],
                            'from_country_watch': True
                        }
                    if not any(r['key'] == pub_region.region_key for r in pub_dict[pub.id]['regions']):
                        pub_dict[pub.id]['regions'].append({
                            'key': pub_region.region_key,
                            'name': get_region_name(pub_region.region_key),
                            'matched_terms': pub_region.matched_terms
                        })

    # Add program area and subtopic info for display
    for pub_id, pub_data in pub_dict.items():
        areas = PublicationProgramArea.query.filter_by(publication_id=pub_id).all()
        for area in areas:
            pub_data['program_areas'].append({
                'key': area.program_area_key,
                'name': get_program_area_name(area.program_area_key),
                'score': area.relevance_score
            })

        subtopics = PublicationSubtopic.query.filter_by(publication_id=pub_id).all()
        for st in subtopics:
            pub_data['subtopics'].append({
                'program_key': st.program_area_key,
                'subtopic_key': st.subtopic_key,
                'name': get_subtopic_name(st.program_area_key, st.subtopic_key),
                'score': st.relevance_score
            })

    # Convert to list, sort by date, and limit
    results = list(pub_dict.values())
    results.sort(key=lambda x: x['publication'].publication_date or date.min, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} country watch publications for user {user.email}")
    return results


def get_resurfaced_publications(user, max_publications=None):
    """
    Find ahead-of-print publications that should be resurfaced.

    A publication should be resurfaced if:
    - It was previously sent to this user (exists in DigestLog)
    - It is an ahead-of-print publication (is_ahead_of_print = True)
    - Its publication_date is now in the past (official date has arrived)
    - It hasn't been resurfaced yet (resurfaced_at IS NULL)

    Args:
        user: User object
        max_publications: Maximum number of publications to return

    Returns:
        List of dicts with publication data marked with is_resurfaced=True
    """
    if max_publications is None:
        max_publications = Config.MAX_PUBLICATIONS_PER_DIGEST

    today = date.today()

    # Find publication IDs that were previously sent to this user
    sent_pub_ids = db.session.query(DigestLog.publication_id).filter(
        DigestLog.user_id == user.id
    ).scalar_subquery()

    # Find ahead-of-print publications that are now published and haven't been resurfaced
    resurfaced_pubs = db.session.query(Publication).filter(
        Publication.id.in_(sent_pub_ids),
        Publication.is_ahead_of_print == True,
        Publication.publication_date <= today,
        Publication.resurfaced_at.is_(None)
    ).all()

    if not resurfaced_pubs:
        return []

    pub_dict = {}
    for pub in resurfaced_pubs:
        pub_dict[pub.id] = {
            'publication': pub,
            'program_areas': [],
            'subtopics': [],
            'regions': [],
            'is_resurfaced': True
        }

        # Get program areas
        areas = PublicationProgramArea.query.filter_by(publication_id=pub.id).all()
        for area in areas:
            pub_dict[pub.id]['program_areas'].append({
                'key': area.program_area_key,
                'name': get_program_area_name(area.program_area_key),
                'score': area.relevance_score
            })

        # Get subtopics
        subtopics = PublicationSubtopic.query.filter_by(publication_id=pub.id).all()
        for st in subtopics:
            pub_dict[pub.id]['subtopics'].append({
                'program_key': st.program_area_key,
                'subtopic_key': st.subtopic_key,
                'name': get_subtopic_name(st.program_area_key, st.subtopic_key),
                'score': st.relevance_score
            })

        # Get regions
        regions = PublicationRegion.query.filter_by(publication_id=pub.id).all()
        for region in regions:
            pub_dict[pub.id]['regions'].append({
                'key': region.region_key,
                'name': get_region_name(region.region_key),
                'matched_terms': region.matched_terms
            })

    results = list(pub_dict.values())
    results.sort(key=_get_max_score, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} resurfaced publications for user {user.email}")
    return results


def get_publications_for_user(user, days_back=30, max_publications=None):
    """
    Find all publications matching user's subscriptions that haven't been sent yet,
    plus ahead-of-print publications that are now officially published (resurfaced).

    Combines results from:
    1. Program Subscriptions (health topic-based)
    2. Country Watch (geography-based)
    3. Resurfaced publications (ahead-of-print now published)

    Args:
        user: User object
        days_back: Only include publications from the last N days
        max_publications: Maximum number of publications to return

    Returns:
        List of dicts with publication data, program areas, subtopics, and regions
    """
    if max_publications is None:
        max_publications = Config.MAX_PUBLICATIONS_PER_DIGEST

    # Get publications from both subscription types
    program_pubs = get_program_subscription_publications(user, days_back, max_publications)
    country_watch_pubs = get_country_watch_publications(user, days_back, max_publications)

    # Get resurfaced publications (ahead-of-print that are now officially published)
    resurfaced_pubs = get_resurfaced_publications(user, max_publications)

    # Combine and deduplicate
    pub_dict = {}

    # Add resurfaced publications first (they get priority in "New This Week")
    for pub_data in resurfaced_pubs:
        pub_id = pub_data['publication'].id
        pub_dict[pub_id] = pub_data
        pub_dict[pub_id]['is_resurfaced'] = True

    for pub_data in program_pubs:
        pub_id = pub_data['publication'].id
        if pub_id not in pub_dict:
            pub_dict[pub_id] = pub_data
        pub_dict[pub_id]['from_program_sub'] = True

    for pub_data in country_watch_pubs:
        pub_id = pub_data['publication'].id
        if pub_id not in pub_dict:
            pub_dict[pub_id] = pub_data
        else:
            # Publication already in dict from program subs, mark as both
            pub_dict[pub_id]['from_country_watch'] = True

    # Convert to list, sort by relevance score, and limit
    results = list(pub_dict.values())
    results.sort(key=_get_max_score, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} total publications for user {user.email}")
    return results


def _get_max_score(pub_data):
    """Get the maximum relevance score for a publication."""
    scores = [pa['score'] for pa in pub_data.get('program_areas', [])]
    scores.extend([st['score'] for st in pub_data.get('subtopics', [])])
    return max(scores) if scores else 0


def _format_program_subscriptions_for_footer(program_prefs):
    """
    Format program subscription preferences for email footer display.

    Groups subscriptions by program area and includes location filter info.

    Args:
        program_prefs: List of preference dicts from user.get_program_preferences_detail()

    Returns:
        List of dicts: [{'program_name': str, 'subtopics': [str], 'location_filter': str}]
    """
    # Group by program area
    programs = {}
    for pref in program_prefs:
        program_key = pref['program_area_key']
        program_name = get_program_area_name(program_key)
        subtopic_key = pref['subtopic_key']
        locations = pref.get('locations', [])

        if program_key not in programs:
            programs[program_key] = {
                'program_name': program_name,
                'subtopics': [],
                'want_all_subtopics': False,
                'location_type': 'all',
                'location_names': []
            }

        if subtopic_key is None:
            programs[program_key]['want_all_subtopics'] = True
        else:
            subtopic_name = get_subtopic_name(program_key, subtopic_key)
            if subtopic_name not in programs[program_key]['subtopics']:
                programs[program_key]['subtopics'].append(subtopic_name)

        # Handle location filters
        for loc in locations:
            programs[program_key]['location_type'] = loc['location_type']
            if loc['location_type'] == 'region':
                loc_name = get_region_name(loc['location_value'])
            else:
                loc_name = loc['location_value']  # Country name is already human-readable
            if loc_name not in programs[program_key]['location_names']:
                programs[program_key]['location_names'].append(loc_name)

    # Format for display
    result = []
    for program_key, data in programs.items():
        formatted = {
            'program_name': data['program_name'],
            'subtopics': data['subtopics'] if not data['want_all_subtopics'] else [],
            'all_subtopics': data['want_all_subtopics'],
            'location_filter': None
        }

        # Build location filter string
        if data['location_type'] == 'region' and data['location_names']:
            formatted['location_filter'] = f"Regions: {', '.join(data['location_names'])}"
        elif data['location_type'] == 'country' and data['location_names']:
            formatted['location_filter'] = f"Countries: {', '.join(data['location_names'])}"

        result.append(formatted)

    return result


def get_previously_sent_publications(user, lookback_days, max_publications=MAX_ICYMI_PROGRAM_PUBS, exclude_ids=None, subscription_type=None):
    """
    Get publications that were previously sent to this user within the lookback period.

    Args:
        user: User object
        lookback_days: How many days back to look for previously sent publications
        max_publications: Maximum number of publications to return
        exclude_ids: Set of publication IDs to exclude (e.g., those in Section 1)
        subscription_type: Filter by subscription type - 'program', 'country_watch', or None for all

    Returns:
        List of dicts with publication data, program areas, and regions, sorted by relevance
    """
    if exclude_ids is None:
        exclude_ids = set()

    # Calculate lookback cutoff
    cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

    # Get publication IDs sent to this user within the lookback period
    sent_logs = db.session.query(DigestLog).filter(
        DigestLog.user_id == user.id,
        DigestLog.sent_at >= cutoff_date
    ).order_by(DigestLog.sent_at.desc()).all()

    # Get unique publication IDs (most recently sent first)
    sent_pub_ids = []
    seen = set()
    for log in sent_logs:
        if log.publication_id not in seen and log.publication_id not in exclude_ids:
            sent_pub_ids.append(log.publication_id)
            seen.add(log.publication_id)

    if not sent_pub_ids:
        return []

    # Get user's subscribed program keys for filtering
    user_program_keys = set()
    if subscription_type in ('program', None):
        user_program_keys = set(pref.program_area_key for pref in user.program_preferences)

    # Get user's watched regions/countries for filtering
    user_watched_regions = set()
    user_watched_countries = set()
    if subscription_type in ('country_watch', None):
        for watch in user.country_watches:
            if watch.region_key and not watch.country_name:
                user_watched_regions.add(watch.region_key)
            if watch.country_name:
                user_watched_countries.add(watch.country_name)

    # Get the publications with their program areas
    pub_dict = {}
    for pub_id in sent_pub_ids:
        pub = Publication.query.get(pub_id)
        if not pub:
            continue

        # Get program areas
        areas = PublicationProgramArea.query.filter_by(publication_id=pub_id).all()
        program_areas = []
        matches_program = False
        for area in areas:
            program_areas.append({
                'key': area.program_area_key,
                'name': get_program_area_name(area.program_area_key),
                'score': area.relevance_score
            })
            if area.program_area_key in user_program_keys:
                matches_program = True

        # Get subtopics
        subtopics = PublicationSubtopic.query.filter_by(publication_id=pub_id).all()
        subtopic_list = []
        for st in subtopics:
            subtopic_list.append({
                'program_key': st.program_area_key,
                'subtopic_key': st.subtopic_key,
                'name': get_subtopic_name(st.program_area_key, st.subtopic_key),
                'score': st.relevance_score
            })

        # Get regions
        regions = PublicationRegion.query.filter_by(publication_id=pub_id).all()
        region_list = []
        matches_country_watch = False
        for region in regions:
            region_list.append({
                'key': region.region_key,
                'name': get_region_name(region.region_key),
                'matched_terms': region.matched_terms
            })
            # Check if this region matches user's country watch
            if region.region_key in user_watched_regions:
                matches_country_watch = True
            # Check if any matched terms are in user's watched countries
            if region.matched_terms:
                matched_terms = [t.strip() for t in region.matched_terms.split(',')]
                if any(term in user_watched_countries for term in matched_terms):
                    matches_country_watch = True

        # Filter based on subscription_type
        include_pub = False
        if subscription_type == 'program' and matches_program:
            include_pub = True
        elif subscription_type == 'country_watch' and matches_country_watch:
            include_pub = True
        elif subscription_type is None:
            include_pub = True

        if include_pub:
            pub_dict[pub.id] = {
                'publication': pub,
                'program_areas': program_areas,
                'subtopics': subtopic_list,
                'regions': region_list,
                'from_program_sub': matches_program,
                'from_country_watch': matches_country_watch
            }

    # Convert to list, sort by relevance score, and limit
    results = list(pub_dict.values())
    results.sort(key=_get_max_score, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} previously sent publications for user {user.email} (type: {subscription_type or 'all'})")
    return results


def format_publication_for_display(pub_data):
    """
    Format a publication dict for display in the digest.

    Args:
        pub_data: Dict with 'publication', 'program_areas', 'subtopics', 'regions'

    Returns:
        Dict formatted for template display

    Tag logic:
        - is_ahead_of_print=True and publication_date is in future → "Ahead of Print" (amber)
        - is_ahead_of_print=True and is_resurfaced=True → "Now Published" (green)
        - Otherwise → no special tag
    """
    pub = pub_data['publication']
    today = date.today()

    # Get the highest relevance score
    max_score = _get_max_score(pub_data)

    # Get program area names for display (deduplicated)
    program_area_names = list(dict.fromkeys([pa['name'] for pa in pub_data.get('program_areas', [])]))

    # Get region and subtopic names for display
    region_names = [r['name'] for r in pub_data.get('regions', [])]
    subtopic_names = [st['name'] for st in pub_data.get('subtopics', [])]

    # Determine tag display:
    # - show_ahead_of_print: True if ahead-of-print AND date is still in the future
    # - is_resurfaced: True if this is a resurfaced publication (now officially published)
    is_ahead_of_print = getattr(pub, 'is_ahead_of_print', False)
    is_resurfaced = pub_data.get('is_resurfaced', False)

    # Only show "Ahead of Print" if the date is still in the future
    show_ahead_of_print = is_ahead_of_print and pub.publication_date and pub.publication_date > today

    return {
        'title': pub.title,
        'url': pub.url,
        'source': pub.source,
        'date': pub.publication_date,
        'is_ahead_of_print': show_ahead_of_print,  # Only True if date is in future
        'is_resurfaced': is_resurfaced,  # True if now officially published
        'abstract': truncate_text(pub.abstract, 200) if pub.abstract else None,
        'authors': pub.authors,
        'relevance_score': max_score,
        'program_areas': program_area_names,
        'regions': region_names,
        'subtopics': subtopic_names,
        'from_country_watch': pub_data.get('from_country_watch', False),
        'from_program_sub': pub_data.get('from_program_sub', False)
    }


def create_digest_content(user, new_publications, icymi_publications, base_url=None):
    """
    Create the HTML content for a digest email with two sections.

    Args:
        user: User object
        new_publications: List of new publications (Section 1: "New This Week")
        icymi_publications: List of previously sent publications (Section 2: "In Case You Missed It")
        base_url: Base URL for links (preferences, unsubscribe).
                  Defaults to Config.BASE_URL if not provided.

    Returns:
        Dictionary with 'html' and 'text' content
    """
    if base_url is None:
        base_url = Config.BASE_URL

    # Separate new publications by subscription type
    new_program_pubs = [p for p in new_publications if p.get('from_program_sub', False) and not p.get('from_country_watch', False)]
    new_country_watch_pubs = [p for p in new_publications if p.get('from_country_watch', False) and not p.get('from_program_sub', False)]
    new_both_pubs = [p for p in new_publications if p.get('from_program_sub', False) and p.get('from_country_watch', False)]

    # Publications that match both go to program subscriptions section
    new_program_pubs.extend(new_both_pubs)

    # Separate ICYMI publications by subscription type (need to check source)
    icymi_program_pubs = [p for p in icymi_publications if p.get('from_program_sub', False) or not p.get('from_country_watch', False)]
    icymi_country_watch_pubs = [p for p in icymi_publications if p.get('from_country_watch', False)]

    # Format publications for display
    new_program_pubs_formatted = [format_publication_for_display(p) for p in new_program_pubs]
    new_country_watch_pubs_formatted = [format_publication_for_display(p) for p in new_country_watch_pubs]
    icymi_program_pubs_formatted = [format_publication_for_display(p) for p in icymi_program_pubs]
    icymi_country_watch_pubs_formatted = [format_publication_for_display(p) for p in icymi_country_watch_pubs]

    # Generate unsubscribe token
    unsubscribe_token = generate_unsubscribe_token(user)
    unsubscribe_url = f"{base_url}/unsubscribe/{unsubscribe_token}"
    preferences_url = f"{base_url}/preferences"

    # Get user's program subscriptions with location filters for footer
    program_prefs = user.get_program_preferences_detail()
    program_subscriptions = _format_program_subscriptions_for_footer(program_prefs)

    # Get user's country watches for footer
    country_watches = user.get_country_watches()
    watched_regions = [get_region_name(w['region_key']) for w in country_watches if w['region_key'] and not w['country_name']]
    watched_countries = [w['country_name'] for w in country_watches if w['country_name']]

    # Get frequency-specific text
    frequency = user.digest_frequency
    no_new_pubs_message = NO_NEW_PUBS_MESSAGE.get(frequency, NO_NEW_PUBS_MESSAGE['weekly'])
    icymi_header = ICYMI_HEADER.get(frequency, ICYMI_HEADER['weekly'])

    # Calculate date range
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=7)

    # Total publication count
    total_count = len(new_publications) + len(icymi_publications)

    # Create context for template
    context = {
        'user': user,
        # Separated new publications
        'new_program_pubs': new_program_pubs_formatted,
        'new_country_watch_pubs': new_country_watch_pubs_formatted,
        # Separated ICYMI publications
        'icymi_program_pubs': icymi_program_pubs_formatted,
        'icymi_country_watch_pubs': icymi_country_watch_pubs_formatted,
        # Counts
        'new_program_count': len(new_program_pubs_formatted),
        'new_country_watch_count': len(new_country_watch_pubs_formatted),
        'new_count': len(new_publications),
        'icymi_program_count': len(icymi_program_pubs_formatted),
        'icymi_country_watch_count': len(icymi_country_watch_pubs_formatted),
        'icymi_count': len(icymi_publications),
        'total_count': total_count,
        # Flags for showing sections
        'has_new_publications': len(new_publications) > 0,
        'has_new_program_pubs': len(new_program_pubs_formatted) > 0,
        'has_new_country_watch_pubs': len(new_country_watch_pubs_formatted) > 0,
        'has_icymi_publications': len(icymi_publications) > 0,
        'has_icymi_program_pubs': len(icymi_program_pubs_formatted) > 0,
        'has_icymi_country_watch_pubs': len(icymi_country_watch_pubs_formatted) > 0,
        'no_new_pubs_message': no_new_pubs_message,
        'icymi_header': icymi_header,
        'start_date': start_date.strftime('%B %d, %Y'),
        'end_date': end_date.strftime('%B %d, %Y'),
        'program_subscriptions': program_subscriptions,
        'subscribed_regions': watched_regions,
        'watched_countries': watched_countries,
        'unsubscribe_url': unsubscribe_url,
        'preferences_url': preferences_url,
    }

    # Render HTML template
    from flask import current_app
    with current_app.app_context():
        html_content = render_template('email_digest.html', **context)

    # Create plain text version
    text_content = create_plain_text_digest(context)

    # Create subject line
    if len(new_publications) > 0:
        subject = f"CHAI Health Digest - {len(new_publications)} New Publication{'s' if len(new_publications) != 1 else ''}"
    else:
        subject = "CHAI Health Digest - In Case You Missed It"

    return {
        'html': html_content,
        'text': text_content,
        'subject': subject
    }


def create_plain_text_digest(context):
    """
    Create a plain text version of the digest for email clients
    that don't support HTML.

    Args:
        context: Dictionary with digest data

    Returns:
        Plain text string
    """
    def format_pub_text(pub):
        """Format a single publication for plain text."""
        pub_lines = []
        pub_lines.append(f"* {pub['title']}")
        pub_lines.append(f"  Source: {pub['source']}")
        if pub['date']:
            date_str = pub['date'].strftime('%B %Y')
            if pub.get('is_ahead_of_print'):
                date_str += " (Ahead of Print)"
            elif pub.get('is_resurfaced'):
                date_str += " (Now Published)"
            pub_lines.append(f"  Date: {date_str}")
        # Show program areas and subtopics as tags
        tags = []
        if pub.get('program_areas'):
            tags.extend(pub['program_areas'])
        if pub.get('subtopics'):
            tags.extend(pub['subtopics'])
        if tags:
            pub_lines.append(f"  Tags: [{'] ['.join(tags)}]")
        if pub.get('regions'):
            pub_lines.append(f"  Regions: {', '.join(pub['regions'])}")
        pub_lines.append(f"  Link: {pub['url']}")
        if pub['abstract']:
            pub_lines.append(f"  {pub['abstract']}")
        pub_lines.append("")
        return pub_lines

    lines = [
        "CHAI Health Publications Digest",
        "=" * 40,
        f"Date: {context['end_date']}",
        "",
    ]

    # Section 1: New This Week
    if context['has_new_publications']:
        lines.append("=" * 40)
        lines.append("NEW THIS WEEK")
        lines.append("=" * 40)
        lines.append(f"{context['new_count']} new publication{'s' if context['new_count'] != 1 else ''}")
        lines.append("")

        # Program Subscriptions sub-section
        if context.get('has_new_program_pubs'):
            lines.append("PROGRAM SUBSCRIPTIONS")
            lines.append("-" * 20)
            lines.append(f"{context['new_program_count']} publication{'s' if context['new_program_count'] != 1 else ''}")
            lines.append("")
            for pub in context['new_program_pubs']:
                lines.extend(format_pub_text(pub))

        # Country Watch sub-section
        if context.get('has_new_country_watch_pubs'):
            lines.append("COUNTRY WATCH")
            lines.append("-" * 20)
            lines.append(f"{context['new_country_watch_count']} publication{'s' if context['new_country_watch_count'] != 1 else ''}")
            lines.append("")
            for pub in context['new_country_watch_pubs']:
                lines.extend(format_pub_text(pub))
    else:
        lines.append(context['no_new_pubs_message'])
        lines.append("")

    # Section 2: In Case You Missed It
    if context['has_icymi_publications']:
        lines.append("")
        lines.append("=" * 40)
        lines.append(context['icymi_header'].upper())
        lines.append("=" * 40)
        lines.append(f"{context['icymi_count']} publication{'s' if context['icymi_count'] != 1 else ''}")
        lines.append("")

        # Program Subscriptions sub-section
        if context.get('has_icymi_program_pubs'):
            lines.append("PROGRAM SUBSCRIPTIONS")
            lines.append("-" * 20)
            lines.append(f"{context['icymi_program_count']} publication{'s' if context['icymi_program_count'] != 1 else ''}")
            lines.append("")
            for pub in context['icymi_program_pubs']:
                lines.extend(format_pub_text(pub))

        # Country Watch sub-section
        if context.get('has_icymi_country_watch_pubs'):
            lines.append("COUNTRY WATCH")
            lines.append("-" * 20)
            lines.append(f"{context['icymi_country_watch_count']} publication{'s' if context['icymi_country_watch_count'] != 1 else ''}")
            lines.append("")
            for pub in context['icymi_country_watch_pubs']:
                lines.extend(format_pub_text(pub))

    lines.extend([
        "",
        "-" * 40,
    ])

    # Show program subscription info
    if context.get('program_subscriptions'):
        lines.append("Program Subscriptions:")
        for sub in context['program_subscriptions']:
            sub_line = f"  - {sub['program_name']}"
            if sub['subtopics']:
                sub_line += f" ({', '.join(sub['subtopics'])})"
            elif sub['all_subtopics']:
                sub_line += " (All topics)"
            if sub['location_filter']:
                sub_line += f" [{sub['location_filter']}]"
            lines.append(sub_line)

    # Show country watch info
    if context.get('subscribed_regions'):
        lines.append(f"Watching regions: {', '.join(context['subscribed_regions'])}")
    if context.get('watched_countries'):
        lines.append(f"Watching countries: {', '.join(context['watched_countries'])}")

    lines.extend([
        f"Update preferences: {context['preferences_url']}",
        f"Unsubscribe: {context['unsubscribe_url']}",
    ])

    return "\n".join(lines)


def truncate_text(text, max_length):
    """Truncate text to max_length, adding ellipsis if needed."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length-3].rsplit(' ', 1)[0] + "..."


def send_digest_to_user(user, base_url=None):
    """
    Create and send a digest email to a single user.

    The digest has two main sections with sub-sections:
    1. "New This Week"
       - Program Subscriptions: up to MAX_NEW_PROGRAM_PUBS publications
       - Country Watch: up to MAX_NEW_COUNTRY_WATCH_PUBS publications
    2. "In Case You Missed It"
       - Program Subscriptions: up to MAX_ICYMI_PROGRAM_PUBS publications
       - Country Watch: up to MAX_ICYMI_COUNTRY_WATCH_PUBS publications

    Total maximum: TOTAL_MAX_PUBLICATIONS (30)

    Args:
        user: User object
        base_url: Base URL for links. Defaults to Config.BASE_URL.

    Returns:
        Dictionary with results: {success, new_sent, icymi_count, error}
    """
    if base_url is None:
        base_url = Config.BASE_URL
    logger.info(f"Preparing digest for user {user.email}")

    # Get new publications separately by subscription type with individual caps
    # Each list is sorted by relevance score (highest first)
    new_program_pubs = get_program_subscription_publications(
        user, days_back=30, max_publications=MAX_NEW_PROGRAM_PUBS
    )
    new_country_watch_pubs = get_country_watch_publications(
        user, days_back=30, max_publications=MAX_NEW_COUNTRY_WATCH_PUBS
    )

    # Get resurfaced publications (ahead-of-print that are now officially published)
    resurfaced_pubs = get_resurfaced_publications(user, max_publications=MAX_NEW_PROGRAM_PUBS)

    # Mark resurfaced publications and add to program pubs (they were originally program subs)
    for pub_data in resurfaced_pubs:
        pub_data['is_resurfaced'] = True
        pub_data['from_program_sub'] = True

    # Combine into new_publications list, handling overlaps
    new_pub_dict = {}

    # Add resurfaced first (priority)
    for pub_data in resurfaced_pubs:
        pub_id = pub_data['publication'].id
        new_pub_dict[pub_id] = pub_data

    # Add program pubs (mark as from_program_sub)
    for pub_data in new_program_pubs:
        pub_id = pub_data['publication'].id
        if pub_id not in new_pub_dict:
            new_pub_dict[pub_id] = pub_data
        new_pub_dict[pub_id]['from_program_sub'] = True

    # Add country watch pubs (mark as from_country_watch)
    for pub_data in new_country_watch_pubs:
        pub_id = pub_data['publication'].id
        if pub_id not in new_pub_dict:
            new_pub_dict[pub_id] = pub_data
        new_pub_dict[pub_id]['from_country_watch'] = True

    new_publications = list(new_pub_dict.values())

    # Get IDs of new publications to exclude from ICYMI
    new_pub_ids = set(p['publication'].id for p in new_publications)

    # Get lookback period based on user's frequency
    lookback_days = ICYMI_LOOKBACK.get(user.digest_frequency, 14)

    # Get previously sent publications separately by subscription type
    icymi_program_pubs = get_previously_sent_publications(
        user,
        lookback_days=lookback_days,
        max_publications=MAX_ICYMI_PROGRAM_PUBS,
        exclude_ids=new_pub_ids,
        subscription_type='program'
    )
    icymi_country_watch_pubs = get_previously_sent_publications(
        user,
        lookback_days=lookback_days,
        max_publications=MAX_ICYMI_COUNTRY_WATCH_PUBS,
        exclude_ids=new_pub_ids,
        subscription_type='country_watch'
    )

    # Combine ICYMI publications, handling overlaps
    icymi_pub_dict = {}
    for pub_data in icymi_program_pubs:
        pub_id = pub_data['publication'].id
        icymi_pub_dict[pub_id] = pub_data
        icymi_pub_dict[pub_id]['from_program_sub'] = True
    for pub_data in icymi_country_watch_pubs:
        pub_id = pub_data['publication'].id
        if pub_id not in icymi_pub_dict:
            icymi_pub_dict[pub_id] = pub_data
        icymi_pub_dict[pub_id]['from_country_watch'] = True

    icymi_publications = list(icymi_pub_dict.values())

    # If no publications at all, skip sending
    if not new_publications and not icymi_publications:
        logger.info(f"No publications (new or ICYMI) for user {user.email}")
        return {
            'success': True,
            'new_sent': 0,
            'icymi_count': 0,
            'message': 'No publications to send'
        }

    try:
        # Create digest content with both sections
        content = create_digest_content(user, new_publications, icymi_publications, base_url)

        # Send the email
        email_sent = send_email(
            to_email=user.email,
            subject=content['subject'],
            html_content=content['html'],
            text_content=content['text']
        )

        if email_sent:
            # Log only the NEW publications (not ICYMI or resurfaced, as those were already logged)
            batch_id = str(uuid.uuid4())[:8]
            resurfaced_count = 0
            for pub_data in new_publications:
                pub = pub_data['publication']
                is_resurfaced = pub_data.get('is_resurfaced', False)

                if is_resurfaced:
                    # Mark as resurfaced so it won't appear again
                    pub.resurfaced_at = datetime.utcnow()
                    resurfaced_count += 1
                else:
                    # Only log truly new publications (not resurfaced ones)
                    log = DigestLog(
                        user_id=user.id,
                        publication_id=pub.id,
                        digest_batch_id=batch_id
                    )
                    db.session.add(log)

            # Update user's last_digest_sent
            user.last_digest_sent = datetime.utcnow()
            db.session.commit()

            logger.info(f"Digest sent to {user.email}: {len(new_publications)} new ({resurfaced_count} resurfaced), {len(icymi_publications)} ICYMI")
            return {
                'success': True,
                'new_sent': len(new_publications),
                'icymi_count': len(icymi_publications),
                'message': 'Digest sent successfully'
            }
        else:
            logger.error(f"Failed to send digest to {user.email}")
            return {
                'success': False,
                'new_sent': 0,
                'icymi_count': 0,
                'error': 'Email sending failed'
            }

    except Exception as e:
        logger.error(f"Error creating digest for {user.email}: {e}")
        return {
            'success': False,
            'new_sent': 0,
            'icymi_count': 0,
            'error': str(e)
        }


def get_users_due_for_digest():
    """
    Find all active users who are due for a digest based on their frequency setting.

    Returns:
        List of User objects
    """
    now = datetime.utcnow()
    users_due = []

    # Get all active users
    active_users = User.query.filter(
        User.is_active == True
    ).all()

    for user in active_users:
        # Skip users with no subscriptions (program preferences OR country watches)
        if not user.has_subscriptions():
            continue

        # If never sent a digest, they're due
        if user.last_digest_sent is None:
            users_due.append(user)
            continue

        # Calculate if due based on frequency
        days_since_last = (now - user.last_digest_sent).days

        frequency_days = {
            'daily': 1,
            'weekly': 7,
            'biweekly': 14,
            'monthly': 30
        }

        required_days = frequency_days.get(user.digest_frequency, 7)

        if days_since_last >= required_days:
            users_due.append(user)

    logger.info(f"Found {len(users_due)} users due for digest")
    return users_due


def send_all_pending_digests(base_url=None):
    """
    Send digests to all users who are due.

    Args:
        base_url: Base URL for links in emails. Defaults to Config.BASE_URL.

    Returns:
        Dictionary with summary: {total, sent, failed, skipped}
    """
    if base_url is None:
        base_url = Config.BASE_URL
    logger.info("=" * 50)
    logger.info("Starting digest send process")
    logger.info("=" * 50)

    users = get_users_due_for_digest()

    results = {
        'total': len(users),
        'sent': 0,
        'failed': 0,
        'skipped': 0,
        'details': []
    }

    for user in users:
        result = send_digest_to_user(user, base_url)

        if result['success']:
            # Count as sent if we sent any publications (new or ICYMI)
            total_pubs = result.get('new_sent', 0) + result.get('icymi_count', 0)
            if total_pubs > 0:
                results['sent'] += 1
            else:
                results['skipped'] += 1
        else:
            results['failed'] += 1

        results['details'].append({
            'email': user.email,
            **result
        })

    logger.info(f"Digest process complete: {results['sent']} sent, {results['failed']} failed, {results['skipped']} skipped")
    return results
