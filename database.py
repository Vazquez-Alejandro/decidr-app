import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./decidr.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String, nullable=True)
    public_key = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    bio = Column(String, nullable=True)
    avatar = Column(String, nullable=True)
    theme = Column(Text, nullable=True)
    pin = Column(String, unique=True, index=True, nullable=True)
    phone = Column(String, nullable=True)
    mp_access_token = Column(String, nullable=True)
    payment_pin_hash = Column(String, nullable=True)
    emergency_contact = Column(String, nullable=True)
    remote_disable_code_hash = Column(String, nullable=True)
    payments_disabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class BlockedUserDB(Base):
    __tablename__ = "blocked_users"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    blocked_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    blocker = relationship("UserDB", foreign_keys=[user_id])
    blocked = relationship("UserDB", foreign_keys=[blocked_id])


class ChatDB(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class MessageDB(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String)
    nonce = Column(String, nullable=True)
    sender_id = Column(Integer, ForeignKey("users.id"), default=1)
    chat_id = Column(Integer, ForeignKey("chats.id"), default=1)
    is_game_result = Column(Boolean, default=False)
    edited = Column(Boolean, default=False)
    deleted = Column(Boolean, default=False)
    reply_to = Column(Integer, nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    sender = relationship("UserDB")
    chat = relationship("ChatDB")


class RoomDB(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    creator_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    creator = relationship("UserDB")


class RoomMemberDB(Base):
    __tablename__ = "room_members"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    joined_at = Column(DateTime, default=datetime.datetime.utcnow)
    room = relationship("RoomDB")
    user = relationship("UserDB")


class ScheduledMessageDB(Base):
    __tablename__ = "scheduled_messages"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    nonce = Column(String, nullable=True)
    sender_client_id = Column(String, nullable=False)
    sender_name = Column(String, nullable=False)
    target_username = Column(String, nullable=True)
    room = Column(String, default="default_room")
    scheduled_at = Column(DateTime, nullable=False)
    sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class FileDB(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, index=True)
    original_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    stored_path = Column(String, nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id"))
    room_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    uploader = relationship("UserDB")


class PushSubscriptionDB(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    endpoint = Column(String, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    user = relationship("UserDB")


Base.metadata.create_all(bind=engine)
