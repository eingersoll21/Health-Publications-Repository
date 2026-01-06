"""
Digest Service for the CHAI Health Publications Tracker.

This module handles creating and sending email digests:
- Finding relevant publications for each user
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
from app.config import Config, PROGRAM_AREAS, get_program_area_name, get_region_name, get_subtopic_name
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


def get_publications_for_user(user, days_back=30, max_publications=None):
    """
    Find publications matching user's preferences based on their filter_mode
    that haven't been sent to them yet.

    Filter modes:
    - program_only: Match publications by program areas only
    - region_only: Match publications by regions only
    - program_and_region: Match publications that have BOTH matching program AND region

    Args:
        user: User object
        days_back: Only include publications from the last N days
        max_publications: Maximum number of publications to return

    Returns:
        List of dicts with publication data, program areas, and regions
    """
    if max_publications is None:
        max_publications = Config.MAX_PUBLICATIONS_PER_DIGEST

    # Get user's preferences
    selected_areas = user.get_selected_program_keys()
    selected_regions = user.get_selected_region_keys()
    filter_mode = user.filter_mode

    # Get detailed program preferences (with subtopic info)
    program_prefs = user.get_program_preferences_detail()

    # Validate that user has required preferences for their filter mode
    if filter_mode == 'program_only' and not selected_areas:
        logger.info(f"User {user.email} has program_only mode but no program areas selected")
        return []
    elif filter_mode == 'region_only' and not selected_regions:
        logger.info(f"User {user.email} has region_only mode but no regions selected")
        return []
    elif filter_mode == 'program_and_region' and (not selected_areas or not selected_regions):
        logger.info(f"User {user.email} has program_and_region mode but missing preferences")
        return []

    # Determine which program areas want all subtopics vs specific subtopics
    areas_want_all = set()
    specific_subtopics = []  # List of (program_key, subtopic_key) tuples
    for program_key, subtopics in program_prefs.items():
        if None in subtopics:
            areas_want_all.add(program_key)
        else:
            for subtopic_key in subtopics:
                if subtopic_key is not None:
                    specific_subtopics.append((program_key, subtopic_key))

    # Calculate date cutoff
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)

    # Get publication IDs already sent to this user
    sent_pub_ids = db.session.query(DigestLog.publication_id).filter(
        DigestLog.user_id == user.id
    ).subquery()

    # Build the query based on filter mode
    if filter_mode == 'program_only':
        # Match by program areas with subtopic support
        pub_dict = {}

        # First, get publications matching program areas where user wants ALL subtopics
        if areas_want_all:
            matching_pubs = db.session.query(
                Publication,
                PublicationProgramArea
            ).join(
                PublicationProgramArea,
                Publication.id == PublicationProgramArea.publication_id
            ).filter(
                PublicationProgramArea.program_area_key.in_(areas_want_all),
                Publication.scraped_at >= cutoff_date,
                ~Publication.id.in_(sent_pub_ids)
            ).order_by(
                PublicationProgramArea.relevance_score.desc(),
                Publication.publication_date.desc()
            ).all()

            for pub, pub_area in matching_pubs:
                if pub.id not in pub_dict:
                    pub_dict[pub.id] = {
                        'publication': pub,
                        'program_areas': [],
                        'subtopics': [],
                        'regions': []
                    }
                pub_dict[pub.id]['program_areas'].append({
                    'key': pub_area.program_area_key,
                    'name': get_program_area_name(pub_area.program_area_key),
                    'score': pub_area.relevance_score
                })

        # Second, get publications matching specific subtopics
        if specific_subtopics:
            for program_key, subtopic_key in specific_subtopics:
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
                ).order_by(
                    PublicationSubtopic.relevance_score.desc(),
                    Publication.publication_date.desc()
                ).all()

                for pub, pub_subtopic in subtopic_pubs:
                    if pub.id not in pub_dict:
                        pub_dict[pub.id] = {
                            'publication': pub,
                            'program_areas': [],
                            'subtopics': [],
                            'regions': []
                        }
                        # Also get program area info for this publication
                        area = PublicationProgramArea.query.filter_by(
                            publication_id=pub.id,
                            program_area_key=program_key
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

        # Add region info (for display, not filtering)
        for pub_id, pub_data in pub_dict.items():
            regions = PublicationRegion.query.filter_by(publication_id=pub_id).all()
            for region in regions:
                pub_data['regions'].append({
                    'key': region.region_key,
                    'name': get_region_name(region.region_key),
                    'matched_terms': region.matched_terms
                })

    elif filter_mode == 'region_only':
        # Match by regions only (excluding 'global' which means no filter)
        filter_regions = [r for r in selected_regions if r != 'global']

        if not filter_regions or 'global' in selected_regions:
            # If global selected or no specific regions, get all recent publications
            matching_pubs = db.session.query(Publication).filter(
                Publication.scraped_at >= cutoff_date,
                ~Publication.id.in_(sent_pub_ids)
            ).order_by(
                Publication.publication_date.desc()
            ).all()

            pub_dict = {}
            for pub in matching_pubs:
                pub_dict[pub.id] = {
                    'publication': pub,
                    'program_areas': [],
                    'subtopics': [],
                    'regions': []
                }
        else:
            # Filter by specific regions
            matching_pubs = db.session.query(
                Publication,
                PublicationRegion
            ).join(
                PublicationRegion,
                Publication.id == PublicationRegion.publication_id
            ).filter(
                PublicationRegion.region_key.in_(filter_regions),
                Publication.scraped_at >= cutoff_date,
                ~Publication.id.in_(sent_pub_ids)
            ).order_by(
                Publication.publication_date.desc()
            ).all()

            pub_dict = {}
            for pub, pub_region in matching_pubs:
                if pub.id not in pub_dict:
                    pub_dict[pub.id] = {
                        'publication': pub,
                        'program_areas': [],
                        'subtopics': [],
                        'regions': []
                    }
                pub_dict[pub.id]['regions'].append({
                    'key': pub_region.region_key,
                    'name': get_region_name(pub_region.region_key),
                    'matched_terms': pub_region.matched_terms
                })

        # Add program area and subtopic info (for display, not filtering)
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

    else:  # program_and_region
        # Match publications that have BOTH matching program AND region
        # With subtopic support
        filter_regions = [r for r in selected_regions if r != 'global']

        # Build subquery for publications matching program areas/subtopics
        # Include publications from areas_want_all OR specific_subtopics
        program_pub_ids_list = []

        if areas_want_all:
            area_pubs = db.session.query(PublicationProgramArea.publication_id).filter(
                PublicationProgramArea.program_area_key.in_(areas_want_all)
            ).all()
            program_pub_ids_list.extend([p[0] for p in area_pubs])

        if specific_subtopics:
            for program_key, subtopic_key in specific_subtopics:
                subtopic_pubs = db.session.query(PublicationSubtopic.publication_id).filter(
                    PublicationSubtopic.program_area_key == program_key,
                    PublicationSubtopic.subtopic_key == subtopic_key
                ).all()
                program_pub_ids_list.extend([p[0] for p in subtopic_pubs])

        program_pub_ids_set = set(program_pub_ids_list)

        # Get publications matching regions (if not global)
        if filter_regions and 'global' not in selected_regions:
            region_pub_ids = db.session.query(PublicationRegion.publication_id).filter(
                PublicationRegion.region_key.in_(filter_regions)
            ).all()
            region_pub_ids_set = set([p[0] for p in region_pub_ids])

            # Get publications that match BOTH
            matching_ids = program_pub_ids_set.intersection(region_pub_ids_set)
            matching_pubs = db.session.query(Publication).filter(
                Publication.id.in_(matching_ids),
                Publication.scraped_at >= cutoff_date,
                ~Publication.id.in_(sent_pub_ids)
            ).order_by(
                Publication.publication_date.desc()
            ).all()
        else:
            # Global selected, just filter by program
            matching_pubs = db.session.query(Publication).filter(
                Publication.id.in_(program_pub_ids_set),
                Publication.scraped_at >= cutoff_date,
                ~Publication.id.in_(sent_pub_ids)
            ).order_by(
                Publication.publication_date.desc()
            ).all()

        pub_dict = {}
        for pub in matching_pubs:
            pub_dict[pub.id] = {
                'publication': pub,
                'program_areas': [],
                'subtopics': [],
                'regions': []
            }

        # Add program areas, subtopics, and regions info
        for pub_id, pub_data in pub_dict.items():
            areas = PublicationProgramArea.query.filter_by(publication_id=pub_id).all()
            for area in areas:
                if area.program_area_key in selected_areas:
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

            regions = PublicationRegion.query.filter_by(publication_id=pub_id).all()
            for region in regions:
                pub_data['regions'].append({
                    'key': region.region_key,
                    'name': get_region_name(region.region_key),
                    'matched_terms': region.matched_terms
                })

    # Convert to list, sort by relevance score, and limit
    results = list(pub_dict.values())

    # Sort by highest relevance score
    def get_max_score(pub_data):
        scores = [pa['score'] for pa in pub_data.get('program_areas', [])]
        scores.extend([st['score'] for st in pub_data.get('subtopics', [])])
        return max(scores) if scores else 0

    results.sort(key=get_max_score, reverse=True)
    results = results[:max_publications]

    logger.info(f"Found {len(results)} new publications for user {user.email} (filter_mode: {filter_mode})")
    return results


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

    def get_max_score(pub_data):
        scores = [pa['score'] for pa in pub_data.get('program_areas', [])]
        scores.extend([st['score'] for st in pub_data.get('subtopics', [])])
        return max(scores) if scores else 0

    results.sort(key=get_max_score, reverse=True)
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
    scores = [pa['score'] for pa in pub_data.get('program_areas', [])]
    scores.extend([st['score'] for st in pub_data.get('subtopics', [])])
    max_score = max(scores) if scores else 0

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
        'subtopics': subtopic_names
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

    # Get user's subscribed areas and regions for footer
    subscribed_areas = [get_program_area_name(key) for key in user.get_selected_program_keys()]
    subscribed_regions = [get_region_name(key) for key in user.get_selected_region_keys()]

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
        'subscribed_regions': subscribed_regions,
        'filter_mode': user.filter_mode,
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
        lines.append(f"Regions: {', '.join(context['subscribed_regions'])}")

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

    # Get all active users with at least one program preference
    active_users = User.query.filter(
        User.is_active == True
    ).all()

    for user in active_users:
        # Skip users with no program preferences
        if not user.get_selected_program_keys():
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
