"""
PubMed Scraper for the CHAI Health Publications Tracker.

This module collects research papers from PubMed using the official NCBI API
via Biopython's Entrez module. It searches for papers matching CHAI program
area keywords and saves relevant publications to the database.

NCBI Usage Guidelines:
- Maximum 3 requests per second
- Include email address in requests
- Use official API, not web scraping
"""

import logging
import time
import re
from datetime import datetime, timedelta
from Bio import Entrez

from app.models import db, Publication, PublicationProgramArea, PublicationSubtopic, PublicationRegion
from app.config import Config, PROGRAM_AREAS, REGIONS_AND_COUNTRIES

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure Entrez with required identification
Entrez.email = Config.PUBMED_EMAIL or "chai-tracker@example.com"
Entrez.tool = Config.PUBMED_TOOL

# Rate limiting: NCBI allows max 3 requests/second
REQUEST_DELAY = 0.4  # seconds between requests


def build_search_query(keywords):
    """
    Build a PubMed search query from a list of keywords.

    Args:
        keywords: List of keywords to search for

    Returns:
        PubMed query string with OR operators
    """
    # Wrap multi-word keywords in quotes
    formatted = []
    for kw in keywords:
        if " " in kw:
            formatted.append(f'"{kw}"')
        else:
            formatted.append(kw)

    return "(" + " OR ".join(formatted) + ")"


