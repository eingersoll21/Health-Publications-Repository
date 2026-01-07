"""
WHO Publications Scraper for the Global Health Publications Tracker.

This module collects publications from the World Health Organization API,
extracts metadata, categorizes them by health program areas, and saves them
to the database.

Uses the WHO Publications API for reliable data access.
"""

import logging
import time
import re
from datetime import datetime, date
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

from app.models import db, Publication, PublicationProgramArea, PublicationSubtopic, PublicationRegion, ScraperLog
from app.config import Config, PROGRAM_AREAS, REGIONS_AND_COUNTRIES

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base URL for WHO website
WHO_BASE_URL = "https://www.who.int"
WHO_API_URL = "https://www.who.int/api/hubs/publications"

# Headers for API requests
HEADERS = {
    "User-Agent": "CHAI-Health-Tracker/1.0 (Health Publications Research Tool)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}

# Number of publications to fetch from API
MAX_PUBLICATIONS = 100


def fetch_page(url):
    """
    Fetch a page from WHO website with error handling.

    Args:
        url: URL to fetch

    Returns:
        BeautifulSoup object or None if fetch failed
    """
    try:
        logger.info(f"Fetching: {url}")
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return BeautifulSoup(response.text, "html.parser")
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None


def extract_publications_from_listing(soup, source_type="publication"):
    """
    Extract publication links and basic info from a WHO listing page.

    Args:
        soup: BeautifulSoup object of listing page
        source_type: Type of content ('publication' or 'news')

    Returns:
        List of dictionaries with basic publication info
    """
    publications = []

    # WHO uses different structures for different pages
    # Try multiple selectors to find publication items
    selectors = [
        "div.list-view--item",
        "div.sf-list-vertical__item",
        "article.list-view--item",
        "div.vertical-list-item",
        "a.link-container",
    ]

    items = []
    for selector in selectors:
        items = soup.select(selector)
        if items:
            logger.info(f"Found {len(items)} items using selector: {selector}")
            break

    if not items:
        # Try finding any links to publication pages
        items = soup.select("a[href*='/publications/']")
        logger.info(f"Fallback: Found {len(items)} publication links")

    for item in items[:20]:  # Limit to 20 items per page
        try:
            pub_info = {}

            # Extract link
            link = item if item.name == "a" else item.select_one("a")
            if link and link.get("href"):
                href = link.get("href")
                pub_info["url"] = urljoin(WHO_BASE_URL, href)

                # Generate external ID from URL
                pub_info["external_id"] = href.strip("/").split("/")[-1]

            # Extract title
            title_elem = item.select_one("h3, h4, .title, .heading, span.text")
            if title_elem:
                pub_info["title"] = title_elem.get_text(strip=True)
            elif link:
                pub_info["title"] = link.get_text(strip=True)

            # Extract date if available
            date_elem = item.select_one("time, .date, .timestamp, span.date")
            if date_elem:
                date_text = date_elem.get("datetime") or date_elem.get_text(strip=True)
                pub_info["date_text"] = date_text

            # Extract description/summary if available
            desc_elem = item.select_one("p, .description, .summary, .excerpt")
            if desc_elem:
                pub_info["summary"] = desc_elem.get_text(strip=True)

            pub_info["source_type"] = source_type

            # Only add if we have at least a title and URL
            if pub_info.get("title") and pub_info.get("url"):
                publications.append(pub_info)

        except Exception as e:
            logger.warning(f"Error extracting item: {e}")
            continue

    return publications


def parse_publication_page(url):
    """
    Extract detailed information from a single publication page.

    Args:
        url: URL of the publication page

    Returns:
        Dictionary with publication details or None if parsing failed
    """
    soup = fetch_page(url)
    if not soup:
        return None

    details = {"url": url}

    try:
        # Extract title
        title_elem = soup.select_one("h1, .page-title, .publication-title")
        if title_elem:
            details["title"] = title_elem.get_text(strip=True)

        # Extract abstract/overview
        abstract_selectors = [
            "div.sf-body",
            "div.publication-overview",
            "div.page-content p",
            "article p",
            "div.content-main p",
        ]
        for selector in abstract_selectors:
            abstract_elem = soup.select_one(selector)
            if abstract_elem:
                # Get text from first few paragraphs
                paragraphs = soup.select(selector)[:3]
                abstract_text = " ".join(p.get_text(strip=True) for p in paragraphs)
                if len(abstract_text) > 50:  # Only use if substantial
                    details["abstract"] = abstract_text[:2000]  # Limit length
                    break

        # Extract publication date
        date_selectors = [
            "time",
            "span.date",
            "div.publication-date",
            "meta[property='article:published_time']",
        ]
        for selector in date_selectors:
            date_elem = soup.select_one(selector)
            if date_elem:
                date_str = date_elem.get("datetime") or date_elem.get("content") or date_elem.get_text(strip=True)
                parsed_date, is_ahead_of_print = parse_date(date_str)
                if parsed_date:
                    details["publication_date"] = parsed_date
                    details["is_ahead_of_print"] = is_ahead_of_print
                    break

        # Extract authors if available
        author_elem = soup.select_one("div.authors, span.author, meta[name='author']")
        if author_elem:
            details["authors"] = author_elem.get("content") or author_elem.get_text(strip=True)

        # Extract publication type
        type_elem = soup.select_one("span.type, div.publication-type, .document-type")
        if type_elem:
            details["publication_type"] = type_elem.get_text(strip=True)
        else:
            # Infer from URL
            if "/guidelines" in url.lower():
                details["publication_type"] = "Guideline"
            elif "/technical" in url.lower():
                details["publication_type"] = "Technical Document"
            elif "/news" in url.lower() or "/release" in url.lower():
                details["publication_type"] = "News Release"
            else:
                details["publication_type"] = "Publication"

        return details

    except Exception as e:
        logger.error(f"Error parsing publication page {url}: {e}")
        return None


def parse_date(date_str):
    """
    Parse various date formats into a date object.

    WHO publications are always officially published when they appear on the site,
    so is_ahead_of_print is always False for WHO content.

    Args:
        date_str: Date string in various formats

    Returns:
        Tuple of (datetime.date or None, is_ahead_of_print boolean)
    """
    if not date_str:
        return None, False

    date_formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y/%m/%d",
    ]

    # Clean up the date string
    date_str = date_str.strip()

    parsed_date = None
    for fmt in date_formats:
        try:
            parsed_date = datetime.strptime(date_str[:19], fmt).date()
            break
        except ValueError:
            continue

    # Try to extract year at minimum
    if not parsed_date:
        year_match = re.search(r"20[0-9]{2}", date_str)
        if year_match:
            try:
                parsed_date = datetime(int(year_match.group()), 1, 1).date()
            except ValueError:
                pass

    # WHO publications are always published (not ahead-of-print)
    return parsed_date, False


