#!/usr/bin/env python3
"""
Manual digest sender for the CHAI Health Publications Tracker.

Run this script to send email digests to all users who are due.

Usage:
    python scripts/send_digests.py              # Send to all due users
    python scripts/send_digests.py --preview    # Preview without sending
    python scripts/send_digests.py --test EMAIL # Send test digest to specific email
"""

import sys
import os
import argparse
from datetime import datetime

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, init_db
from app.models import db, User
from app.services.digest_service import (
    get_users_due_for_digest,
    get_publications_for_user,
    create_digest_content,
    send_digest_to_user,
    send_all_pending_digests
)
from app.config import get_program_area_name


def print_separator():
    """Print a visual separator."""
    print("=" * 60)


def preview_digests(app):
    """
    Preview what digests would be sent without actually sending them.
    """
    print_separator()
    print("PREVIEW MODE - No emails will be sent")
    print_separator()

    with app.app_context():
        users = get_users_due_for_digest()

        if not users:
            print("\nNo users are currently due for a digest.")
            return

        print(f"\nFound {len(users)} user(s) due for digest:\n")

        for user in users:
            print(f"User: {user.email}")
            print(f"  Frequency: {user.digest_frequency}")
            print(f"  Last digest: {user.last_digest_sent or 'Never'}")

            # Get their subscribed areas
            areas = user.get_selected_program_keys()
            area_names = [get_program_area_name(a) for a in areas]
            print(f"  Subscribed to: {', '.join(area_names)}")

            # Get publications that would be included
            publications = get_publications_for_user(user)
            print(f"  Publications to include: {len(publications)}")

            if publications:
                print("  Sample publications:")
                for pub_data in publications[:3]:
                    pub = pub_data['publication']
                    print(f"    - [{pub.source}] {pub.title[:50]}...")

            print()


def send_test_digest(app, email):
    """
    Send a test digest to a specific email address.
    """
    print_separator()
    print(f"TEST MODE - Sending test digest to {email}")
    print_separator()

    with app.app_context():
        # Find or create a test scenario
        user = User.query.filter_by(email=email).first()

        if not user:
            print(f"\nNo user found with email: {email}")
            print("Creating a temporary test scenario...")

            # Create a mock digest preview
            from app.models import Publication
            publications = Publication.query.limit(5).all()

            if not publications:
                print("No publications in database. Run scrapers first.")
                return

            print(f"\nFound {len(publications)} publications to preview.")
            print("\nSample publications that would be included:")
            for pub in publications:
                print(f"  - [{pub.source}] {pub.title[:50]}...")

            print("\nNote: To send an actual test email, register this email first.")
            return

        # User exists, send them a digest
        print(f"\nUser found: {user.email}")
        print(f"Subscribed areas: {', '.join(user.get_selected_program_keys())}")

        publications = get_publications_for_user(user)
        print(f"Publications to include: {len(publications)}")

        if not publications:
            print("\nNo new publications to send. Try running the scrapers first.")
            return

        # Create and show the digest
        print("\nGenerating digest...")
        content = create_digest_content(user, publications)

        print(f"\nSubject: {content['subject']}")
        print("\n--- HTML Preview (first 500 chars) ---")
        print(content['html'][:500])
        print("...")

        # Ask for confirmation
        confirm = input("\nSend this digest? (y/n): ").strip().lower()
        if confirm == 'y':
            result = send_digest_to_user(user)
            if result['success']:
                print(f"\nDigest sent successfully! ({result['publications_sent']} publications)")
            else:
                print(f"\nFailed to send digest: {result.get('error', 'Unknown error')}")
        else:
            print("\nCancelled.")


def send_digests(app):
    """
    Send digests to all users who are due.
    """
    print_separator()
    print("SEND MODE - Sending digests to all due users")
    print_separator()

    with app.app_context():
        results = send_all_pending_digests()

        print(f"\nDigest Send Summary:")
        print(f"  Total users due: {results['total']}")
        print(f"  Successfully sent: {results['sent']}")
        print(f"  Failed: {results['failed']}")
        print(f"  Skipped (no new content): {results['skipped']}")

        if results['details']:
            print("\nDetails:")
            for detail in results['details']:
                status = "SENT" if detail['success'] and detail['publications_sent'] > 0 else \
                         "SKIPPED" if detail['success'] else "FAILED"
                print(f"  [{status}] {detail['email']}: {detail.get('publications_sent', 0)} publications")
                if not detail['success']:
                    print(f"         Error: {detail.get('error', 'Unknown')}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Send email digests for CHAI Health Tracker"
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview digests without sending"
    )
    parser.add_argument(
        "--test",
        type=str,
        metavar="EMAIL",
        help="Send test digest to specific email"
    )
    args = parser.parse_args()

    print_separator()
    print("CHAI Health Publications Tracker - Digest Sender")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_separator()

    # Create Flask app
    app = create_app()
    init_db(app)

    if args.preview:
        preview_digests(app)
    elif args.test:
        send_test_digest(app, args.test)
    else:
        send_digests(app)

    print_separator()
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_separator()


if __name__ == "__main__":
    main()
