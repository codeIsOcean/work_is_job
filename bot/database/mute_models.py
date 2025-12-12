from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Index

from bot.database.models import Base, utcnow


class GroupMute(Base):
    __tablename__ = "group_mutes"
    __table_args__ = (
        Index("ix_group_mutes_group_id", "group_id"),
        Index("ix_group_mutes_target_user_id", "target_user_id"),
        Index("ix_group_mutes_admin_user_id", "admin_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, nullable=False)
    target_user_id = Column(BigInteger, nullable=False)
    admin_user_id = Column(BigInteger, nullable=False)
    reaction = Column(String(16), nullable=False)
    mute_until = Column(DateTime, nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class UserScore(Base):
    __tablename__ = "user_scores"

    user_id = Column(BigInteger, primary_key=True)
    score = Column(Integer, nullable=False, default=0)


class SpammerRecord(Base):
    __tablename__ = "spammers"

    user_id = Column(BigInteger, primary_key=True)
    risk_score = Column(Integer, nullable=False, default=0)
    reason = Column(String, nullable=True)
    incidents = Column(Integer, nullable=False, default=1)
    last_incident_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


