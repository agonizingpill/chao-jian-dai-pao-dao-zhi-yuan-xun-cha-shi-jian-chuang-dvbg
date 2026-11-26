from sqlalchemy import CheckConstraint, Column, ForeignKey, JSON, String, Table

from core.db import metadata


rework_batches = Table('rework_batches', metadata,
    Column('code', String(64), primary_key=True),
    Column('request_key', String(160), nullable=False, unique=True),
    Column('route', String(160), ForeignKey('trail_routes.code'), nullable=False),
    Column('plan', JSON, nullable=False),
    CheckConstraint("length(request_key) >= 1"),
)
