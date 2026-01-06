# CHAI Health Publications Tracker

A system that automatically collects health publications from WHO and PubMed, and sends personalized email digests to subscribers based on their areas of interest.

## Features

- **Automated Collection**: Scrapes publications from WHO and PubMed
- **Smart Categorization**: Automatically categorizes publications by health topic
- **Personalized Digests**: Users choose which topics they care about
- **Flexible Scheduling**: Daily, weekly, biweekly, or monthly email updates
- **Simple Web Interface**: Easy registration and preference management
- **Background Scheduler**: Optional automatic scraping and digest sending

## Health Topics Covered

- HIV/AIDS
- Malaria
- Tuberculosis
- Maternal & Child Health
- Vaccines & Immunization
- Essential Medicines
- Health Systems Strengthening

## Requirements

- Python 3.8 or higher
- Internet connection

## Installation

### Step 1: Navigate to the project directory

```bash
cd chai-health-tracker
```

### Step 2: Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure environment variables

Copy the example environment file and edit it:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```
# Email Configuration (for sending digests)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_ADDRESS=your-email@gmail.com
EMAIL_PASSWORD=your-app-password

# Flask Configuration
SECRET_KEY=generate-a-random-string-here

# PubMed API (required by NCBI)
PUBMED_EMAIL=your-email@gmail.com
```

**Note for Gmail users**: You need to create an "App Password" in your Google Account settings (Security > 2-Step Verification > App passwords).

## Running the Application

### Option 1: Website Only (Manual Mode)

Start the website without automatic scheduling:

```bash
source venv/bin/activate
python run.py
```

Then open http://localhost:5000 in your browser.

In this mode, you'll need to run scrapers and send digests manually.

### Option 2: Website + Automatic Scheduling

Start the website with automatic background tasks:

```bash
python run.py --with-scheduler
```

This enables:
- **Scrapers**: Run automatically at 6:00 AM daily
- **Digests**: Sent automatically at 8:00 AM daily

### Command-Line Options

```bash
python run.py [OPTIONS]

Options:
  --with-scheduler     Enable automatic scraping and digest sending
  --host HOST          Host to bind to (default: 127.0.0.1)
  --port PORT          Port to bind to (default: 5000)
  --run-scrapers-now   Run scrapers immediately on startup
  --send-digests-now   Send digests immediately on startup
```

### Run Scrapers Manually

To collect new publications from WHO and PubMed:

```bash
python scripts/run_scrapers.py           # Run all scrapers
python scripts/run_scrapers.py --who     # Run WHO scraper only
python scripts/run_scrapers.py --pubmed  # Run PubMed scraper only
```

### Send Digests Manually

To send email digests to all users who are due:

```bash
python scripts/send_digests.py              # Send to all due users
python scripts/send_digests.py --preview    # Preview without sending
python scripts/send_digests.py --test EMAIL # Send test to specific email
```

## Quick Start Guide

### For Administrators

1. **Start the application**
   ```bash
   source venv/bin/activate
   python run.py
   ```

2. **Collect initial publications**
   ```bash
   python scripts/run_scrapers.py
   ```

3. **Verify publications were collected**
   - The script will show a summary of publications by topic

4. **(Optional) Enable automatic scheduling**
   ```bash
   python run.py --with-scheduler
   ```

### For Users

1. Go to http://localhost:5000
2. Click "Create Account" and register with your email
3. Select your health topics of interest
4. Choose how often you want to receive digests (daily/weekly/biweekly/monthly)
5. You'll receive email digests with relevant publications

## Project Structure

```
chai-health-tracker/
├── app/
│   ├── __init__.py           # Flask app factory
│   ├── config.py             # Configuration and program areas
│   ├── models.py             # Database models (User, Publication, etc.)
│   ├── routes.py             # Web routes (register, login, preferences)
│   ├── scrapers/
│   │   ├── who_scraper.py    # WHO publications scraper
│   │   └── pubmed_scraper.py # PubMed research paper scraper
│   ├── services/
│   │   ├── email_service.py  # SMTP email sending
│   │   └── digest_service.py # Digest creation and delivery
│   ├── templates/            # HTML templates
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── register.html
│   │   ├── login.html
│   │   ├── preferences.html
│   │   └── email_digest.html
│   └── static/
│       └── style.css         # Website styling
├── scripts/
│   ├── run_scrapers.py       # Manual scraper runner
│   └── send_digests.py       # Manual digest sender
├── data/
│   └── chai_tracker.db       # SQLite database (auto-created)
├── venv/                     # Python virtual environment
├── .env                      # Your environment settings (create from .env.example)
├── .env.example              # Example environment file
├── requirements.txt          # Python dependencies
├── run.py                    # Main entry point
└── README.md                 # This file
```

## Database Tables

| Table | Description |
|-------|-------------|
| users | Registered users with email and preferences |
| publications | Collected publications from WHO and PubMed |
| user_program_preferences | Links users to their selected health topics |
| publication_program_areas | Links publications to relevant topics with scores |
| digest_logs | Tracks which publications were sent to which users |

## Troubleshooting

### "Module not found" error
Make sure you've activated the virtual environment and installed requirements:
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### "Database locked" error
Make sure you don't have multiple instances of the application running.

### "Email failed to send" error
- Check your `.env` file has correct email settings
- For Gmail, make sure you're using an App Password, not your regular password
- Enable 2FA on your Google account, then create an App Password

### "No publications found" error
- WHO or PubMed servers might be temporarily unavailable
- Try running the scrapers again later
- Check your internet connection

### Scheduler not running
- Make sure you started with `--with-scheduler` flag
- Check the terminal for scheduler status messages
- Jobs run at fixed times (6 AM and 8 AM) - use `--run-scrapers-now` for immediate execution

## How It Works

1. **Scrapers** collect publications from WHO and PubMed APIs
2. **Categorization** matches publications to health topics using keywords
3. **Users** register and select topics they're interested in
4. **Digest Service** finds new matching publications for each user
5. **Email Service** sends personalized HTML digests
6. **Scheduler** (optional) automates the scraping and sending process

## License

This project is for educational purposes.
