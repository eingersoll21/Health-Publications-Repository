#!/usr/bin/env python3
"""
Main entry point for the CHAI Health Publications Tracker.

Usage:
    python run.py                    # Start website only
    python run.py --with-scheduler   # Start website + automatic tasks

The scheduler runs:
    - Scrapers daily at 6:00 AM (collects new publications)
    - Digest check daily at 8:00 AM (sends emails to users who are due)
"""

import os
import argparse
import logging
import atexit
from datetime import datetime

from app import create_app, init_db
from app.config import Config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create the Flask application
app = create_app()

# Initialize the database (creates tables if they don't exist)
init_db(app)


def run_scrapers_job():
    """
    Scheduled job to run all scrapers.
    Runs within the Flask application context.
    """
    logger.info("=" * 50)
    logger.info("SCHEDULED JOB: Running scrapers")
    logger.info("=" * 50)

    with app.app_context():
        try:
            from app.scrapers.who_scraper import run_who_scraper
            from app.scrapers.pubmed_scraper import run_pubmed_scraper

            # Run WHO scraper
            logger.info("Running WHO scraper...")
            who_results = run_who_scraper()
            logger.info(f"WHO: {who_results.get('saved', 0)} new publications")

            # Run PubMed scraper
            logger.info("Running PubMed scraper...")
            pubmed_results = run_pubmed_scraper()
            logger.info(f"PubMed: {pubmed_results.get('saved', 0)} new publications")

            logger.info("Scraper job completed successfully")

        except Exception as e:
            logger.error(f"Scraper job failed: {e}")


def send_digests_job():
    """
    Scheduled job to send email digests to users who are due.
    Runs within the Flask application context.
    """
    logger.info("=" * 50)
    logger.info("SCHEDULED JOB: Sending digests")
    logger.info("=" * 50)

    with app.app_context():
        try:
            from app.services.digest_service import send_all_pending_digests

            results = send_all_pending_digests()

            logger.info(f"Digest job completed: {results['sent']} sent, "
                       f"{results['failed']} failed, {results['skipped']} skipped")

        except Exception as e:
            logger.error(f"Digest job failed: {e}")


def setup_scheduler():
    """
    Set up APScheduler with jobs for scraping and sending digests.

    Returns:
        BackgroundScheduler instance
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler()

    # Run scrapers daily at 6:00 AM
    scheduler.add_job(
        func=run_scrapers_job,
        trigger=CronTrigger(hour=6, minute=0),
        id='scraper_job',
        name='Run WHO and PubMed scrapers',
        replace_existing=True
    )

    # Send digests daily at 8:00 AM
    scheduler.add_job(
        func=send_digests_job,
        trigger=CronTrigger(hour=8, minute=0),
        id='digest_job',
        name='Send email digests',
        replace_existing=True
    )

    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started with the following jobs:")
    logger.info("  - Scrapers: Daily at 6:00 AM")
    logger.info("  - Digests: Daily at 8:00 AM")

    # Shut down scheduler when app exits
    atexit.register(lambda: scheduler.shutdown())

    return scheduler


def main():
    """Main entry point with command-line argument handling."""
    parser = argparse.ArgumentParser(
        description="CHAI Health Publications Tracker"
    )
    parser.add_argument(
        "--with-scheduler",
        action="store_true",
        help="Enable automatic scraping and digest sending"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get('HOST', '0.0.0.0'),
        help="Host to bind to (default: 0.0.0.0, or HOST env var)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get('PORT', 5000)),
        help="Port to bind to (default: 5000, or PORT env var)"
    )
    parser.add_argument(
        "--run-scrapers-now",
        action="store_true",
        help="Run scrapers immediately on startup"
    )
    parser.add_argument(
        "--send-digests-now",
        action="store_true",
        help="Send digests immediately on startup"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("CHAI Health Publications Tracker")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Open http://{args.host}:{args.port} in your browser")
    print()

    # Run immediate tasks if requested
    if args.run_scrapers_now:
        print("Running scrapers immediately...")
        run_scrapers_job()
        print()

    if args.send_digests_now:
        print("Sending digests immediately...")
        send_digests_job()
        print()

    # Set up scheduler if requested
    if args.with_scheduler:
        print("Starting with automatic scheduling enabled")
        print("  - Scrapers will run daily at 6:00 AM")
        print("  - Digests will be sent daily at 8:00 AM")
        print()
        setup_scheduler()
    else:
        print("Scheduler disabled. Use --with-scheduler to enable.")
        print("Run scrapers manually: python scripts/run_scrapers.py")
        print("Send digests manually: python scripts/send_digests.py")
        print()

    print("=" * 60)
    print()

    # Start Flask server
    # Debug mode is OFF by default for security - set FLASK_DEBUG=true to enable
    debug_mode = Config.DEBUG

    if debug_mode:
        print("WARNING: Debug mode is ON. Do not use in production!")

    app.run(
        host=args.host,
        port=args.port,
        debug=debug_mode,
        use_reloader=False  # Disable reloader to prevent scheduler duplicates
    )


if __name__ == '__main__':
    main()