def categorize_publication(title, abstract=None):
    """
    Determine which CHAI program areas and subtopics a publication is relevant to.

    Checks the title and abstract against keywords for each program area
    and its subtopics, calculating relevance scores.

    Args:
        title: Publication title
        abstract: Publication abstract/summary (optional)

    Returns:
        Tuple of (program_areas, subtopics) where:
        - program_areas: Dictionary mapping program_area_key to relevance_score
        - subtopics: Dictionary mapping (program_area_key, subtopic_key) to relevance_score
    """
    program_areas = {}
    subtopics = {}

    # Combine title and abstract for searching
    text = (title or "").lower()
    if abstract:
        text += " " + abstract.lower()

    for area_key, area_info in PROGRAM_AREAS.items():
        # Check program-level keywords
        program_keywords = area_info.get("keywords", [])
        program_matches = 0

        for keyword in program_keywords:
            pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
            if re.search(pattern, text):
                program_matches += 1

        # Check subtopic keywords
        area_subtopics = area_info.get("subtopics", {})
        subtopic_matched = False

        for subtopic_key, subtopic_info in area_subtopics.items():
            subtopic_keywords = subtopic_info.get("keywords", [])
            subtopic_matches = 0

            for keyword in subtopic_keywords:
                pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
                if re.search(pattern, text):
                    subtopic_matches += 1

            if subtopic_matches > 0:
                # Calculate subtopic score
                score = int((subtopic_matches / len(subtopic_keywords)) * 100)
                score = min(100, score + (subtopic_matches * 5))

                if score >= Config.MIN_RELEVANCE_SCORE:
                    subtopics[(area_key, subtopic_key)] = score
                    subtopic_matched = True

        # Calculate program area score (program keywords + any subtopic match)
        total_matches = program_matches + (1 if subtopic_matched else 0)
        if total_matches > 0:
            score = int((program_matches / max(len(program_keywords), 1)) * 100)
            score = min(100, score + (program_matches * 5) + (20 if subtopic_matched else 0))

            if score >= Config.MIN_RELEVANCE_SCORE:
                program_areas[area_key] = score

    return program_areas, subtopics


