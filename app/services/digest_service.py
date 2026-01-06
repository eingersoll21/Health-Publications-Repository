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
from datetime import datetime, timedelta
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

# Constants for digest sections
MAX_NEW_PUBLICATIONS = 7
MAX_ICYMI_PUBLICATIONS = 5
TOTAL_MAX_PUBLICATIONS = 12

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
    # {program_key: {'subtopics': set(), 'want_all': bool, 'region_filter': set()}}
    prefs_by_program = {}
    for pref in program_prefs:
        program_key = pref['program_area_key']
        subtopic_key = pref['subtopic_key']
        region_key = pref['region_key']

        if program_key not in prefs_by_program:
            prefs_by_program[program_key] = {
                'subtopics': set(),
                'want_all': False,
                'region_filters': set()
            }

        if subtopic_key is None:
            prefs_by_program[program_key]['want_all'] = True
        else:
            prefs_by_program[program_key]['subtopics'].add(subtopic_key)

        if region_key:
            prefs_by_program[program_key]['region_filters'].add(region_key)

    # Calculate date cutoff
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)

    # Get publication IDs already sent to this user
    sent_pub_ids = db.session.query(DigestLog.publication_id).filter(
        DigestLog.user_id == user.id
    ).subquery()

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
                _add_publication_to_dict(pub_dict, pub, pub_area, pref_data['region_filters'])

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
                _add_subtopic_publication_to_dict(pub_dict, pub, pub_subtopic, pref_data['region_filters'])

    # Apply region filter if specified (remove publications not matching region)
    if any(pref_data['region_filters'] for pref_data in prefs_by_program.values()):
        pub_dict = _filter_by_region(pub_dict, prefs_by_program)

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


def _add_publication_to_dict(pub_dict, pub, pub_area, region_filters):
    """Add a publication matched by program area to the dict."""
    if pub.id not in pub_dict:
        pub_dict[pub.id] = {
            'publication': pub,
            'program_areas': [],
            'subtopics': [],
            'regions': [],
            'region_filters': region_filters  # Track which region filters apply
        }
    pub_dict[pub.id]['program_areas'].append({
        'key': pub_area.program_area_key,
        'name': get_program_area_name(pub_area.program_area_key),
        'score': pub_area.relevance_score
    })


def _add_subtopic_publication_to_dict(pub_dict, pub, pub_subtopic, region_filters):
    """Add a publication matched by subtopic to the dict."""
    if pub.id not in pub_dict:
        pub_dict[pub.id] = {
            'publication': pub,
            'program_areas': [],
            'subtopics': [],
            'regions': [],
            'region_filters': region_filters
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


def _filter_by_region(pub_dict, prefs_by_program):
    """Filter publications to only include those matching region filters."""
    filtered_dict = {}

    for pub_id, pub_data in pub_dict.items():
        region_filters = pub_data.get('region_filters', set())

        # If no region filter, include the publication
        if not region_filters:
            filtered_dict[pub_id] = pub_data
            continue

        # Check if publication matches any of the region filters
        pub_regions = PublicationRegion.query.filter_by(publication_id=pub_id).all()
        pub_region_keys = set(r.region_key for r in pub_regions)

        if pub_region_keys.intersection(region_filters):
            filtered_dict[pub_id] = pub_data
            # Add region info
            for region in pub_regions:
                if region.region_key in region_filters:
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
    ).subquery()

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
    results.sort(key=lambda x: x['publication'].publication_date or datetime.min, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} country watch publications for user {user.email}")
    return results


