"""
Database models for the Global Health Research Hub.

This file defines all database tables:
- User: Registered users with their preferences
- UserProgramPreference: Links users to health programs (with optional subtopics)
- UserProgramPreferenceLocation: Links program preferences to location filters (regions or countries)
- UserCountryWatch: Links users to countries/regions they want ALL publications for
- Publication: Publications from WHO and PubMed
- PublicationProgramArea: Links publications to relevant program areas
- PublicationSubtopic: Links publications to specific subtopics within program areas
- PublicationRegion: Links publications to detected geographic regions
- DigestLog: Tracks which publications were sent to which users
- ScraperLog: Tracks scraper runs for monitoring
- UserSuggestion: User feedback and suggestions
- ReadingFolder: User-created folders to organize saved publications
- SavedPublication: Publications saved to user's reading list
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Initialize SQLAlchemy - will be configured with Flask app
db = SQLAlchemy()


class User(UserMixin, db.Model):
    """
    Registered user who receives publication digests.

    UserMixin provides default implementations for Flask-Login:
    - is_authenticated, is_active, is_anonymous, get_id()
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Digest preferences
    digest_frequency = db.Column(
        db.String(20),
        default='weekly',
        nullable=False
    )  # Options: 'daily', 'weekly', 'biweekly', 'monthly'
    last_digest_sent = db.Column(db.DateTime, nullable=True)

    # Digest timing preferences
    preferred_day = db.Column(
        db.String(20),
        nullable=True
    )  # For weekly/biweekly: 'monday'-'sunday'. For monthly: '1', '15'. For daily: NULL
    preferred_time = db.Column(
        db.Time,
        nullable=True
    )  # e.g., 08:00, 14:00. Defaults to 08:00 if not set
    timezone = db.Column(
        db.String(50),
        default='UTC',
        nullable=True
    )  # e.g., 'America/New_York', 'Europe/London'

    # Relationships
    program_preferences = db.relationship(
        'UserProgramPreference',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    country_watches = db.relationship(
        'UserCountryWatch',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    digest_logs = db.relationship(
        'DigestLog',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    suggestions = db.relationship(
        'UserSuggestion',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    reading_folders = db.relationship(
        'ReadingFolder',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    saved_publications = db.relationship(
        'SavedPublication',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def set_password(self, password):
        """Hash and store the password. Never store plain text passwords."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def get_selected_program_keys(self):
        """Get list of program area keys this user has selected (any subtopic selection counts)."""
        return list(set(pref.program_area_key for pref in self.program_preferences))

    def get_program_preferences_detail(self):
        """
        Get detailed program preferences including subtopic and location filter selections.

        Returns:
            List of dicts with program_area_key, subtopic_key, and locations list.
        """
        return [
            {
                'program_area_key': pref.program_area_key,
                'subtopic_key': pref.subtopic_key,
                'locations': [
                    {
                        'location_type': loc.location_type,
                        'location_value': loc.location_value
                    }
                    for loc in pref.locations
                ]
            }
            for pref in self.program_preferences
        ]

    def get_country_watches(self):
        """
        Get user's country watch preferences.

        Returns:
            List of dicts with region_key and country_name.
        """
        return [
            {
                'region_key': watch.region_key,
                'country_name': watch.country_name
            }
            for watch in self.country_watches
        ]

    def has_subscriptions(self):
        """Check if user has any program subscriptions or country watches."""
        return self.program_preferences.count() > 0 or self.country_watches.count() > 0

    def __repr__(self):
        return f'<User {self.email}>'


class UserProgramPreference(db.Model):
    """
    Links a user to a health program area (and optionally specific subtopic) they're interested in.

    If subtopic_key is NULL, user wants ALL subtopics within that program area.
    If subtopic_key is set, user only wants that specific subtopic.

    Location filtering is handled by the related UserProgramPreferenceLocation table.
    If no location rows exist, publications from any location are included.

    One user can have multiple entries for the same program area with different subtopics.
    """
    __tablename__ = 'user_program_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    program_area_key = db.Column(db.String(50), nullable=False, index=True)
    subtopic_key = db.Column(db.String(50), nullable=True, index=True)  # NULL = all subtopics
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to location filters
    locations = db.relationship(
        'UserProgramPreferenceLocation',
        backref='preference',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # Ensure a user can only select each program/subtopic combination once
    __table_args__ = (
        db.UniqueConstraint('user_id', 'program_area_key', 'subtopic_key',
                           name='unique_user_program_subtopic'),
    )

    def get_location_filter_type(self):
        """Get the type of location filter: 'all', 'region', or 'country'."""
        first_loc = self.locations.first()
        if not first_loc:
            return 'all'
        return first_loc.location_type

    def get_location_values(self):
        """Get list of location values for this preference."""
        return [loc.location_value for loc in self.locations]

    def __repr__(self):
        parts = [str(self.user_id), self.program_area_key]
        parts.append(self.subtopic_key or 'ALL')
        loc_count = self.locations.count()
        if loc_count > 0:
            parts.append(f'{loc_count} locations')
        return f'<UserProgramPreference {":".join(parts)}>'


class UserProgramPreferenceLocation(db.Model):
    """
    Links a program preference to a location filter (region or country).

    Each program subscription can have multiple location filters of the same type.
    location_type is either 'region' or 'country'.
    location_value is the region key (e.g., 'sub_saharan_africa') or country name (e.g., 'Kenya').
    """
    __tablename__ = 'user_program_preference_locations'

    id = db.Column(db.Integer, primary_key=True)
    program_preference_id = db.Column(
        db.Integer,
        db.ForeignKey('user_program_preferences.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    location_type = db.Column(db.String(20), nullable=False)  # 'region' or 'country'
    location_value = db.Column(db.String(100), nullable=False)  # region key or country name

    # Ensure unique location per preference
    __table_args__ = (
        db.UniqueConstraint('program_preference_id', 'location_type', 'location_value',
                           name='unique_preference_location'),
    )

    def __repr__(self):
        return f'<UserProgramPreferenceLocation {self.program_preference_id}:{self.location_type}:{self.location_value}>'


class UserCountryWatch(db.Model):
    """
    Links a user to a country/region they want ALL publications for.

    This is the "Country Watch" subscription type - user gets every health
    publication that mentions this country/region, regardless of program area.

    If region_key is set and country_name is NULL: watching entire region
    If country_name is set: watching specific country (region_key can indicate which region it belongs to)
    """
    __tablename__ = 'user_country_watches'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    region_key = db.Column(db.String(50), nullable=True, index=True)  # NULL if watching specific country only
    country_name = db.Column(db.String(100), nullable=True, index=True)  # NULL if watching entire region
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ensure unique combinations
    __table_args__ = (
        db.UniqueConstraint('user_id', 'region_key', 'country_name', name='unique_user_country_watch'),
    )

    def __repr__(self):
        if self.country_name:
            return f'<UserCountryWatch {self.user_id}:{self.country_name}>'
        return f'<UserCountryWatch {self.user_id}:{self.region_key}>'


class Publication(db.Model):
    """
    A publication from WHO or PubMed.

    Stores metadata about health publications that can be matched
    to user preferences based on program areas.
    """
    __tablename__ = 'publications'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(20), nullable=False)  # 'WHO' or 'PubMed'
    external_id = db.Column(db.String(100), nullable=False)  # ID from source
    title = db.Column(db.Text, nullable=False)
    abstract = db.Column(db.Text, nullable=True)
    authors = db.Column(db.Text, nullable=True)  # Comma-separated list
    publication_date = db.Column(db.Date, nullable=True)
    url = db.Column(db.String(500), nullable=False)
    publication_type = db.Column(db.String(100), nullable=True)
    is_ahead_of_print = db.Column(db.Boolean, default=False, nullable=False)
    resurfaced_at = db.Column(db.DateTime, nullable=True)  # When ahead-of-print was resurfaced after official date
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    program_areas = db.relationship(
        'PublicationProgramArea',
        backref='publication',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    subtopics = db.relationship(
        'PublicationSubtopic',
        backref='publication',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    regions = db.relationship(
        'PublicationRegion',
        backref='publication',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    digest_logs = db.relationship(
        'DigestLog',
        backref='publication',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # Ensure we don't store duplicates from the same source
    __table_args__ = (
        db.UniqueConstraint('source', 'external_id', name='unique_source_external_id'),
        db.Index('idx_publication_date', 'publication_date'),
        db.Index('idx_source', 'source'),
    )

    def __repr__(self):
        return f'<Publication {self.source}:{self.external_id}>'


class PublicationProgramArea(db.Model):
    """
    Links a publication to a relevant health program area.

    The relevance_score indicates how strongly the publication
    matches the program area (based on keyword matches).
    """
    __tablename__ = 'publication_program_areas'

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(
        db.Integer,
        db.ForeignKey('publications.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    program_area_key = db.Column(db.String(50), nullable=False, index=True)
    relevance_score = db.Column(db.Integer, default=0)  # 0-100

    # Ensure each publication-program pair is unique
    __table_args__ = (
        db.UniqueConstraint(
            'publication_id',
            'program_area_key',
            name='unique_publication_program'
        ),
    )

    def __repr__(self):
        return f'<PublicationProgramArea {self.publication_id}:{self.program_area_key}>'


class PublicationSubtopic(db.Model):
    """
    Links a publication to a specific subtopic within a program area.

    This provides granular categorization - a publication can match
    multiple subtopics within the same program area.
    The relevance_score indicates how strongly the publication
    matches the subtopic (based on keyword matches).
    """
    __tablename__ = 'publication_subtopics'

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(
        db.Integer,
        db.ForeignKey('publications.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    program_area_key = db.Column(db.String(50), nullable=False, index=True)
    subtopic_key = db.Column(db.String(50), nullable=False, index=True)
    relevance_score = db.Column(db.Integer, default=0)  # 0-100

    # Ensure each publication-program-subtopic triplet is unique
    __table_args__ = (
        db.UniqueConstraint(
            'publication_id',
            'program_area_key',
            'subtopic_key',
            name='unique_publication_subtopic'
        ),
        db.Index('idx_pub_program_subtopic', 'program_area_key', 'subtopic_key'),
    )

    def __repr__(self):
        return f'<PublicationSubtopic {self.publication_id}:{self.program_area_key}:{self.subtopic_key}>'


class PublicationRegion(db.Model):
    """
    Links a publication to a detected geographic region.

    Stores which countries/regions were mentioned in the publication.
    The matched_terms field stores which specific terms were found.
    """
    __tablename__ = 'publication_regions'

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(
        db.Integer,
        db.ForeignKey('publications.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    region_key = db.Column(db.String(50), nullable=False, index=True)
    matched_terms = db.Column(db.Text, nullable=True)  # Comma-separated list of matched countries/keywords

    # Ensure each publication-region pair is unique
    __table_args__ = (
        db.UniqueConstraint(
            'publication_id',
            'region_key',
            name='unique_publication_region'
        ),
    )

    def __repr__(self):
        return f'<PublicationRegion {self.publication_id}:{self.region_key}>'


class DigestLog(db.Model):
    """
    Tracks which publications have been sent to which users.

    This prevents sending the same publication to a user multiple times
    and allows grouping publications by digest batch.
    """
    __tablename__ = 'digest_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    publication_id = db.Column(
        db.Integer,
        db.ForeignKey('publications.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    digest_batch_id = db.Column(db.String(50), nullable=True)  # Groups same email

    # Index for efficient lookups
    __table_args__ = (
        db.Index('idx_user_publication', 'user_id', 'publication_id'),
    )

    def __repr__(self):
        return f'<DigestLog {self.user_id}:{self.publication_id}>'


class ScraperLog(db.Model):
    """
    Tracks scraper runs for monitoring and display on home page.

    Records when each scraper was run and how many publications
    were found and saved.
    """
    __tablename__ = 'scraper_logs'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(20), nullable=False)  # 'WHO' or 'PubMed'
    run_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    publications_found = db.Column(db.Integer, default=0)
    publications_new = db.Column(db.Integer, default=0)

    # Index for efficient lookups
    __table_args__ = (
        db.Index('idx_scraper_source_run', 'source', 'run_at'),
    )

    def __repr__(self):
        return f'<ScraperLog {self.source}:{self.run_at}>'


class UserSuggestion(db.Model):
    """
    User feedback and suggestions for improving the platform.

    Allows users to suggest new data sources, request features,
    report bugs, or provide other feedback.
    """
    __tablename__ = 'user_suggestions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    suggestion_type = db.Column(
        db.String(50),
        nullable=False
    )  # 'new_data_source', 'feature_request', 'bug_report', 'other'
    description = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(
        db.String(20),
        default='pending',
        nullable=False
    )  # 'pending', 'reviewed', 'implemented'

    def __repr__(self):
        return f'<UserSuggestion {self.user_id}:{self.suggestion_type}>'


class ReadingFolder(db.Model):
    """
    A folder to organize saved publications.

    Users can create custom folders/projects to organize their saved
    publications (e.g., "Kenya PrEP Research", "Q1 Grant Proposal").
    """
    __tablename__ = 'reading_folders'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship to saved publications in this folder
    saved_publications = db.relationship(
        'SavedPublication',
        backref='folder',
        lazy='dynamic'
    )

    # Ensure folder names are unique per user
    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='unique_user_folder_name'),
    )

    def __repr__(self):
        return f'<ReadingFolder {self.user_id}:{self.name}>'


class SavedPublication(db.Model):
    """
    A publication saved to a user's reading list.

    Users can save publications for later reading, optionally organizing
    them into folders. Includes notes and read/unread status.
    """
    __tablename__ = 'saved_publications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    publication_id = db.Column(
        db.Integer,
        db.ForeignKey('publications.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    folder_id = db.Column(
        db.Integer,
        db.ForeignKey('reading_folders.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )  # NULL = "Unfiled"
    saved_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, default=False)

    # Relationship to publication
    publication = db.relationship('Publication', backref='saved_by_users')

    # Ensure a user can only save each publication once
    __table_args__ = (
        db.UniqueConstraint('user_id', 'publication_id', name='unique_user_publication'),
        db.Index('idx_user_folder', 'user_id', 'folder_id'),
    )

    def __repr__(self):
        return f'<SavedPublication {self.user_id}:{self.publication_id}>'
