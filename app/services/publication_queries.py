"""
Shared publication query helpers for the Global Health Publications Tracker.

This module provides reusable functions for querying publications based on
user preferences, with proper handling of:
- Program area subscriptions (with subtopic filtering)
- Location filters (region/country)
- Country watch subscriptions

Used by both the home dashboard (routes.py) and email digests (digest_service.py).
"""

from datetime import datetime, timedelta
from sqlalchemy import or_

from app.models import (
    db, Publication, PublicationProgramArea, PublicationSubtopic,
    PublicationRegion, DigestLog
)
from app.config import get_program_area_name, get_region_name, get_subtopic_name


def get_user_preference_structure(user):
    """
    Get user's program preferences organized for querying.

    Returns a dict organized by program area:
    {
        'hiv_aids': {
            'subtopics': {'art', 'pmtct'},  # Empty if want_all
            'want_all': False,              # True if no specific subtopics selected
            'location_type': 'all',         # 'all', 'region', or 'country'
            'location_values': set()        # Region keys or country names
        },
        ...
    }
    """
    program_prefs = user.get_program_preferences_detail()

    if not program_prefs:
        return {}

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

        # Handle location filters
        for loc in locations:
            prefs_by_program[program_key]['location_type'] = loc['location_type']
            prefs_by_program[program_key]['location_values'].add(loc['location_value'])

    return prefs_by_program


def get_matching_publications(user, days_back=7, max_publications=10, exclude_sent=False):
    """
    Find publications matching user's program subscriptions with proper subtopic filtering.

    This is the CORRECT logic that respects subtopic selections:
    - If user selected specific subtopics → only return publications tagged with those subtopics
    - If user selected 'All Subtopics' → return all publications from that program area
    - Also applies location filters if set

    Args:
        user: User object
        days_back: Only include publications from the last N days
        max_publications: Maximum number of publications to return
        exclude_sent: If True, exclude publications already sent to this user

    Returns:
        List of dicts with publication data and metadata
    """
    prefs_by_program = get_user_preference_structure(user)

    if not prefs_by_program:
        return []

    # Calculate date cutoff
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)

    # Get publication IDs already sent to this user (if excluding)
    sent_pub_ids = set()
    if exclude_sent:
        sent_logs = db.session.query(DigestLog.publication_id).filter(
            DigestLog.user_id == user.id
        ).all()
        sent_pub_ids = set(log[0] for log in sent_logs)

    pub_dict = {}

    for program_key, pref_data in prefs_by_program.items():
        if pref_data['want_all']:
            # User wants ALL publications from this program area
            matching_pubs = db.session.query(
                Publication,
                PublicationProgramArea
            ).join(
                PublicationProgramArea,
                Publication.id == PublicationProgramArea.publication_id
            ).filter(
                PublicationProgramArea.program_area_key == program_key,
                Publication.publication_date >= cutoff_date.date()
            ).all()

            for pub, pub_area in matching_pubs:
                if exclude_sent and pub.id in sent_pub_ids:
                    continue
                _add_publication_to_dict(
                    pub_dict, pub, pub_area, program_key,
                    pref_data['location_type'], pref_data['location_values']
                )

        # Get publications matching specific subtopics (even if want_all is True,
        # we still want to capture subtopic matches for display purposes)
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
                Publication.publication_date >= cutoff_date.date()
            ).all()

            for pub, pub_subtopic in subtopic_pubs:
                if exclude_sent and pub.id in sent_pub_ids:
                    continue
                _add_subtopic_publication_to_dict(
                    pub_dict, pub, pub_subtopic,
                    pref_data['location_type'], pref_data['location_values']
                )

    # Apply location filter if any preferences have location filters
    if any(pref_data['location_values'] for pref_data in prefs_by_program.values()):
        pub_dict = _filter_by_location(pub_dict)

    # Convert to list, sort by date, and limit
    results = list(pub_dict.values())
    results.sort(key=lambda x: x['publication'].publication_date or datetime.min.date(), reverse=True)
    results = results[:max_publications]

    return results


def _add_publication_to_dict(pub_dict, pub, pub_area, program_key, location_type, location_values):
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

    # Check if this program area is already added
    if not any(pa['key'] == pub_area.program_area_key for pa in pub_dict[pub.id]['program_areas']):
        pub_dict[pub.id]['program_areas'].append({
            'key': pub_area.program_area_key,
            'name': get_program_area_name(pub_area.program_area_key),
            'score': pub_area.relevance_score
        })

    # Also fetch subtopics for this publication (even when matched by program area)
    pub_subtopics = PublicationSubtopic.query.filter_by(
        publication_id=pub.id,
        program_area_key=program_key
    ).all()
    for st in pub_subtopics:
        if not any(existing['subtopic_key'] == st.subtopic_key for existing in pub_dict[pub.id]['subtopics']):
            pub_dict[pub.id]['subtopics'].append({
                'program_key': st.program_area_key,
                'subtopic_key': st.subtopic_key,
                'name': get_subtopic_name(st.program_area_key, st.subtopic_key),
                'score': st.relevance_score
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
        if area and not any(pa['key'] == area.program_area_key for pa in pub_dict[pub.id]['program_areas']):
            pub_dict[pub.id]['program_areas'].append({
                'key': area.program_area_key,
                'name': get_program_area_name(area.program_area_key),
                'score': area.relevance_score
            })

    # Check if this subtopic is already added
    if not any(st['subtopic_key'] == pub_subtopic.subtopic_key for st in pub_dict[pub.id]['subtopics']):
        pub_dict[pub.id]['subtopics'].append({
            'program_key': pub_subtopic.program_area_key,
            'subtopic_key': pub_subtopic.subtopic_key,
            'name': get_subtopic_name(pub_subtopic.program_area_key, pub_subtopic.subtopic_key),
            'score': pub_subtopic.relevance_score
        })


def _filter_by_location(pub_dict):
    """Filter publications to only include those matching location filters."""
    filtered_dict = {}

    for pub_id, pub_data in pub_dict.items():
        location_type = pub_data.get('location_type', 'all')
        location_values = pub_data.get('location_values', set())

        # If no location filter, include the publication
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
                        if not any(r['key'] == region.region_key for r in pub_data['regions']):
                            pub_data['regions'].append({
                                'key': region.region_key,
                                'name': get_region_name(region.region_key),
                                'matched_terms': region.matched_terms
                            })

        elif location_type == 'country':
            # Filter by country - publication must mention ANY of the selected countries
            for region in pub_regions:
                if region.matched_terms:
                    matched_terms = set(region.matched_terms.split(', '))
                    if matched_terms.intersection(location_values):
                        filtered_dict[pub_id] = pub_data
                        if not any(r['key'] == region.region_key for r in pub_data['regions']):
                            pub_data['regions'].append({
                                'key': region.region_key,
                                'name': get_region_name(region.region_key),
                                'matched_terms': region.matched_terms
                            })

    return filtered_dict


def get_publication_counts_by_program(user):
    """
    Get total publication counts for each of the user's subscribed program areas.

    Returns:
        Dict mapping program_key to {'name': str, 'count': int}
    """
    prefs_by_program = get_user_preference_structure(user)

    if not prefs_by_program:
        return {}

    program_counts = {}
    for program_key in prefs_by_program.keys():
        count = Publication.query.join(
            PublicationProgramArea
        ).filter(
            PublicationProgramArea.program_area_key == program_key
        ).distinct().count()

        program_counts[program_key] = {
            'name': get_program_area_name(program_key),
            'count': count
        }

    return program_counts
