#!/usr/bin/env python3
"""
Manual scraper runner for the Global Health Publications Tracker.

Run this script to manually fetch publications from WHO and PubMed.

Usage:
    python scripts/run_scrapers.py           # Run all scrapers
    python scripts/run_scrapers.py --who     # Run WHO scraper only
    python scripts/run_scrapers.py --pubmed  # Run PubMed scraper only
"""

import sys
import os
import argparse
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, init_db
from app.models import db, Publication, PublicationProgramArea
from app.config import PROGRAM_AREAS, get_program_area_name


def print_separator():
    """Print a visual separator."""
    print("=" * 60)


def print_results(results):
    """Print scraper results in a formatted way."""
    print(f"\n📊 Results for {results['source']}:")
    print(f"   Status: {results['status']}")
    if results['status'] == 'success':
        print(f"   Total found: {results['total_found']}")
        print(f"   New saved: {results['saved']}")
        print(f"   Skipped: {results['skipped']}")
    else:
        print(f"   Error: {results.get('error', 'Unknown error')}")


def show_database_summary(app):
    """Show summary of publications in the database."""
    with app.app_context():
        total = Publication.query.count()
        who_count = Publication.query.filter_by(source="WHO").count()
        pubmed_count = Publication.query.filter_by(source="PubMed").count()

        print_separator()
        print("📚 DATABASE SUMMARY")
        print_separator()
        print(f"Total publications: {total}")
        print(f"  - WHO: {who_count}")
        print(f"  - PubMed: {pubmed_count}")

        # Show breakdown by program area
        print("\nPublications by program area:")
        for area_key, area_info in PROGRAM_AREAS.items():
            count = PublicationProgramArea.query.filter_by(
                program_area_key=area_key
            ).count()
            print(f"  - {area_info['name']}: {count}")

        # Show recent publications
        print("\nMost recent publications:")
        recent = Publication.query.order_by(
            Publication.scraped_at.desc()
        ).limit(5).all()

        for pub in recent:
            title = pub.title[:50] + "..." if len(pub.title) > 50 else pub.title
            print(f"  [{pub.source}] {title}")


def run_who_scraper(app):
    """Run the WHO scraper."""
    print_separator()
    print("🌍 Running WHO Scraper")
    print_separator()

    with app.app_context():
        from app.scrapers.who_scraper import run_who_scraper
        results = run_who_scraper()
        print_results(results)
        return results


def run_pubmed_scraper(app):
    """Run the PubMed scraper."""
    print_separator()
    print("🔬 Running PubMed Scraper")
    print_separator()

    try:
        with app.app_context():
            from app.scrapers.pubmed_scraper import run_pubmed_scraper
            results = run_pubmed_scraper()
            print_results(results)
            return results
    except ImportError:
        print("PubMed scraper not yet implemented.")
        return {"source": "PubMed", "status": "not_implemented"}


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run publication scrapers for Health Publications Tracker"
    )
    parser.add_argument(
        "--who",
        action="store_true",
        help="Run WHO scraper only"
    )
    parser.add_argument(
        "--pubmed",
        action="store_true",
        help="Run PubMed scraper only"
    )
    args = parser.parse_args()

    # If no specific scraper selected, run all
    run_all = not args.who and not args.pubmed

    print_separator()
    print("🏥 Global Health Publications Tracker - Scraper Runner")
    print(f"   Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_separator()

    # Create Flask app and initialize database
    app = create_app()
    init_db(app)

    results = []

    # Run selected scrapers
    if args.who or run_all:
        results.append(run_who_scraper(app))

    if args.pubmed or run_all:
        results.append(run_pubmed_scraper(app))

    # Show summary
    show_database_summary(app)

    print_separator()
    print(f"✅ Scraping completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_separator()


if __name__ == "__main__":
    main()
