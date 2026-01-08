"""
Email Service for the Global Health Research Hub.

This module handles sending emails via SMTP, including:
- HTML email formatting
- Welcome emails for new users
- SMTP connection management
- Error handling and logging
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import render_template
from app.config import Config

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def send_email(to_email, subject, html_content, text_content=None):
    """
    Send an HTML email via SMTP.

    Args:
        to_email: Recipient email address
        subject: Email subject line
        html_content: HTML body of the email
        text_content: Plain text fallback (optional, generated from subject if not provided)

    Returns:
        True if email was sent successfully, False otherwise
    """
    # Check if email settings are configured
    if not Config.EMAIL_ADDRESS or not Config.EMAIL_PASSWORD:
        logger.error("Email settings not configured. Set EMAIL_ADDRESS and EMAIL_PASSWORD in .env")
        return False

    if not to_email:
        logger.error("No recipient email address provided")
        return False

    try:
        # Create message container
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = Config.EMAIL_ADDRESS
        msg['To'] = to_email

        # Create plain text version (fallback)
        if not text_content:
            text_content = f"Please view this email in an HTML-capable email client.\n\nSubject: {subject}"

        # Attach both plain text and HTML versions
        part1 = MIMEText(text_content, 'plain')
        part2 = MIMEText(html_content, 'html')

        msg.attach(part1)
        msg.attach(part2)

        # Connect to SMTP server and send (with 10 second timeout)
        logger.info(f"Connecting to SMTP server {Config.SMTP_SERVER}:{Config.SMTP_PORT}")

        smtp_username = Config.SMTP_USERNAME or Config.EMAIL_ADDRESS

        # Use SSL for port 465, STARTTLS for port 587
        if Config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10) as server:
                logger.info(f"Authenticating as {smtp_username}")
                server.login(smtp_username, Config.EMAIL_PASSWORD)
                logger.info(f"Sending email to {to_email}")
                server.sendmail(Config.EMAIL_ADDRESS, to_email, msg.as_string())
        else:
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                logger.info(f"Authenticating as {smtp_username}")
                server.login(smtp_username, Config.EMAIL_PASSWORD)
                logger.info(f"Sending email to {to_email}")
                server.sendmail(Config.EMAIL_ADDRESS, to_email, msg.as_string())

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        logger.error("Check your EMAIL_ADDRESS and EMAIL_PASSWORD settings")
        return False

    except smtplib.SMTPConnectError as e:
        logger.error(f"Failed to connect to SMTP server: {e}")
        logger.error(f"Check SMTP_SERVER ({Config.SMTP_SERVER}) and SMTP_PORT ({Config.SMTP_PORT})")
        return False

    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"Recipient refused: {e}")
        return False

    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return False

    except Exception as e:
        logger.error(f"Unexpected error sending email: {e}")
        return False


def test_email_connection():
    """
    Test the SMTP connection without sending an email.

    Returns:
        True if connection successful, False otherwise
    """
    if not Config.EMAIL_ADDRESS or not Config.EMAIL_PASSWORD:
        logger.error("Email settings not configured")
        return False

    try:
        logger.info(f"Testing connection to {Config.SMTP_SERVER}:{Config.SMTP_PORT}")

        smtp_username = Config.SMTP_USERNAME or Config.EMAIL_ADDRESS

        # Use SSL for port 465, STARTTLS for port 587
        if Config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10) as server:
                server.login(smtp_username, Config.EMAIL_PASSWORD)
        else:
            with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(smtp_username, Config.EMAIL_PASSWORD)

        logger.info("SMTP connection test successful!")
        return True

    except Exception as e:
        logger.error(f"SMTP connection test failed: {e}")
        return False


def send_welcome_email(user, base_url=None):
    """
    Send a welcome email to a newly registered user.

    Args:
        user: User object with email and first_name
        base_url: Base URL for links. Defaults to Config.BASE_URL.

    Returns:
        True if email was sent successfully, False otherwise
    """
    if base_url is None:
        base_url = Config.BASE_URL

    try:
        # Import here to avoid circular imports
        from app.routes import generate_unsubscribe_token

        # Generate URLs
        unsubscribe_token = generate_unsubscribe_token(user)
        unsubscribe_url = f"{base_url}/unsubscribe/{unsubscribe_token}"
        preferences_url = f"{base_url}/preferences"
        browse_url = f"{base_url}/browse"
        suggestions_url = f"{base_url}/suggestions"

        # Create context for template
        context = {
            'user_first_name': user.first_name,
            'unsubscribe_url': unsubscribe_url,
            'preferences_url': preferences_url,
            'browse_url': browse_url,
            'suggestions_url': suggestions_url,
        }

        # Render HTML template
        from flask import current_app
        with current_app.app_context():
            html_content = render_template('email_welcome.html', **context)

        # Create plain text version
        text_content = f"""
