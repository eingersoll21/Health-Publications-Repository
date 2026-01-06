"""
Database models for the CHAI Health Publications Tracker.

This file defines all database tables:
- User: Registered users with their preferences
- UserProgramPreference: Links users to their chosen health programs (with optional subtopics)
- UserRegionPreference: Links users to their chosen geographic regions
- Publication: Publications from WHO and PubMed
- PublicationProgramArea: Links publications to relevant program areas
- PublicationSubtopic: Links publications to specific subtopics within program areas
- PublicationRegion: Links publications to detected geographic regions
- DigestLog: Tracks which publications were sent to which users
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Digest preferences
    digest_frequency = db.Column(
        db.String(20),
        default='weekly',
        nullable=False
    )  # Options: 'daily', 'weekly', 'biweekly', 'monthly'
    last_digest_sent = db.Column(db.DateTime, nullable=True)

    # Filter mode: how to combine program and region filters
    # Options: 'program_only', 'region_only', 'program_and_region'
    filter_mode = db.Column(
        db.String(30),
        default='program_only',
        nullable=False
    )

    # Relationships
    program_preferences = db.relationship(
        'UserProgramPreference',
        backref='user',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )
    region_preferences = db.relationship(
        'UserRegionPreference',
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

    def set_password(self, password):
        """Hash and store the password. Never store plain text passwords."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a password against the stored hash."""
        return check_password_hash(self.password_hash, password)

    def get_selected_program_keys(self):
        """Get list of program area keys this user has selected (any subtopic selection counts)."""
        return list(set(pref.program_area_key for pref in self.program_preferences))

    def get_selected_region_keys(self):
        """Get list of region keys this user has selected."""
        return [pref.region_key for pref in self.region_preferences]

    def get_program_preferences_detail(self):
        """
        Get detailed program preferences including subtopic selections.

        Returns:
            Dictionary mapping program_area_key to list of subtopic_keys.
            If subtopic_key is None in the list, user wants ALL subtopics.
        """
        result = {}
        for pref in self.program_preferences:
            if pref.program_area_key not in result:
                result[pref.program_area_key] = []
            result[pref.program_area_key].append(pref.subtopic_key)
        return result

    def wants_all_subtopics(self, program_key):
        """Check if user wants all subtopics for a program area (None in preferences)."""
        prefs = self.get_program_preferences_detail()
        if program_key not in prefs:
            return False
        return None in prefs[program_key]

    def get_selected_subtopics(self, program_key):
        """Get list of selected subtopic keys for a program area."""
        prefs = self.get_program_preferences_detail()
        if program_key not in prefs:
            return []
        return [st for st in prefs[program_key] if st is not None]

    def __repr__(self):
        return f'<User {self.email}>'


class UserProgramPreference(db.Model):
    """
    Links a user to a CHAI program area (and optionally specific subtopic) they're interested in.

    If subtopic_key is NULL, user wants ALL subtopics within that program area.
    If subtopic_key is set, user only wants that specific subtopic.

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

    # Ensure a user can only select each program/subtopic combination once
    __table_args__ = (
        db.UniqueConstraint('user_id', 'program_area_key', 'subtopic_key', name='unique_user_program_subtopic'),
    )

    def __repr__(self):
        if self.subtopic_key:
            return f'<UserProgramPreference {self.user_id}:{self.program_area_key}:{self.subtopic_key}>'
        return f'<UserProgramPreference {self.user_id}:{self.program_area_key}:ALL>'


class UserRegionPreference(db.Model):
    """
    Links a user to a geographic region they're interested in.
    One user can have multiple region preferences.
    """
    __tablename__ = 'user_region_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    region_key = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Ensure a user can only select each region once
    __table_args__ = (
        db.UniqueConstraint('user_id', 'region_key', name='unique_user_region'),
    )

    def __repr__(self):
        return f'<UserRegionPreference {self.user_id}:{self.region_key}>'


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
    Links a publication to a relevant CHAI program area.

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