def get_publications_for_user(user, days_back=30, max_publications=None):
    """
    Find all publications matching user's subscriptions that haven't been sent yet.

    Combines results from:
    1. Program Subscriptions (health topic-based)
    2. Country Watch (geography-based)

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

    # Combine and deduplicate
    pub_dict = {}

    for pub_data in program_pubs:
        pub_id = pub_data['publication'].id
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


def get_previously_sent_publications(user, lookback_days, max_publications=MAX_ICYMI_PUBLICATIONS, exclude_ids=None):
    """
    Get publications that were previously sent to this user within the lookback period.

    Args:
        user: User object
        lookback_days: How many days back to look for previously sent publications
        max_publications: Maximum number of publications to return
        exclude_ids: Set of publication IDs to exclude (e.g., those in Section 1)

    Returns:
        List of dicts with publication data, program areas, and regions
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

    # Get the publications with their program areas
    pub_dict = {}
    for pub_id in sent_pub_ids:
        pub = Publication.query.get(pub_id)
        if not pub:
            continue

        pub_dict[pub.id] = {
            'publication': pub,
            'program_areas': [],
            'subtopics': [],
            'regions': []
        }

        # Get program areas
        areas = PublicationProgramArea.query.filter_by(publication_id=pub_id).all()
        for area in areas:
            pub_dict[pub.id]['program_areas'].append({
                'key': area.program_area_key,
                'name': get_program_area_name(area.program_area_key),
                'score': area.relevance_score
            })

        # Get subtopics
        subtopics = PublicationSubtopic.query.filter_by(publication_id=pub_id).all()
        for st in subtopics:
            pub_dict[pub.id]['subtopics'].append({
                'program_key': st.program_area_key,
                'subtopic_key': st.subtopic_key,
                'name': get_subtopic_name(st.program_area_key, st.subtopic_key),
                'score': st.relevance_score
            })

        # Get regions
        regions = PublicationRegion.query.filter_by(publication_id=pub_id).all()
        for region in regions:
            pub_dict[pub.id]['regions'].append({
                'key': region.region_key,
                'name': get_region_name(region.region_key),
                'matched_terms': region.matched_terms
            })

    # Convert to list, sort by relevance score, and limit
    results = list(pub_dict.values())
    results.sort(key=_get_max_score, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} previously sent publications for user {user.email}")
    return results