def detect_regions(title, abstract=None):
    """
    Detect which geographic regions are mentioned in a publication.

    Searches title and abstract for country names and region keywords.

    Args:
        title: Publication title
        abstract: Publication abstract/summary (optional)

    Returns:
        Dictionary mapping region_key to list of matched terms
    """
    results = {}

    # Combine title and abstract for searching
    text = (title or "")
    if abstract:
        text += " " + abstract

    for region_key, region_info in REGIONS_AND_COUNTRIES.items():
        # Skip 'global' region - it has no keywords/countries
        if region_key == "global":
            continue

        matched_terms = []

        # Check region-level keywords
        for keyword in region_info.get("keywords", []):
            pattern = r'\b' + re.escape(keyword) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                matched_terms.append(keyword)

        # Check country names
        for country in region_info.get("countries", []):
            pattern = r'\b' + re.escape(country) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                matched_terms.append(country)

        if matched_terms:
            results[region_key] = matched_terms

    return results


def publication_exists(source, external_id):
    """
    Check if a publication already exists in the database.

    Args:
        source: Source identifier ('WHO')
        external_id: External ID from the source

    Returns:
        True if publication exists, False otherwise
    """
    return Publication.query.filter_by(
        source=source,
        external_id=external_id
    ).first() is not None


def save_publication(pub_data, program_areas, subtopics=None, regions=None):
    """
    Save a publication and its program area, subtopic, and region links to the database.

    Args:
        pub_data: Dictionary with publication data
        program_areas: Dictionary mapping program_area_key to relevance_score
        subtopics: Dictionary mapping (program_area_key, subtopic_key) to relevance_score (optional)
        regions: Dictionary mapping region_key to list of matched terms (optional)

    Returns:
        The saved Publication object or None if save failed
    """
    try:
        # Create publication record
        publication = Publication(
            source="WHO",
            external_id=pub_data.get("external_id", ""),
            title=pub_data.get("title", ""),
            abstract=pub_data.get("abstract"),
            authors=pub_data.get("authors"),
            publication_date=pub_data.get("publication_date"),
            is_ahead_of_print=pub_data.get("is_ahead_of_print", False),
            url=pub_data.get("url", ""),
            publication_type=pub_data.get("publication_type"),
        )
        db.session.add(publication)
        db.session.flush()  # Get the ID without committing

        # Create program area links
        for area_key, score in program_areas.items():
            link = PublicationProgramArea(
                publication_id=publication.id,
                program_area_key=area_key,
                relevance_score=score
            )
            db.session.add(link)

        # Create subtopic links
        if subtopics:
            for (area_key, subtopic_key), score in subtopics.items():
                subtopic_link = PublicationSubtopic(
                    publication_id=publication.id,
                    program_area_key=area_key,
                    subtopic_key=subtopic_key,
                    relevance_score=score
                )
                db.session.add(subtopic_link)

        # Create region links
        if regions:
            for region_key, matched_terms in regions.items():
                region_link = PublicationRegion(
                    publication_id=publication.id,
                    region_key=region_key,
                    matched_terms=", ".join(matched_terms)
                )
                db.session.add(region_link)

        db.session.commit()
        logger.info(f"Saved publication: {publication.title[:50]}...")
        return publication

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving publication: {e}")
        return None


def fetch_publications_from_api():
    """
    Fetch publications from the WHO Publications API.

    Returns:
        List of dictionaries with publication data
    """
    logger.info(f"Fetching publications from WHO API (max {MAX_PUBLICATIONS})...")

    try:
        params = {
            '$top': MAX_PUBLICATIONS,
            '$orderby': 'PublicationDate desc',
        }

        response = requests.get(WHO_API_URL, headers=HEADERS, params=params, timeout=60)
        response.raise_for_status()

        data = response.json()
        publications = data.get('value', [])

        logger.info(f"WHO API returned {len(publications)} publications")
        return publications

    except requests.RequestException as e:
        logger.error(f"Failed to fetch from WHO API: {e}")
        return []


