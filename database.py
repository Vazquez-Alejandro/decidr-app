from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, ForeignKey, LargeBinary
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
import datetime

DATABASE_URL = "sqlite:///./decidr.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String, nullable=True)
    public_key = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


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


Base.metadata.create_all(bind=engine)