def format_publication_for_display(pub_data):
    """
    Format a publication dict for display in the digest.

    Args:
        pub_data: Dict with 'publication', 'program_areas', 'subtopics', 'regions'

    Returns:
        Dict formatted for template display
    """
    pub = pub_data['publication']

    # Get the highest relevance score
    max_score = _get_max_score(pub_data)

    # Get region and subtopic names for display
    region_names = [r['name'] for r in pub_data.get('regions', [])]
    subtopic_names = [st['name'] for st in pub_data.get('subtopics', [])]

    return {
        'title': pub.title,
        'url': pub.url,
        'source': pub.source,
        'date': pub.publication_date,
        'abstract': truncate_text(pub.abstract, 200) if pub.abstract else None,
        'authors': pub.authors,
        'relevance_score': max_score,
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

    # Format publications for display
    new_pubs_formatted = [format_publication_for_display(p) for p in new_publications]
    icymi_pubs_formatted = [format_publication_for_display(p) for p in icymi_publications]

    # Generate unsubscribe token
    unsubscribe_token = generate_unsubscribe_token(user)
    unsubscribe_url = f"{base_url}/unsubscribe/{unsubscribe_token}"
    preferences_url = f"{base_url}/preferences"

    # Get user's subscribed areas for footer
    subscribed_areas = [get_program_area_name(key) for key in user.get_selected_program_keys()]

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
        'new_publications': new_pubs_formatted,
        'icymi_publications': icymi_pubs_formatted,
        'new_count': len(new_publications),
        'icymi_count': len(icymi_publications),
        'total_count': total_count,
        'has_new_publications': len(new_publications) > 0,
        'has_icymi_publications': len(icymi_publications) > 0,
        'no_new_pubs_message': no_new_pubs_message,
        'icymi_header': icymi_header,
        'start_date': start_date.strftime('%B %d, %Y'),
        'end_date': end_date.strftime('%B %d, %Y'),
        'subscribed_areas': subscribed_areas,
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
    lines = [
        "CHAI Health Publications Digest",
        "=" * 40,
        f"Date: {context['end_date']}",
        "",
    ]

    # Section 1: New This Week
    if context['has_new_publications']:
        lines.append("NEW THIS WEEK")
        lines.append("-" * 20)
        lines.append(f"{context['new_count']} new publication{'s' if context['new_count'] != 1 else ''}")
        lines.append("")

        for pub in context['new_publications']:
            lines.append(f"* {pub['title']}")
            lines.append(f"  Source: {pub['source']}")
            if pub['date']:
                lines.append(f"  Date: {pub['date'].strftime('%Y-%m-%d')}")
            if pub.get('subtopics'):
                lines.append(f"  Topics: {', '.join(pub['subtopics'])}")
            if pub.get('regions'):
                lines.append(f"  Regions: {', '.join(pub['regions'])}")
            lines.append(f"  Link: {pub['url']}")
            if pub['abstract']:
                lines.append(f"  {pub['abstract']}")
            lines.append("")
    else:
        lines.append(context['no_new_pubs_message'])
        lines.append("")

    # Section 2: In Case You Missed It
    if context['has_icymi_publications']:
        lines.append("")
        lines.append(context['icymi_header'].upper())
        lines.append("-" * 20)
        lines.append(f"{context['icymi_count']} publication{'s' if context['icymi_count'] != 1 else ''}")
        lines.append("")

        for pub in context['icymi_publications']:
            lines.append(f"* {pub['title']}")
            lines.append(f"  Source: {pub['source']}")
            if pub['date']:
                lines.append(f"  Date: {pub['date'].strftime('%Y-%m-%d')}")
            if pub.get('subtopics'):
                lines.append(f"  Topics: {', '.join(pub['subtopics'])}")
            if pub.get('regions'):
                lines.append(f"  Regions: {', '.join(pub['regions'])}")
            lines.append(f"  Link: {pub['url']}")
            if pub['abstract']:
                lines.append(f"  {pub['abstract']}")
            lines.append("")

    lines.extend([
        "",
        "-" * 40,
    ])

    # Show subscription info
    if context.get('subscribed_areas'):
        lines.append(f"Program areas: {', '.join(context['subscribed_areas'])}")
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

    The digest has two sections:
    1. "New This Week" - up to 7 new publications
    2. "In Case You Missed It" - up to 5 previously sent publications

    Args:
        user: User object
        base_url: Base URL for links. Defaults to Config.BASE_URL.

    Returns:
        Dictionary with results: {success, new_sent, icymi_count, error}
    """
    if base_url is None:
        base_url = Config.BASE_URL
    logger.info(f"Preparing digest for user {user.email}")

    # Get new publications for this user (Section 1)
    new_publications = get_publications_for_user(user, max_publications=MAX_NEW_PUBLICATIONS)

    # Get IDs of new publications to exclude from ICYMI
    new_pub_ids = set(p['publication'].id for p in new_publications)

    # Get lookback period based on user's frequency
    lookback_days = ICYMI_LOOKBACK.get(user.digest_frequency, 14)

    # Get previously sent publications (Section 2)
    icymi_publications = get_previously_sent_publications(
        user,
        lookback_days=lookback_days,
        max_publications=MAX_ICYMI_PUBLICATIONS,
        exclude_ids=new_pub_ids
    )

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
            # Log only the NEW publications (not ICYMI, as those were already logged)
            batch_id = str(uuid.uuid4())[:8]
            for pub_data in new_publications:
                log = DigestLog(
                    user_id=user.id,
                    publication_id=pub_data['publication'].id,
                    digest_batch_id=batch_id
                )
                db.session.add(log)

            # Update user's last_digest_sent
            user.last_digest_sent = datetime.utcnow()
            db.session.commit()

            logger.info(f"Digest sent to {user.email}: {len(new_publications)} new, {len(icymi_publications)} ICYMI")
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