def get_date_range(days_back=30):
    """
    Get date range for PubMed search.

    Args:
        days_back: Number of days to look back

    Returns:
        Tuple of (start_date, end_date) in YYYY/MM/DD format
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    return (
        start_date.strftime("%Y/%m/%d"),
        end_date.strftime("%Y/%m/%d")
    )


def search_pubmed(query, max_results=50, days_back=30):
    """
    Search PubMed for articles matching the query.

    Args:
        query: PubMed search query string
        max_results: Maximum number of results to return
        days_back: Only include papers from the last N days

    Returns:
        List of PubMed IDs (PMIDs)
    """
    try:
        start_date, end_date = get_date_range(days_back)

        # Add date filter to query
        full_query = f"{query} AND ({start_date}[PDAT] : {end_date}[PDAT])"

        logger.info(f"Searching PubMed: {query[:50]}...")

        handle = Entrez.esearch(
            db="pubmed",
            term=full_query,
            retmax=max_results,
            sort="pub_date",
            usehistory="y"
        )
        results = Entrez.read(handle)
        handle.close()

        pmids = results.get("IdList", [])
        logger.info(f"Found {len(pmids)} papers")

        time.sleep(REQUEST_DELAY)
        return pmids

    except Exception as e:
        logger.error(f"PubMed search error: {e}")
        return []


def fetch_paper_details(pmid_list):
    """
    Fetch detailed information for a list of PubMed IDs.

    Args:
        pmid_list: List of PubMed IDs

    Returns:
        List of dictionaries with paper details
    """
    if not pmid_list:
        return []

    papers = []

    try:
        # Fetch in batches to respect rate limits
        batch_size = 20
        for i in range(0, len(pmid_list), batch_size):
            batch = pmid_list[i:i + batch_size]

            logger.info(f"Fetching details for {len(batch)} papers...")

            handle = Entrez.efetch(
                db="pubmed",
                id=",".join(batch),
                rettype="xml",
                retmode="xml"
            )
            records = Entrez.read(handle)
            handle.close()

            # Process each article
            for article in records.get("PubmedArticle", []):
                paper = parse_pubmed_article(article)
                if paper:
                    papers.append(paper)

            time.sleep(REQUEST_DELAY)

    except Exception as e:
        logger.error(f"Error fetching paper details: {e}")

    return papers


def parse_pubmed_article(article):
    """
    Parse a PubMed article XML record into a dictionary.

    Args:
        article: PubMed article record from Entrez

    Returns:
        Dictionary with paper details or None if parsing failed
    """
    try:
        medline = article.get("MedlineCitation", {})
        article_data = medline.get("Article", {})
        pmid = str(medline.get("PMID", ""))

        if not pmid:
            return None

        # Extract title
        title = article_data.get("ArticleTitle", "")
        if isinstance(title, list):
            title = " ".join(str(t) for t in title)

        # Extract abstract
        abstract_data = article_data.get("Abstract", {})
        abstract_text = abstract_data.get("AbstractText", [])
        if isinstance(abstract_text, list):
            # Handle structured abstracts
            abstract_parts = []
            for part in abstract_text:
                if hasattr(part, "attributes") and part.attributes.get("Label"):
                    abstract_parts.append(f"{part.attributes['Label']}: {str(part)}")
                else:
                    abstract_parts.append(str(part))
            abstract = " ".join(abstract_parts)
        else:
            abstract = str(abstract_text)

        # Extract authors and affiliations
        author_list = article_data.get("AuthorList", [])
        authors = []
        affiliations = []
        for author in author_list[:10]:  # Limit to first 10 authors
            last_name = author.get("LastName", "")
            fore_name = author.get("ForeName", "")
            if last_name:
                if fore_name:
                    authors.append(f"{last_name} {fore_name}")
                else:
                    authors.append(last_name)
            # Extract affiliation info
            affiliation_list = author.get("AffiliationInfo", [])
            for aff in affiliation_list:
                aff_str = aff.get("Affiliation", "")
                if aff_str and aff_str not in affiliations:
                    affiliations.append(aff_str)
        authors_str = ", ".join(authors)
        if len(author_list) > 10:
            authors_str += " et al."
        affiliations_str = "; ".join(affiliations[:10])  # Limit affiliations

        # Extract publication date
        pub_date = None
        journal = article_data.get("Journal", {})
        journal_issue = journal.get("JournalIssue", {})
        pub_date_data = journal_issue.get("PubDate", {})

        year = pub_date_data.get("Year")
        month = pub_date_data.get("Month", "01")
        day = pub_date_data.get("Day", "01")

        if year:
            # Convert month name to number if needed
            month_map = {
                "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
            }
            if month in month_map:
                month = month_map[month]
            try:
                month = str(int(month)).zfill(2)
                day = str(int(day)).zfill(2)
                pub_date = datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pub_date = datetime.strptime(f"{year}-01-01", "%Y-%m-%d").date()

        # Extract journal name
        journal_title = journal.get("Title", "")

        # Build URL
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

        return {
            "external_id": pmid,
            "title": title,
            "abstract": abstract[:4000] if abstract else None,  # Limit length
            "authors": authors_str,
            "affiliations": affiliations_str if affiliations_str else None,
            "publication_date": pub_date,
            "url": url,
            "publication_type": "Research Article",
            "journal": journal_title
        }

    except Exception as e:
        logger.error(f"Error parsing article: {e}")
        return None


def categorize_publication(title, abstract=None):
    """
    Determine which CHAI program areas and subtopics a publication is relevant to.

    Checks the title and abstract against keywords for each program area
    and its subtopics, calculating relevance scores.

    Args:
        title: Publication title
        abstract: Publication abstract (optional)

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


def detect_regions(title, abstract=None, affiliations=None):
    """
    Detect which geographic regions are mentioned in a publication.

    Searches title, abstract, and author affiliations for country names
    and region keywords.

    Args:
        title: Publication title
        abstract: Publication abstract (optional)
        affiliations: Author affiliations string (optional)

    Returns:
        Dictionary mapping region_key to list of matched terms
    """
    results = {}

    # Combine title, abstract, and affiliations for searching
    text = (title or "")
    if abstract:
        text += " " + abstract
    if affiliations:
        text += " " + affiliations

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
        source: Source identifier ('PubMed')
        external_id: PMID

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
        publication = Publication(
            source="PubMed",
            external_id=pub_data.get("external_id", ""),
            title=pub_data.get("title", ""),
            abstract=pub_data.get("abstract"),
            authors=pub_data.get("authors"),
            publication_date=pub_data.get("publication_date"),
            url=pub_data.get("url", ""),
            publication_type=pub_data.get("publication_type"),
        )
        db.session.add(publication)
        db.session.flush()

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
        logger.info(f"Saved: {publication.title[:50]}...")
        return publication

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving publication: {e}")
        return None


