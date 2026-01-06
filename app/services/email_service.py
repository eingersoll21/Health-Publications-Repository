"""
Email Service for the CHAI Health Publications Tracker.

This module handles sending emails via SMTP, including:
- HTML email formatting
- SMTP connection management
- Error handling and logging
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

        # Connect to SMTP server and send
        logger.info(f"Connecting to SMTP server {Config.SMTP_SERVER}:{Config.SMTP_PORT}")

        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()

            logger.info(f"Authenticating as {Config.EMAIL_ADDRESS}")
            server.login(Config.EMAIL_ADDRESS, Config.EMAIL_PASSWORD)

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

        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(Config.EMAIL_ADDRESS, Config.EMAIL_PASSWORD)

        logger.info("SMTP connection test successful!")
        return True

    except Exception as e:
        logger.error(f"SMTP connection test failed: {e}")
        return False