Welcome to Global Health Research Hub!

Hi {user.first_name},

Your account has been created. Here's what you can do:

SET UP YOUR PERSONALIZED DIGESTS
Subscribe to health topics and countries you care about.
{preferences_url}

BROWSE THE DATABASE
Search our database of WHO publications and PubMed research.
{browse_url}

ADJUST ANYTIME
Update your preferences or change your delivery schedule.
{preferences_url}

SUGGESTIONS WELCOME
Have ideas for new data sources or features?
{suggestions_url}

Happy reading!
Global Health Research Hub

---
Unsubscribe: {unsubscribe_url}
Update Preferences: {preferences_url}
"""

        # Send the email
        subject = "Welcome to Global Health Research Hub!"
        success = send_email(
            to_email=user.email,
            subject=subject,
            html_content=html_content,
            text_content=text_content
        )

        if success:
            logger.info(f"Welcome email sent to {user.email}")
        else:
            logger.error(f"Failed to send welcome email to {user.email}")

        return success

    except Exception as e:
        logger.error(f"Error sending welcome email to {user.email}: {e}")
        return False


def send_admin_notification(subject, body_text):
    """
    Send a notification email to the admin address.

    Args:
        subject: Email subject line
        body_text: Plain text body of the email

    Returns:
        True if email was sent successfully, False otherwise
    """
    admin_email = Config.EMAIL_ADDRESS  # Send to the same address that sends emails

    # Create simple HTML version
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #2d5f7a; }}
            .details {{ background: #f5f5f5; padding: 15px; border-radius: 5px; }}
            .details p {{ margin: 8px 0; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>{subject}</h2>
            <div class="details">
                {body_text.replace(chr(10), '<br>')}
            </div>
        </div>
    </body>
    </html>
    """

    try:
        success = send_email(
            to_email=admin_email,
            subject=subject,
            html_content=html_content,
            text_content=body_text
        )

        if success:
            logger.info(f"Admin notification sent: {subject}")
        else:
            logger.error(f"Failed to send admin notification: {subject}")

        return success

    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")
        return False


def send_new_user_notification(user):
    """
    Send notification to admin when a new user registers.

    Args:
        user: User object with email, first_name, last_name

    Returns:
        True if email was sent successfully, False otherwise
    """
    from datetime import datetime

    subject = "New User Registration"

    body_text = f"""A new user has registered on Global Health Research Hub.

Name: {user.first_name} {user.last_name or ''}
Email: {user.email}
Registered: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""

    return send_admin_notification(subject, body_text)


def send_suggestion_notification(user, suggestion_type, description):
    """
    Send notification to admin when a user submits a suggestion.

    Args:
        user: User object who submitted the suggestion
        suggestion_type: Type of suggestion (e.g., 'feature_request', 'bug_report')
        description: The suggestion text

    Returns:
        True if email was sent successfully, False otherwise
    """
    from datetime import datetime

    # Format suggestion type for display
    type_display = suggestion_type.replace('_', ' ').title()

    subject = f"New Suggestion: {type_display}"

    body_text = f"""A new suggestion has been submitted on Global Health Research Hub.

User: {user.first_name} {user.last_name or ''}
Email: {user.email}
Type: {type_display}
Submitted: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

Description:
{description}
"""

    return send_admin_notification(subject, body_text)