def fetch_all_program_areas():
    """
    Search PubMed for publications matching all CHAI program areas.

    Returns:
        List of publication data dictionaries with program areas
    """
    all_publications = {}  # Use dict to deduplicate by PMID

    for area_key, area_info in PROGRAM_AREAS.items():
        logger.info(f"Searching for {area_info['name']} publications...")

        # Build search query from keywords
        query = build_search_query(area_info["keywords"])

        # Search PubMed
        pmids = search_pubmed(
            query,
            max_results=Config.PUBMED_MAX_RESULTS_PER_AREA,
            days_back=Config.PUBMED_DAYS_LOOKBACK
        )

        if pmids:
            # Fetch details
            papers = fetch_paper_details(pmids)

            for paper in papers:
                pmid = paper["external_id"]
                if pmid not in all_publications:
                    # Categorize and add (now returns tuple)
                    program_areas, subtopics = categorize_publication(
                        paper.get("title", ""),
                        paper.get("abstract")
                    )
                    # Detect regions (including affiliations for PubMed)
                    regions = detect_regions(
                        paper.get("title", ""),
                        paper.get("abstract"),
                        paper.get("affiliations")
                    )
                    paper["program_areas"] = program_areas
                    paper["subtopics"] = subtopics
                    paper["regions"] = regions
                    all_publications[pmid] = paper
                else:
                    # Update program areas and subtopics if already exists
                    existing_areas = all_publications[pmid].get("program_areas", {})
                    existing_subtopics = all_publications[pmid].get("subtopics", {})
                    new_areas, new_subtopics = categorize_publication(
                        paper.get("title", ""),
                        paper.get("abstract")
                    )
                    existing_areas.update(new_areas)
                    existing_subtopics.update(new_subtopics)
                    all_publications[pmid]["program_areas"] = existing_areas
                    all_publications[pmid]["subtopics"] = existing_subtopics
                    # Update regions as well
                    existing_regions = all_publications[pmid].get("regions", {})
                    new_regions = detect_regions(
                        paper.get("title", ""),
                        paper.get("abstract"),
                        paper.get("affiliations")
                    )
                    for region_key, terms in new_regions.items():
                        if region_key in existing_regions:
                            # Merge terms without duplicates
                            existing_terms = existing_regions[region_key]
                            for term in terms:
                                if term not in existing_terms:
                                    existing_terms.append(term)
                        else:
                            existing_regions[region_key] = terms
                    all_publications[pmid]["regions"] = existing_regions

        logger.info(f"Found {len(pmids)} papers for {area_info['name']}")
        time.sleep(REQUEST_DELAY)

    return list(all_publications.values())


def save_publications(publications):
    """
    Save a list of publications to the database.

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
        if publication_exists("PubMed", external_id):
            logger.debug(f"Skipping existing: {external_id}")
            skipped += 1
            continue

        # Skip if no relevant program areas
        program_areas = pub_data.get("program_areas", {})
        if not program_areas:
            skipped += 1
            continue

        # Get subtopics and detected regions
        subtopics = pub_data.get("subtopics", {})
        regions = pub_data.get("regions", {})

        # Save to database
        if save_publication(pub_data, program_areas, subtopics, regions):
            saved += 1
        else:
            skipped += 1

    logger.info(f"Saved {saved} new publications, skipped {skipped}")
    return saved, skipped


def run_pubmed_scraper():
    """
    Run the complete PubMed scraping process.

    Returns:
        Dictionary with scraping results
    """
    logger.info("=" * 50)
    logger.info("Starting PubMed Scraper")
    logger.info("=" * 50)

    if not Config.PUBMED_EMAIL:
        logger.warning("PUBMED_EMAIL not set. Using placeholder email.")

    try:
        # Fetch publications for all program areas
        publications = fetch_all_program_areas()
        logger.info(f"PubMed scraper found {len(publications)} unique publications")

        # Save to database
        saved, skipped = save_publications(publications)

        results = {
            "source": "PubMed",
            "total_found": len(publications),
            "saved": saved,
            "skipped": skipped,
            "status": "success"
        }

        logger.info(f"PubMed scraper completed: {saved} saved, {skipped} skipped")
        return results

    except Exception as e:
        logger.error(f"PubMed scraper failed: {e}")
        return {
            "source": "PubMed",
            "status": "error",
            "error": str(e)
        }