def parse_api_publication(api_pub):
    """
    Parse a publication from the WHO API response into our format.

    Args:
        api_pub: Dictionary from WHO API response

    Returns:
        Dictionary with publication data in our format
    """
    # Extract and clean abstract from Overview, Summary, or MetaDescription
    abstract = None
    overview = api_pub.get('Overview', '')
    if overview:
        # Strip HTML tags from overview
        soup = BeautifulSoup(overview, 'html.parser')
        abstract = soup.get_text(strip=True)[:2000]
    elif api_pub.get('Summary'):
        abstract = api_pub.get('Summary')[:2000]
    elif api_pub.get('MetaDescription'):
        abstract = api_pub.get('MetaDescription')[:2000]

    # Parse publication date
    pub_date = None
    is_ahead_of_print = False
    date_str = api_pub.get('PublicationDate') or api_pub.get('PublicationDateAndTime')
    if date_str:
        pub_date, is_ahead_of_print = parse_date(date_str)

    # Build full URL
    url_name = api_pub.get('ItemDefaultUrl', '') or api_pub.get('UrlName', '')
    if url_name and not url_name.startswith('http'):
        url = f"{WHO_BASE_URL}/publications/i/item{url_name}" if not url_name.startswith('/') else f"{WHO_BASE_URL}/publications/i/item{url_name}"
    else:
        url = url_name

    # Use IRISID or Id as external_id
    external_id = api_pub.get('IRISID') or api_pub.get('Id') or url_name.strip('/')

    return {
        'external_id': str(external_id),
        'title': api_pub.get('Title', ''),
        'abstract': abstract,
        'authors': api_pub.get('Editors'),
        'publication_date': pub_date,
        'is_ahead_of_print': is_ahead_of_print,
        'url': url,
        'publication_type': api_pub.get('Subtitle') or 'Publication',
    }


def fetch_who_publications():
    """
    Main function to fetch publications from WHO API.

    Fetches publications from the WHO API, extracts details,
    categorizes them, and returns a list of publication data.

    Returns:
        List of dictionaries with publication data and program areas
    """
    logger.info("Starting WHO scraper...")

    all_publications = []
    seen_ids = set()

    # Fetch from WHO API
    api_publications = fetch_publications_from_api()

    for api_pub in api_publications:
        # Parse API response
        pub_data = parse_api_publication(api_pub)

        # Skip duplicates
        if pub_data['external_id'] in seen_ids:
            continue
        seen_ids.add(pub_data['external_id'])

        # Skip if no title
        if not pub_data.get('title'):
            continue

        # Categorize by program areas and subtopics
        program_areas, subtopics = categorize_publication(
            pub_data.get('title', ''),
            pub_data.get('abstract')
        )

        # Detect geographic regions
        regions = detect_regions(
            pub_data.get('title', ''),
            pub_data.get('abstract')
        )

        pub_data['program_areas'] = program_areas
        pub_data['subtopics'] = subtopics
        pub_data['regions'] = regions
        all_publications.append(pub_data)

    logger.info(f"WHO scraper found {len(all_publications)} publications total")
    return all_publications


def save_publications(publications):
    """
    Save a list of publications to the database.

    Checks for duplicates and only saves new publications.

    Args:
        publications: List of publication data dictionaries

    Returns:
        Tuple of (saved_count, skipped_count)
    """
    saved = 0
    skipped = 0

    for pub_data in publications:
        external_id = pub_data.get("external_id", "")

        # Skip if already exists
        if publication_exists("WHO", external_id):
            logger.debug(f"Skipping existing publication: {external_id}")
            skipped += 1
            continue

        # Skip if no relevant program areas
        program_areas = pub_data.get("program_areas", {})
        if not program_areas:
            logger.debug(f"Skipping publication with no relevant program areas: {pub_data.get('title', '')[:50]}")
            skipped += 1
            continue

        # Get detected subtopics and regions
        subtopics = pub_data.get("subtopics", {})
        regions = pub_data.get("regions", {})

        # Save to database
        if save_publication(pub_data, program_areas, subtopics, regions):
            saved += 1
        else:
            skipped += 1

    logger.info(f"Saved {saved} new publications, skipped {skipped}")
    return saved, skipped


def run_who_scraper():
    """
    Run the complete WHO scraping process.

    Fetches publications, filters by relevance, and saves to database.
    Logs the run to ScraperLog for monitoring.

    Returns:
        Dictionary with scraping results
    """
    logger.info("=" * 50)
    logger.info("Starting WHO Publications Scraper")
    logger.info("=" * 50)

    try:
        # Fetch publications
        publications = fetch_who_publications()

        # Save to database
        saved, skipped = save_publications(publications)

        # Log the scraper run
        scraper_log = ScraperLog(
            source='WHO',
            publications_found=len(publications),
            publications_new=saved
        )
        db.session.add(scraper_log)
        db.session.commit()

        # Compile results
        results = {
            "source": "WHO",
            "total_found": len(publications),
            "saved": saved,
            "skipped": skipped,
            "status": "success"
        }

        logger.info(f"WHO scraper completed: {saved} saved, {skipped} skipped")
        return results

    except Exception as e:
        logger.error(f"WHO scraper failed: {e}")
        return {
            "source": "WHO",
            "status": "error",
            "error": str(e)
        }
