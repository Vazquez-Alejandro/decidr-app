import os
import random
import string
import json
import asyncio
import datetime
import time
import secrets
from pathlib import Path
from collections import defaultdict
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from fastapi.datastructures import UploadFile as UploadFileType
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_
from database import SessionLocal, MessageDB, UserDB, ChatDB, RoomDB, RoomMemberDB, BlockedUserDB, ScheduledMessageDB, FileDB, ReactionDB, PollDB, PollOptionDB, PollVoteDB, ReminderDB, PushSubscriptionDB, engine, Base
import bcrypt
import jwt
from pydantic import BaseModel
from pywebpush import webpush, WebPushException

Base.metadata.create_all(bind=engine)

# ─── JWT ────────────────────────────────────────────────────────────
_SECRET_FILE = Path(__file__).parent / ".jwt_secret"
JWT_SECRET = os.environ.get("JWT_SECRET") or (
    _SECRET_FILE.read_text().strip() if _SECRET_FILE.exists() else ""
)
if not JWT_SECRET:
    JWT_SECRET = secrets.token_hex(64)
    _SECRET_FILE.write_text(JWT_SECRET)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY = int(os.environ.get("JWT_EXPIRY", 24 * 3600))

# ─── Mercado Pago ─────────────────────────────────────────────────
_MP_TOKEN_FILE = Path(__file__).parent / ".mp_token"
MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN") or (
    _MP_TOKEN_FILE.read_text().strip() if _MP_TOKEN_FILE.exists() else ""
)

# ─── VAPID keys for push notifications ────────────────────────────
_VAPID_FILE = Path(__file__).parent / ".vapid_keys"
if _VAPID_FILE.exists():
    VAPID_PRIVATE_KEY = _VAPID_FILE.read_text().strip()
    VAPID_PUBLIC_KEY = (Path(__file__).parent / ".vapid_public").read_text().strip()
else:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from base64 import urlsafe_b64encode
    private_key = ec.generate_private_key(ec.SECP256R1())
    VAPID_PRIVATE_KEY = urlsafe_b64encode(
        private_key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()
        )
    ).decode().rstrip("=")
    public_key = private_key.public_key()
    VAPID_PUBLIC_KEY = urlsafe_b64encode(
        public_key.public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint
        )
    ).decode().rstrip("=")
    _VAPID_FILE.write_text(VAPID_PRIVATE_KEY)
    (Path(__file__).parent / ".vapid_public").write_text(VAPID_PUBLIC_KEY)
VAPID_CLAIMS = {"sub": "mailto:decidr@app.local"}


def create_token(user_id: int, username: str):
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(seconds=JWT_EXPIRY),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


# ─── Rate limiter ───────────────────────────────────────────────────
class RateLimiter:
    def __init__(self, max_requests=120, window=60):
        self.max_requests = max_requests
        self.window = window
        self.requests: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str) -> bool:
        now = time.time()
        self.requests[key] = [t for t in self.requests[key] if now - t < self.window]
        if len(self.requests[key]) >= self.max_requests:
            return True
        self.requests[key].append(now)
        return False


limiter = RateLimiter()

# ─── App ────────────────────────────────────────────────────────────
app = FastAPI(docs_url=None, redoc_url=None)

INDEX_HTML = Path(__file__).parent / "index.html"
STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ─── Security headers ───────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ─── Auth models ────────────────────────────────────────────────────
class AuthRequest(BaseModel):
    username: str
    password: str
    phone: str | None = None


# ─── PIN generator ─────────────────────────────────────────────────
def generate_pin(db: Session) -> str:
    import string as str_mod
    chars = string.ascii_uppercase + string.digits
    for _ in range(100):
        pin = ''.join(secrets.choice(chars) for _ in range(6))
        existing = db.query(UserDB).filter(UserDB.pin == pin).first()
        if not existing:
            return pin
    raise RuntimeError("No se pudo generar un PIN único")


# ─── Auth routes ────────────────────────────────────────────────────
@app.post("/register")
async def register(req: AuthRequest):
    if limiter.is_limited(req.username):
        return JSONResponse({"error": "Demasiadas solicitudes"}, status_code=429)
    if not (3 <= len(req.username) <= 20) or not req.password:
        return JSONResponse({"error": "Usuario (3-20 chars) y contraseña requeridos"}, status_code=400)
    db = SessionLocal()
    try:
        existing = db.query(UserDB).filter(UserDB.username == req.username).first()
        if existing:
            return JSONResponse({"error": "Usuario ya existe"}, status_code=409)
        hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt())
        pin = generate_pin(db)
        phone = req.phone.strip() if req.phone else None
        user = UserDB(username=req.username, password_hash=hashed.decode(), pin=pin, phone=phone)
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_token(user.id, user.username)
        return {"token": token, "username": user.username, "user_id": user.id, "pin": user.pin}
    finally:
        db.close()


@app.post("/login")
async def login(req: AuthRequest):
    if limiter.is_limited(req.username):
        return JSONResponse({"error": "Demasiadas solicitudes"}, status_code=429)
    db = SessionLocal()
    try:
        user = db.query(UserDB).filter(UserDB.username == req.username).first()
        if not user or not bcrypt.checkpw(req.password.encode(), user.password_hash.encode()):
            return JSONResponse({"error": "Usuario o contraseña incorrectos"}, status_code=401)
        token = create_token(user.id, user.username)
        return {"token": token, "username": user.username, "user_id": user.id}
    finally:
        db.close()


@app.get("/")
async def get_index():
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


# ─── Room endpoints ────────────────────────────────────────────────
def get_token_user(token: str):
    payload = verify_token(token)
    if not payload:
        return None
    return {"id": int(payload["sub"]), "username": payload["username"]}


@app.post("/rooms")
async def create_room(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    name = body.get("name", "").strip()
    if not name or len(name) > 50:
        return JSONResponse({"error": "Nombre inválido"}, status_code=400)
    is_channel = body.get("is_channel", False)
    db = SessionLocal()
    try:
        existing_room = db.query(RoomDB).filter(RoomDB.name == name).first()
        if existing_room:
            existing_member = db.query(RoomMemberDB).filter(
                RoomMemberDB.room_id == existing_room.id,
                RoomMemberDB.user_id == user["id"]
            ).first()
            if not existing_member:
                member = RoomMemberDB(room_id=existing_room.id, user_id=user["id"])
                db.add(member)
                db.commit()
            return {"id": existing_room.id, "name": existing_room.name, "is_channel": existing_room.is_channel}
        room = RoomDB(name=name, creator_id=user["id"], is_channel=is_channel)
        db.add(room)
        db.commit()
        db.refresh(room)
        member = RoomMemberDB(room_id=room.id, user_id=user["id"], is_admin=True)
        db.add(member)
        db.commit()
        return {"id": room.id, "name": room.name, "is_channel": room.is_channel, "created_at": room.created_at.isoformat()}
    finally:
        db.close()


@app.get("/rooms")
async def list_rooms(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        memberships = db.query(RoomMemberDB).filter(RoomMemberDB.user_id == user["id"]).all()
        room_ids = [m.room_id for m in memberships]
        rooms = db.query(RoomDB).filter(RoomDB.id.in_(room_ids)).all()
        result = []
        for r in rooms:
            member_count = db.query(RoomMemberDB).filter(RoomMemberDB.room_id == r.id).count()
            is_dm = r.name.startswith("__dm__") if r.name else False
            membership = db.query(RoomMemberDB).filter(
                RoomMemberDB.room_id == r.id, RoomMemberDB.user_id == user["id"]
            ).first()
            user_is_admin = membership.is_admin if membership else False
            display_name = r.name
            if is_dm:
                members = db.query(RoomMemberDB).filter(RoomMemberDB.room_id == r.id).all()
                for m in members:
                    if m.user_id != user["id"]:
                        other = db.query(UserDB).filter(UserDB.id == m.user_id).first()
                        if other:
                            display_name = other.display_name or other.username
                        break
            result.append({
                "id": r.id,
                "name": display_name,
                "member_count": member_count,
                "is_dm": is_dm,
                "is_channel": r.is_channel,
                "is_admin": user_is_admin,
                "created_at": r.created_at.isoformat()
            })
        return {"rooms": result}
    finally:
        db.close()


@app.post("/rooms/{room_id}/join")
async def join_room(room_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        room = db.query(RoomDB).filter(RoomDB.id == room_id).first()
        if not room:
            return JSONResponse({"error": "Sala no encontrada"}, status_code=404)
        existing = db.query(RoomMemberDB).filter(
            RoomMemberDB.room_id == room_id, RoomMemberDB.user_id == user["id"]
        ).first()
        if not existing:
            member = RoomMemberDB(room_id=room_id, user_id=user["id"])
            db.add(member)
            db.commit()
        return {"id": room.id, "name": room.name}
    finally:
        db.close()


def is_room_admin(db: Session, room_id: int, user_id: int) -> bool:
    member = db.query(RoomMemberDB).filter(
        RoomMemberDB.room_id == room_id,
        RoomMemberDB.user_id == user_id
    ).first()
    return member is not None and member.is_admin


@app.get("/rooms/{room_id}/members")
async def get_room_members(room_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        room = db.query(RoomDB).filter(RoomDB.id == room_id).first()
        if not room:
            return JSONResponse({"error": "Sala no encontrada"}, status_code=404)
        member_rows = db.query(RoomMemberDB).filter(RoomMemberDB.room_id == room_id).all()
        members = []
        for m in member_rows:
            u = db.query(UserDB).filter(UserDB.id == m.user_id).first()
            if u:
                members.append({
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name or u.username,
                    "is_admin": m.is_admin,
                    "joined_at": m.joined_at.isoformat() if m.joined_at else None,
                })
        return {"members": members}
    finally:
        db.close()


@app.post("/rooms/{room_id}/members")
async def add_room_member(room_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        if not is_room_admin(db, room_id, user["id"]):
            return JSONResponse({"error": "Solo admins pueden agregar miembros"}, status_code=403)
        body = await req.json()
        username = body.get("username")
        target = db.query(UserDB).filter(UserDB.username == username).first()
        if not target:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        existing = db.query(RoomMemberDB).filter(
            RoomMemberDB.room_id == room_id,
            RoomMemberDB.user_id == target.id
        ).first()
        if existing:
            return JSONResponse({"error": "Ya es miembro"}, status_code=400)
        member = RoomMemberDB(room_id=room_id, user_id=target.id)
        db.add(member)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.delete("/rooms/{room_id}/members/{username}")
async def remove_room_member(room_id: int, username: str, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        if not is_room_admin(db, room_id, user["id"]):
            return JSONResponse({"error": "Solo admins pueden expulsar miembros"}, status_code=403)
        target = db.query(UserDB).filter(UserDB.username == username).first()
        if not target:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        member = db.query(RoomMemberDB).filter(
            RoomMemberDB.room_id == room_id,
            RoomMemberDB.user_id == target.id
        ).first()
        if not member:
            return JSONResponse({"error": "No es miembro"}, status_code=404)
        db.delete(member)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.put("/rooms/{room_id}/members/{username}")
async def toggle_room_admin(room_id: int, username: str, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        if not is_room_admin(db, room_id, user["id"]):
            return JSONResponse({"error": "Solo admins pueden cambiar roles"}, status_code=403)
        body = await req.json()
        make_admin = body.get("admin", True)
        target = db.query(UserDB).filter(UserDB.username == username).first()
        if not target:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        member = db.query(RoomMemberDB).filter(
            RoomMemberDB.room_id == room_id,
            RoomMemberDB.user_id == target.id
        ).first()
        if not member:
            return JSONResponse({"error": "No es miembro"}, status_code=404)
        member.is_admin = make_admin
        db.commit()
        return {"ok": True, "is_admin": member.is_admin}
    finally:
        db.close()
async def delete_room(room_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        room = db.query(RoomDB).filter(RoomDB.id == room_id).first()
        if not room:
            return JSONResponse({"error": "Sala no encontrada"}, status_code=404)
        # Remove all members
        db.query(RoomMemberDB).filter(RoomMemberDB.room_id == room_id).delete()
        # Remove all messages
        db.query(MessageDB).filter(MessageDB.chat_id == room_id).delete()
        # Remove the room
        db.delete(room)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ─── Room key storage for E2EE ────────────────────────────────────
@app.post("/rooms/{room_id}/key")
async def store_room_key(room_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    encrypted_key = body.get("encrypted_key")
    if not encrypted_key:
        return JSONResponse({"error": "Falta encrypted_key"}, status_code=400)
    db = SessionLocal()
    try:
        member = db.query(RoomMemberDB).filter(
            RoomMemberDB.room_id == room_id, RoomMemberDB.user_id == user["id"]
        ).first()
        if not member:
            return JSONResponse({"error": "No sos miembro"}, status_code=403)
        user_obj = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if user_obj:
            # Store encrypted room key on user metadata or a dedicated table
            # For simplicity, we use a JSON field or just broadcast via WS
            pass
        return {"ok": True}
    finally:
        db.close()


# ─── Profile & Block endpoints ────────────────────────────────────
AVATAR_DIR = STATIC_DIR / "avatars"
AVATAR_DIR.mkdir(exist_ok=True)
UPLOADS_DIR = STATIC_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


@app.put("/profile")
async def update_profile(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u:
            return JSONResponse({"error": "No encontrado"}, status_code=404)
        if "display_name" in body:
            u.display_name = body["display_name"][:30]
        if "bio" in body:
            u.bio = body["bio"][:150]
        if "theme" in body:
            u.theme = body["theme"]
        if "phone" in body:
            u.phone = body["phone"][:20] if body["phone"] else None
        db.commit()
        return {"ok": True, "display_name": u.display_name, "bio": u.bio}
    finally:
        db.close()


@app.post("/profile/avatar")
async def upload_avatar(req: Request, file: UploadFile = File(...)):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    if file.content_type not in ("image/jpeg", "image/png", "image/webp"):
        return JSONResponse({"error": "Formato no soportado (JPEG, PNG, WebP)"}, status_code=400)
    ext = file.filename.split(".")[-1] if "." in (file.filename or "") else "jpg"
    fname = f"avatar_{user['id']}_{int(time.time())}.{ext}"
    fpath = AVATAR_DIR / fname
    content = await file.read()
    fpath.write_bytes(content)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if u:
            u.avatar = f"/static/avatars/{fname}"
            db.commit()
        return {"ok": True, "avatar": u.avatar if u else None}
    finally:
        db.close()


@app.get("/profile/{username}")
async def get_profile(username: str, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.username == username).first()
        if not u:
            return JSONResponse({"error": "No encontrado"}, status_code=404)
        return {
            "username": u.username,
            "display_name": u.display_name,
            "bio": u.bio,
            "avatar": u.avatar,
            "pin": u.pin,
            "phone": u.phone,
            "has_payment_pin": u.payment_pin_hash is not None,
            "emergency_contact": u.emergency_contact or None,
            "payments_disabled": u.payments_disabled or False,
            "is_emergency_contact": u.emergency_contact == user["username"]
        }
    finally:
        db.close()


@app.get("/me/pin")
async def get_my_pin(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u:
            return JSONResponse({"error": "No encontrado"}, status_code=404)
        return {"pin": u.pin}
    finally:
        db.close()


@app.post("/profile/block/{username}")
async def block_user(username: str, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    if username == user["username"]:
        return JSONResponse({"error": "No te podés bloquear a vos mismo"}, status_code=400)
    db = SessionLocal()
    try:
        target = db.query(UserDB).filter(UserDB.username == username).first()
        if not target:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        existing = db.query(BlockedUserDB).filter(
            BlockedUserDB.user_id == user["id"], BlockedUserDB.blocked_id == target.id
        ).first()
        if not existing:
            b = BlockedUserDB(user_id=user["id"], blocked_id=target.id)
            db.add(b)
            db.commit()
        return {"ok": True, "blocked": username}
    finally:
        db.close()


@app.delete("/profile/block/{username}")
async def unblock_user(username: str, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        target = db.query(UserDB).filter(UserDB.username == username).first()
        if target:
            db.query(BlockedUserDB).filter(
                BlockedUserDB.user_id == user["id"], BlockedUserDB.blocked_id == target.id
            ).delete()
            db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/users/search")
async def search_users(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    q = req.query_params.get("q", "").strip()
    if not q or len(q) < 1:
        return JSONResponse({"error": "Búsqueda muy corta"}, status_code=400)
    db = SessionLocal()
    try:
        users = db.query(UserDB).filter(
            or_(
                UserDB.username.ilike(f"%{q}%"),
                UserDB.pin.ilike(f"%{q}%"),
                UserDB.phone.ilike(f"%{q}%"),
            ),
            UserDB.id != user["id"]
        ).limit(20).all()
        return {"users": [{"username": u.username, "display_name": u.display_name, "pin": u.pin, "is_emergency_contact": u.emergency_contact == user["username"]} for u in users]}
    finally:
        db.close()


# ─── Mercado Pago ──────────────────────────────────────────────────
MP_API = "https://api.mercadopago.com"


@app.post("/payments/create")
async def create_payment(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    amount = body.get("amount")
    concept = (body.get("concept") or "Pago Decidr").strip()[:50]
    room = body.get("room", "default_room")
    if not amount or amount <= 0:
        return JSONResponse({"error": "Monto inválido"}, status_code=400)
    # Verify payment PIN if set
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        if u.payments_disabled:
            return JSONResponse({"error": "Los pagos están desactivados para esta cuenta"}, status_code=403)
        if u.payment_pin_hash:
            pin = body.get("payment_pin", "")
            if not pin or not bcrypt.checkpw(pin.encode(), u.payment_pin_hash.encode()):
                return JSONResponse({"error": "PIN de pago incorrecto"}, status_code=403)
        access_token = MP_ACCESS_TOKEN
        if not access_token and u and u.mp_access_token:
            access_token = u.mp_access_token
    finally:
        db.close()
    if not access_token:
        return JSONResponse({"error": "No hay token de Mercado Pago configurado"}, status_code=400)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{MP_API}/checkout/preferences",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "items": [{
                        "title": concept,
                        "quantity": 1,
                        "unit_price": float(amount),
                        "currency_id": "ARS"
                    }],
                    "back_urls": {
                        "success": "/",
                        "failure": "/",
                        "pending": "/"
                    },
                    "auto_return": "approved",
                    "purpose": "wallet_purchase"
                },
                timeout=15
            )
            data = resp.json()
            if resp.status_code != 201:
                return JSONResponse({"error": f"Error MP: {data.get('message', 'desconocido')}"}, status_code=400)
            init_point = data.get("init_point") or data.get("sandbox_init_point")
            pref_id = data.get("id")
            return {
                "ok": True,
                "init_point": init_point,
                "pref_id": pref_id,
                "amount": float(amount),
                "concept": concept
            }
    except Exception as e:
        return JSONResponse({"error": f"Error de conexión con MP: {str(e)}"}, status_code=500)


@app.post("/profile/mp-token")
async def set_mp_token(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    mp_token = (body.get("mp_access_token") or "").strip()
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u:
            return JSONResponse({"error": "No encontrado"}, status_code=404)
        u.mp_access_token = mp_token or None
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.post("/profile/payment-pin")
async def set_payment_pin(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    pin = body.get("pin", "")
    current_password = body.get("current_password", "")
    if not pin or not pin.isdigit() or len(pin) < 4 or len(pin) > 6:
        return JSONResponse({"error": "PIN debe ser numérico de 4 a 6 dígitos"}, status_code=400)
    if not current_password:
        return JSONResponse({"error": "Contraseña actual requerida"}, status_code=400)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u or not u.password_hash or not bcrypt.checkpw(current_password.encode(), u.password_hash.encode()):
            return JSONResponse({"error": "Contraseña incorrecta"}, status_code=403)
        u.payment_pin_hash = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.post("/profile/emergency")
async def set_emergency_contact(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    contact = (body.get("emergency_contact") or "").strip()
    code = body.get("remote_disable_code", "")
    current_password = body.get("current_password", "")
    if not current_password:
        return JSONResponse({"error": "Contraseña actual requerida"}, status_code=400)
    if code and (not code.isdigit() or len(code) < 4 or len(code) > 6):
        return JSONResponse({"error": "Código: 4 a 6 dígitos numéricos"}, status_code=400)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u or not u.password_hash or not bcrypt.checkpw(current_password.encode(), u.password_hash.encode()):
            return JSONResponse({"error": "Contraseña incorrecta"}, status_code=403)
        u.emergency_contact = contact or None
        if code:
            u.remote_disable_code_hash = bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()
        elif not contact:
            u.remote_disable_code_hash = None
        return {"ok": True}
    finally:
        db.close()


@app.post("/payments/remote-disable")
async def remote_disable_payments(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    target_username = (body.get("target_username") or "").strip()
    code = body.get("code", "")
    if not target_username or not code:
        return JSONResponse({"error": "Faltan datos"}, status_code=400)
    db = SessionLocal()
    try:
        target = db.query(UserDB).filter(UserDB.username == target_username).first()
        if not target:
            return JSONResponse({"error": "Usuario destino no encontrado"}, status_code=404)
        if target.emergency_contact != user["username"]:
            return JSONResponse({"error": "No sos el contacto de emergencia de este usuario"}, status_code=403)
        if not target.remote_disable_code_hash or not bcrypt.checkpw(code.encode(), target.remote_disable_code_hash.encode()):
            return JSONResponse({"error": "Código de desactivación incorrecto"}, status_code=403)
        target.payments_disabled = True
        db.commit()
        return {"ok": True, "message": f"Pagos desactivados para @{target_username}"}
    finally:
        db.close()


@app.post("/payments/remote-enable")
async def remote_enable_payments(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    target_username = (body.get("target_username") or "").strip()
    code = body.get("code", "")
    if not target_username or not code:
        return JSONResponse({"error": "Faltan datos"}, status_code=400)
    db = SessionLocal()
    try:
        target = db.query(UserDB).filter(UserDB.username == target_username).first()
        if not target:
            return JSONResponse({"error": "Usuario destino no encontrado"}, status_code=404)
        if target.emergency_contact != user["username"]:
            return JSONResponse({"error": "No sos el contacto de emergencia de este usuario"}, status_code=403)
        if not target.remote_disable_code_hash or not bcrypt.checkpw(code.encode(), target.remote_disable_code_hash.encode()):
            return JSONResponse({"error": "Código de desactivación incorrecto"}, status_code=403)
        target.payments_disabled = False
        db.commit()
        return {"ok": True, "message": f"Pagos reactivados para @{target_username}"}
    finally:
        db.close()


@app.post("/admin/mp-token")
async def set_global_mp_token(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    # Only allow user "Alejandro" to set global token (simple admin check)
    if user["username"] != "Alejandro":
        return JSONResponse({"error": "Solo el admin puede configurar esto"}, status_code=403)
    body = await req.json()
    mp_token = (body.get("mp_access_token") or "").strip()
    if not mp_token:
        return JSONResponse({"error": "Token requerido"}, status_code=400)
    global MP_ACCESS_TOKEN
    MP_ACCESS_TOKEN = mp_token
    _MP_TOKEN_FILE.write_text(mp_token)
    return {"ok": True}


@app.get("/payments/{pref_id}")
async def get_payment_status(pref_id: str, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    access_token = MP_ACCESS_TOKEN
    if not access_token:
        return JSONResponse({"error": "No hay token MP"}, status_code=400)
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{MP_API}/checkout/preferences/{pref_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )
            if resp.status_code != 200:
                return {"status": "unknown"}
            data = resp.json()
            return {"status": data.get("status", "unknown")}
    except Exception:
        return {"status": "unknown"}


@app.post("/rooms/dm/{username}")
async def create_dm(username: str, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        target = db.query(UserDB).filter(UserDB.username == username).first()
        if not target:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        if target.id == user["id"]:
            return JSONResponse({"error": "No te podés DM a vos mismo"}, status_code=400)
        ids = sorted([user["id"], target.id])
        dm_name = f"__dm__{ids[0]}_{ids[1]}"
        existing = db.query(RoomDB).filter(RoomDB.name == dm_name).first()
        if existing:
            return {"id": existing.id, "name": target.display_name or target.username, "is_dm": True}
        room = RoomDB(name=dm_name, creator_id=user["id"])
        db.add(room)
        db.commit()
        db.refresh(room)
        for uid in [user["id"], target.id]:
            member = RoomMemberDB(room_id=room.id, user_id=uid)
            db.add(member)
        db.commit()
        # Notify the other user about the new DM
        await manager.send_to(target.username, {
            "type": "new_dm",
            "room_id": room.id,
            "from": user["username"]
        })
        return {"id": room.id, "name": target.display_name or target.username, "is_dm": True}
    finally:
        db.close()


# ─── File upload ────────────────────────────────────────────────────
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@app.post("/files/upload")
async def upload_file(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    encrypted_data = body.get("data", "")
    mime_type = body.get("mime", "application/octet-stream")
    original_name = body.get("name", "file")
    file_size = body.get("size", 0)
    room_id = body.get("room_id")
    view_once = body.get("view_once", False)
    if not encrypted_data:
        return JSONResponse({"error": "Faltan datos"}, status_code=400)
    if file_size > MAX_FILE_SIZE:
        return JSONResponse({"error": "Archivo muy grande (máx 50 MB)"}, status_code=400)
    # Decode base64 and store
    try:
        raw = __import__("base64").b64decode(encrypted_data)
    except Exception:
        return JSONResponse({"error": "Datos inválidos"}, status_code=400)
    stored_name = f"file_{user['id']}_{int(time.time())}_{secrets.token_hex(4)}.enc"
    fpath = UPLOADS_DIR / stored_name
    fpath.write_bytes(raw)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        file_rec = FileDB(
            original_name=original_name,
            mime_type=mime_type,
            file_size=file_size,
            stored_path=str(fpath),
            uploader_id=user["id"],
            room_id=room_id,
            view_once=view_once
        )
        db.add(file_rec)
        db.commit()
        db.refresh(file_rec)
        return {"ok": True, "file_id": file_rec.id}
    finally:
        db.close()


@app.get("/files/{file_id}")
async def get_file(file_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        f = db.query(FileDB).filter(FileDB.id == file_id).first()
        if not f:
            return JSONResponse({"error": "Archivo no encontrado"}, status_code=404)
        if f.view_once and f.viewed:
            return JSONResponse({"error": "Esta imagen ya fue vista"}, status_code=410)
        # Verify room membership if room_id is set
        if f.room_id:
            member = db.query(RoomMemberDB).filter(
                RoomMemberDB.room_id == f.room_id,
                RoomMemberDB.user_id == user["id"]
            ).first()
            if not member and f.uploader_id != user["id"]:
                return JSONResponse({"error": "No autorizado"}, status_code=403)
        return FileResponse(
            f.stored_path,
            media_type="application/octet-stream",
            headers={
                "X-File-Id": str(f.id),
                "X-File-Name": f.original_name,
                "X-File-Mime": f.mime_type,
                "X-File-Size": str(f.file_size),
                "Content-Disposition": f'attachment; filename="{f.original_name}"',
            }
        )
    finally:
        db.close()


@app.post("/files/{file_id}/mark-viewed")
async def mark_file_viewed(file_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        f = db.query(FileDB).filter(FileDB.id == file_id).first()
        if not f:
            return JSONResponse({"error": "Archivo no encontrado"}, status_code=404)
        # Don't count the uploader's own view
        if f.uploader_id == user["id"]:
            return {"ok": True, "self": True}
        f.viewed = True
        # Delete the file data from disk
        p = Path(f.stored_path)
        if p.exists():
            p.unlink()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/rooms/{room_id}/search")
async def search_room_messages(room_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    q = req.query_params.get("q", "").strip()
    if not q:
        return {"messages": []}
    db = SessionLocal()
    try:
        chat = db.query(ChatDB).filter(ChatDB.name == str(room_id)).first()
        if not chat:
            return {"messages": []}
        messages = db.query(MessageDB).filter(
            MessageDB.chat_id == chat.id,
            MessageDB.deleted == False,
            MessageDB.content.ilike(f"%{q}%")
        ).order_by(MessageDB.timestamp.desc()).limit(30).all()
        result = []
        for m in messages:
            sender = db.query(UserDB).filter(UserDB.id == m.sender_id).first()
            result.append({
                "id": m.id,
                "content": m.content,
                "nonce": m.nonce,
                "sender": sender.username if sender else "desconocido",
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "is_game_result": m.is_game_result,
                "edited": m.edited,
            })
        return {"messages": result}
    finally:
        db.close()


# ─── Message edit/delete ────────────────────────────────────────────
@app.put("/messages/{message_id}")
async def edit_message(message_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    content = body.get("content", "")
    nonce = body.get("nonce")
    if not content:
        return JSONResponse({"error": "Contenido requerido"}, status_code=400)
    db = SessionLocal()
    try:
        msg = db.query(MessageDB).filter(MessageDB.id == message_id).first()
        if not msg:
            return JSONResponse({"error": "Mensaje no encontrado"}, status_code=404)
        sender = db.query(UserDB).filter(UserDB.id == msg.sender_id).first()
        if not sender or sender.username != user["username"]:
            return JSONResponse({"error": "No podés editar mensajes de otros"}, status_code=403)
        if msg.deleted:
            return JSONResponse({"error": "Mensaje eliminado"}, status_code=400)
        msg.content = content
        msg.nonce = nonce
        msg.edited = True
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.delete("/messages/{message_id}")
async def delete_message(message_id: int, req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        msg = db.query(MessageDB).filter(MessageDB.id == message_id).first()
        if not msg:
            return JSONResponse({"error": "Mensaje no encontrado"}, status_code=404)
        sender = db.query(UserDB).filter(UserDB.id == msg.sender_id).first()
        if not sender or sender.username != user["username"]:
            return JSONResponse({"error": "No podés eliminar mensajes de otros"}, status_code=403)
        msg.deleted = True
        msg.content = None
        msg.nonce = None
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ─── Push notifications ────────────────────────────────────────────
DERIVED_VAPID_PRIVATE = None  # lazy


def get_vapid_private():
    global DERIVED_VAPID_PRIVATE
    if DERIVED_VAPID_PRIVATE:
        return DERIVED_VAPID_PRIVATE
    from base64 import urlsafe_b64decode
    der = urlsafe_b64decode(VAPID_PRIVATE_KEY + "==")
    from cryptography.hazmat.primitives.serialization import load_der_private_key
    DERIVED_VAPID_PRIVATE = load_der_private_key(der, password=None)
    return DERIVED_VAPID_PRIVATE


async def send_push_notification(username: str, title: str, body: str, room: str = None):
    db = SessionLocal()
    try:
        user = db.query(UserDB).filter(UserDB.username == username).first()
        if not user:
            return
        subs = db.query(PushSubscriptionDB).filter(PushSubscriptionDB.user_id == user.id).all()
        for sub in subs:
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub.endpoint,
                        "keys": {"p256dh": sub.p256dh, "auth": sub.auth}
                    },
                    data=json.dumps({"title": title, "body": body, "room": room}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=VAPID_CLAIMS,
                )
            except WebPushException:
                # Subscription expired or invalid
                db.delete(sub)
                db.commit()
            except Exception:
                pass
    finally:
        db.close()


@app.post("/push/subscribe")
async def push_subscribe(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    endpoint = body.get("endpoint")
    p256dh = body.get("keys", {}).get("p256dh")
    auth = body.get("keys", {}).get("auth")
    if not endpoint or not p256dh or not auth:
        return JSONResponse({"error": "Faltan datos"}, status_code=400)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u:
            return JSONResponse({"error": "No encontrado"}, status_code=404)
        existing = db.query(PushSubscriptionDB).filter(
            PushSubscriptionDB.user_id == user["id"],
            PushSubscriptionDB.endpoint == endpoint
        ).first()
        if not existing:
            sub = PushSubscriptionDB(user_id=user["id"], endpoint=endpoint, p256dh=p256dh, auth=auth)
            db.add(sub)
            db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.post("/push/unsubscribe")
async def push_unsubscribe(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    endpoint = body.get("endpoint", "")
    db = SessionLocal()
    try:
        db.query(PushSubscriptionDB).filter(
            PushSubscriptionDB.user_id == user["id"],
            PushSubscriptionDB.endpoint == endpoint
        ).delete()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/push/vapid-public-key")
async def vapid_public_key(req: Request):
    return {"public_key": VAPID_PUBLIC_KEY}


# ─── ICE / TURN config for WebRTC ─────────────────────────────────
@app.get("/ice-config")
async def ice_config(req: Request):
    return {
        "iceServers": [
            {"urls": "stun:stun.l.google.com:19302"},
            {
                "urls": "turn:192.168.0.130:3478",
                "username": "decidr",
                "credential": "decidrTurn2026"
            }
        ]
    }


@app.get("/profile/blocked/list")
async def get_blocked(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        blocks = db.query(BlockedUserDB).filter(BlockedUserDB.user_id == user["id"]).all()
        result = []
        for b in blocks:
            u = db.query(UserDB).filter(UserDB.id == b.blocked_id).first()
            if u:
                result.append({"username": u.username, "display_name": u.display_name})
        return {"blocked": result}
    finally:
        db.close()


@app.get("/privacy/settings")
async def get_privacy_settings(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        return {
            "read_receipts": u.read_receipts if u.read_receipts is not None else True,
            "online_status": u.online_status or 'all',
            "last_seen_visibility": u.last_seen_visibility or 'all',
            "allow_buzz": u.allow_buzz if u.allow_buzz is not None else True,
            "status_text": u.status_text or None,
        }
    finally:
        db.close()


@app.put("/privacy/settings")
async def update_privacy_settings(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if not u:
            return JSONResponse({"error": "Usuario no encontrado"}, status_code=404)
        if "read_receipts" in body:
            u.read_receipts = bool(body["read_receipts"])
        if "online_status" in body and body["online_status"] in ("all", "contacts", "none"):
            u.online_status = body["online_status"]
        if "last_seen_visibility" in body and body["last_seen_visibility"] in ("all", "contacts", "none"):
            u.last_seen_visibility = body["last_seen_visibility"]
        if "allow_buzz" in body:
            u.allow_buzz = bool(body["allow_buzz"])
        if "status_text" in body:
            u.status_text = (body["status_text"] or "").strip()[:60] or None
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.put("/status")
async def update_status(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    body = await req.json()
    new_status = (body.get("status_text") or "").strip()[:60]
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        if u:
            u.status_text = new_status or None
            db.commit()
        return {"ok": True, "status_text": new_status or None}
    finally:
        db.close()


@app.get("/status")
async def get_status(req: Request):
    token = req.headers.get("authorization", "").replace("Bearer ", "")
    user = get_token_user(token)
    if not user:
        return JSONResponse({"error": "No autorizado"}, status_code=401)
    db = SessionLocal()
    try:
        u = db.query(UserDB).filter(UserDB.id == user["id"]).first()
        return {"status_text": u.status_text if u else None, "allow_buzz": u.allow_buzz if u else True}
    finally:
        db.close()


PALABRAS_POOL = [
    "Cerveza", "Hielo", "Carbon", "Carne", "Ensalada", "Pan",
    "Salsa", "Vaso", "Plato", "Servilleta", "Pizza", "Helado",
    "Dip", "Galletas", "Frutas", "Facturas", "Chori", "Papas fritas",
    "Bebida", "Hamburguesa", "Lomito", "Empanadas", "Tabla de quesos",
    "Fernet", "Vino tinto", "Vino blanco", "Agua", "Gaseosa",
    "Mayonesa", "Ketchup", "Mostaza", "Chimichurri",
]


# ─── WebSocket connection manager ───────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.user_names: dict[str, str] = {}
        self.user_data: dict[str, dict] = {}

    async def connect(self, client_id: str, websocket: WebSocket, token_payload: dict):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.user_names[client_id] = token_payload.get("username", client_id)
        self.user_data[client_id] = {"token": token_payload}
        await self.deliver_pending(client_id)
        await broadcast_user_list()
        # Notify others that this user is online
        db2 = SessionLocal()
        try:
            user_db = db2.query(UserDB).filter(UserDB.username == client_id).first()
            await self.broadcast({
                "type": "user_online",
                "username": client_id,
                "read_receipts": user_db.read_receipts if user_db else True,
                "online_status": user_db.online_status if user_db else 'all',
                "last_seen_visibility": user_db.last_seen_visibility if user_db else 'all',
                "status_text": user_db.status_text if user_db else None,
                "allow_buzz": user_db.allow_buzz if user_db else True,
            })
        finally:
            db2.close()

    def disconnect(self, client_id: str, websocket: WebSocket = None):
        current = self.active_connections.get(client_id)
        if websocket and current is not websocket:
            return  # a newer connection already replaced this one
        self.active_connections.pop(client_id, None)
        self.user_names.pop(client_id, None)
        self.user_data.pop(client_id, None)

    async def broadcast(self, message_dict: dict, exclude: str = None):
        for cid, conn in list(self.active_connections.items()):
            if cid != exclude:
                try:
                    await conn.send_json(message_dict)
                except Exception:
                    pass

    async def send_to(self, client_id: str, message_dict: dict):
        conn = self.active_connections.get(client_id)
        if conn:
            try:
                await conn.send_json(message_dict)
            except Exception:
                pass

    async def deliver_pending(self, client_id: str):
        name = self.user_names.get(client_id)
        if not name:
            return
        db = SessionLocal()
        try:
            pending = db.query(ScheduledMessageDB).filter(
                ScheduledMessageDB.sent == False,
                ScheduledMessageDB.target_username == name
            ).all()
            for msg in pending:
                await self.send_to(client_id, {
                    "type": "scheduled",
                    "content": msg.content,
                    "nonce": msg.nonce,
                    "sender": msg.sender_name,
                    "target": msg.target_username,
                    "room": msg.room,
                    "scheduled_id": msg.id
                })
                msg.sent = True
            db.commit()
        finally:
            db.close()


manager = ConnectionManager()


# ─── Usuarios activos ─────────────────────────────────────────────
async def broadcast_user_list():
    db = SessionLocal()
    try:
        users = []
        for cid, name in manager.user_names.items():
            user = db.query(UserDB).filter(UserDB.username == cid).first()
            users.append({
                "id": cid,
                "name": name,
                "key": manager.user_data.get(cid, {}).get("public_key"),
                "online": True,
                "last_seen": None,
                "read_receipts": user.read_receipts if user else True,
                "online_status": user.online_status if user else 'all',
                "last_seen_visibility": user.last_seen_visibility if user else 'all',
                "status_text": user.status_text if user else None,
                "allow_buzz": user.allow_buzz if user else True,
            })
        await manager.broadcast({"type": "user_list", "users": users})
    finally:
        db.close()


# ─── Programación de mensajes ─────────────────────────────────────
async def scheduled_message_checker():
    while True:
        try:
            db = SessionLocal()
            now = datetime.datetime.utcnow()
            due = db.query(ScheduledMessageDB).filter(
                ScheduledMessageDB.sent == False,
                ScheduledMessageDB.scheduled_at <= now
            ).all()
            for msg in due:
                await manager.broadcast({
                    "type": "scheduled",
                    "content": msg.content,
                    "nonce": msg.nonce,
                    "sender": msg.sender_name,
                    "target": msg.target_username or "Todos",
                    "room": msg.room,
                    "scheduled_id": msg.id
                })
                msg.sent = True
                db.commit()
            db.close()
        except Exception:
            pass
        await asyncio.sleep(30)


async def reminder_checker():
    while True:
        try:
            db = SessionLocal()
            now = datetime.datetime.utcnow()
            due = db.query(ReminderDB).filter(
                ReminderDB.done == False,
                ReminderDB.remind_at <= now
            ).all()
            for r in due:
                user = db.query(UserDB).filter(UserDB.id == r.user_id).first()
                if user:
                    await manager.send_to(user.username, {
                        "type": "reminder_fired",
                        "content": r.content,
                        "room": r.room
                    })
                r.done = True
                db.commit()
            db.close()
        except Exception:
            pass
        await asyncio.sleep(10)


async def ephemeral_checker():
    while True:
        try:
            db = SessionLocal()
            now = datetime.datetime.utcnow()
            candidates = db.query(MessageDB).filter(
                MessageDB.ephemeral_seconds.isnot(None),
                MessageDB.ephemeral_deleted == False
            ).all()
            for msg in candidates:
                if msg.timestamp and msg.timestamp + datetime.timedelta(seconds=msg.ephemeral_seconds) <= now:
                    chat = db.query(ChatDB).filter(ChatDB.id == msg.chat_id).first()
                    room = chat.name if chat else "default_room"
                    await manager.broadcast({
                        "type": "ephemeral_delete",
                        "message_id": msg.id,
                        "room": room,
                        "msg_id": None,
                    })
                    msg.ephemeral_deleted = True
                    db.commit()
            db.close()
        except Exception:
            pass
        await asyncio.sleep(5)


@app.on_event("startup")
async def startup():
    asyncio.create_task(scheduled_message_checker())
    asyncio.create_task(reminder_checker())
    asyncio.create_task(ephemeral_checker())


# ─── Gestión de juegos ─────────────────────────────────────────────
game_states: dict[str, dict] = {}


def get_or_create_chat(db: Session, chat_name: str) -> int:
    chat = db.query(ChatDB).filter(ChatDB.name == chat_name).first()
    if not chat:
        chat = ChatDB(name=chat_name)
        db.add(chat)
        db.commit()
        db.refresh(chat)
    return chat.id


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    token = websocket.query_params.get("token", "")
    token_payload = verify_token(token)
    if not token_payload:
        await websocket.close(code=4001)
        return
    client_id = token_payload["username"]
    ip = websocket.client.host
    if limiter.is_limited(f"ws:{ip}"):
        await websocket.close(code=4002)
        return

    await manager.connect(client_id, websocket, token_payload)
    db = SessionLocal()
    # room tracking per client
    if not hasattr(manager, 'client_rooms'):
        manager.client_rooms = {}
    current_room = manager.client_rooms.get(client_id, "default_room")

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "text":
                content = data.get("content", "")
                nonce = data.get("nonce")
                room = data.get("room", current_room)
                msg_id = data.get("msg_id", "")
                reply_to = data.get("reply_to")
                manager.client_rooms[client_id] = room
                current_room = room
                # Channel check: only admins can send
                try:
                    room_id_int = int(room)
                    room_db = db.query(RoomDB).filter(RoomDB.id == room_id_int).first()
                    if room_db and room_db.is_channel:
                        user_db = db.query(UserDB).filter(UserDB.username == client_id).first()
                        if user_db:
                            is_admin = db.query(RoomMemberDB).filter(
                                RoomMemberDB.room_id == room_db.id,
                                RoomMemberDB.user_id == user_db.id,
                                RoomMemberDB.is_admin == True
                            ).first()
                            if not is_admin:
                                try:
                                    await websocket.send_json({"type":"error","message":"Solo admins pueden enviar en este canal"})
                                except Exception:
                                    pass
                                continue
                except Exception as e:
                    print(f"Channel check error: {e}")
                # Save to DB (best effort)
                db_msg_id = None
                try:
                    chat_db_id = get_or_create_chat(db, room)
                    user = db.query(UserDB).filter(UserDB.username == client_id).first()
                    db_msg = MessageDB(
                        content=content,
                        nonce=nonce,
                        is_game_result=False,
                        sender_id=user.id if user else 1,
                        chat_id=chat_db_id,
                        reply_to=reply_to,
                        ephemeral_seconds=data.get("ephemeral")
                    )
                    db.add(db_msg)
                    db.commit()
                    db_msg_id = db_msg.id
                except Exception as e:
                    print(f"DB save error: {e}")
                    # Broadcast to all (happens regardless of DB success)
                    try:
                        sender_name = manager.user_names.get(client_id, client_id)
                        # Check who blocked the sender
                        blocked_by = set()
                        try:
                            sender_db = db.query(UserDB).filter(UserDB.username == client_id).first()
                            if sender_db:
                                blocks = db.query(BlockedUserDB).filter(BlockedUserDB.blocked_id == sender_db.id).all()
                                blocked_by = {b.user_id for b in blocks}
                        except Exception:
                            pass
                        chat_msg = {
                            "type": "chat",
                            "sender": sender_name,
                            "content": content,
                            "nonce": nonce,
                            "client_id": client_id,
                            "room": room,
                            "msg_id": msg_id,
                            "message_id": db_msg_id,
                            "reply_to": reply_to,
                            "ephemeral": data.get("ephemeral"),
                            "status": "sent"
                        }
                        for cid, conn in manager.active_connections.items():
                            try:
                                if cid != client_id:
                                    cid_user = db.query(UserDB).filter(UserDB.username == cid).first()
                                    if cid_user and cid_user.id in blocked_by:
                                        continue
                                await conn.send_json(chat_msg)
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"Broadcast error: {e}")
                # Send push notifications to room members not viewing this room
                try:
                    room_members = db.query(RoomMemberDB).filter(
                        RoomMemberDB.room_id == chat_db_id
                    ).all()
                    room_name = room
                    for member in room_members:
                        member_user = db.query(UserDB).filter(UserDB.id == member.user_id).first()
                        if not member_user or member_user.username == client_id:
                            continue
                        c_room = manager.client_rooms.get(member_user.username)
                        if c_room == room:
                            continue  # they're viewing this room, skip push
                        sender_display = sender_name
                        asyncio.ensure_future(
                            send_push_notification(
                                member_user.username,
                                f"💬 {room_name}",
                                f"{sender_display}: Nuevo mensaje",
                                room
                            )
                        )
                except Exception as e:
                    print(f"Push notification error: {e}")

            elif msg_type == "payment":
                room = data.get("room", current_room)
                manager.client_rooms[client_id] = room
                current_room = room
                sender_name = manager.user_names.get(client_id, client_id)
                chat_msg = {
                    "type": "payment",
                    "sender": sender_name,
                    "client_id": client_id,
                    "room": room,
                    "amount": data.get("amount"),
                    "concept": data.get("concept"),
                    "init_point": data.get("init_point"),
                    "pref_id": data.get("pref_id")
                }
                for cid, conn in manager.active_connections.items():
                    if cid == client_id:
                        continue
                    try:
                        await conn.send_json(chat_msg)
                    except Exception:
                        pass

            elif msg_type == "edit_message":
                msg_id = data.get("message_id")
                content = data.get("content", "")
                nonce = data.get("nonce")
                room = data.get("room", current_room)
                sender_name = manager.user_names.get(client_id, client_id)
                for cid, conn in manager.active_connections.items():
                    if cid == client_id:
                        continue
                    try:
                        await conn.send_json({
                            "type": "edit_message",
                            "message_id": msg_id,
                            "content": content,
                            "nonce": nonce,
                            "sender": sender_name,
                            "room": room
                        })
                    except Exception:
                        pass

            elif msg_type == "delete_message":
                msg_id = data.get("message_id")
                room = data.get("room", current_room)
                sender_name = manager.user_names.get(client_id, client_id)
                for cid, conn in manager.active_connections.items():
                    if cid == client_id:
                        continue
                    try:
                        await conn.send_json({
                            "type": "delete_message",
                            "message_id": msg_id,
                            "sender": sender_name,
                            "room": room
                        })
                    except Exception:
                        pass

            elif msg_type == "typing":
                room = data.get("room", current_room)
                sender_name = manager.user_names.get(client_id, client_id)
                for cid, conn in manager.active_connections.items():
                    if cid == client_id:
                        continue
                    try:
                        await conn.send_json({
                            "type": "typing",
                            "sender": sender_name,
                            "client_id": client_id,
                            "room": room
                        })
                    except Exception:
                        pass

            elif msg_type == "stop_typing":
                room = data.get("room", current_room)
                sender_name = manager.user_names.get(client_id, client_id)
                for cid, conn in manager.active_connections.items():
                    if cid == client_id:
                        continue
                    try:
                        await conn.send_json({
                            "type": "stop_typing",
                            "sender": sender_name,
                            "client_id": client_id,
                            "room": room
                        })
                    except Exception:
                        pass

            elif msg_type == "delivered":
                target = data.get("target")
                msg_id = data.get("message_id")
                if target and msg_id:
                    await manager.send_to(target, {
                        "type": "status_update",
                        "message_id": msg_id,
                        "status": "delivered",
                        "from": client_id
                    })

            elif msg_type == "read":
                target = data.get("target")
                msg_id = data.get("message_id")
                if target and msg_id:
                    # Update DB status
                    try:
                        db.query(MessageDB).filter(MessageDB.id == msg_id).update({
                            "status": "read",
                            "read_at": datetime.datetime.utcnow()
                        })
                        db.commit()
                    except Exception:
                        pass
                    await manager.send_to(target, {
                        "type": "status_update",
                        "message_id": msg_id,
                        "status": "read",
                        "from": client_id
                    })

            elif msg_type == "get_user_status":
                target = data.get("target", "")
                if target:
                    user = db.query(UserDB).filter(UserDB.username == target).first()
                    if user:
                        online = target in manager.active_connections
                        can_see_online = user.online_status in ('all', 'contacts')
                        can_see_last_seen = user.last_seen_visibility in ('all', 'contacts')
                        reply = {
                            "type": "user_status",
                            "username": target,
                        }
                        if can_see_online:
                            reply["online"] = online
                        if can_see_last_seen and user.last_seen:
                            reply["last_seen"] = user.last_seen.isoformat()
                        if user.status_text:
                            reply["status_text"] = user.status_text
                        reply["allow_buzz"] = user.allow_buzz if user.allow_buzz is not None else True
                        await manager.send_to(client_id, reply)

            elif msg_type == "set_status":
                new_status = (data.get("status_text") or "").strip()[:60]
                try:
                    db.query(UserDB).filter(UserDB.username == client_id).update({"status_text": new_status or None})
                    db.commit()
                except Exception:
                    pass
                await manager.send_to(client_id, {"type": "status_updated", "status_text": new_status or None})
                await broadcast_user_list()

            elif msg_type == "buzz":
                target = data.get("target")
                sender_name = manager.user_names.get(client_id, client_id)
                if target:
                    target_user = db.query(UserDB).filter(UserDB.username == target).first()
                    allow = target_user.allow_buzz if target_user else True
                    if target in manager.active_connections and allow:
                        await manager.send_to(target, {
                            "type": "buzz",
                            "from": client_id,
                            "from_name": sender_name
                        })
                        await manager.send_to(client_id, {
                            "type": "system",
                            "content": f"📳 Zumbido enviado a {target}"
                        })
                    else:
                        await manager.send_to(client_id, {
                            "type": "system",
                            "content": "📳 No se pudo enviar el zumbido"
                        })

            elif msg_type == "set_allow_buzz":
                allow = data.get("allow_buzz", True)
                try:
                    db.query(UserDB).filter(UserDB.username == client_id).update({"allow_buzz": bool(allow)})
                    db.commit()
                except Exception:
                    pass

            elif msg_type == "reaction":
                msg_id = data.get("message_id")
                reaction = data.get("reaction", "").strip()
                room = data.get("room", current_room)
                sender_name = manager.user_names.get(client_id, client_id)
                if msg_id and reaction:
                    user = db.query(UserDB).filter(UserDB.username == client_id).first()
                    uid = user.id if user else None
                    # Toggle: if same user+msg+reaction exists, remove it
                    existing = db.query(ReactionDB).filter(
                        ReactionDB.message_id == msg_id,
                        ReactionDB.user_id == uid,
                        ReactionDB.reaction == reaction
                    ).first()
                    if existing:
                        db.delete(existing)
                        db.commit()
                        action = "removed"
                    else:
                        r = ReactionDB(message_id=msg_id, user_id=uid, reaction=reaction)
                        db.add(r)
                        db.commit()
                        action = "added"
                    # Get all reactions for this message
                    all_reactions = db.query(ReactionDB).filter(ReactionDB.message_id == msg_id).all()
                    reaction_list = {}
                    for rr in all_reactions:
                        reaction_list.setdefault(rr.reaction, []).append(rr.user_id)
                    await manager.broadcast({
                        "type": "reaction_update",
                        "message_id": msg_id,
                        "room": room,
                        "reactions": reaction_list,
                        "by_user": uid,
                        "action": action,
                        "reaction": reaction,
                    })

            elif msg_type == "create_poll":
                question = data.get("question", "").strip()
                options = data.get("options", [])
                multiple = data.get("multiple", False)
                room = data.get("room", current_room)
                sender_name = manager.user_names.get(client_id, client_id)
                if question and len(options) >= 2:
                    user = db.query(UserDB).filter(UserDB.username == client_id).first()
                    poll = PollDB(room=room, question=question, creator_id=user.id if user else None, multiple=multiple)
                    db.add(poll)
                    db.commit()
                    db.refresh(poll)
                    for opt in options[:10]:
                        o = PollOptionDB(poll_id=poll.id, text=opt.strip()[:100])
                        db.add(o)
                    db.commit()
                    # Build response
                    opts = db.query(PollOptionDB).filter(PollOptionDB.poll_id == poll.id).all()
                    opt_list = [{"id": o.id, "text": o.text, "votes": 0, "voted": False} for o in opts]
                    await manager.broadcast({
                        "type": "poll",
                        "poll_id": poll.id,
                        "question": question,
                        "options": opt_list,
                        "creator": sender_name,
                        "room": room,
                        "multiple": multiple,
                    })
                    # Also save as chat message for history
                    try:
                        chat_db_id = get_or_create_chat(db, room)
                        db_msg = MessageDB(content=f"📊 Encuesta: {question}", is_game_result=True, sender_id=1, chat_id=chat_db_id)
                        db.add(db_msg)
                        db.commit()
                    except Exception:
                        pass

            elif msg_type == "vote_poll":
                poll_id = data.get("poll_id")
                option_id = data.get("option_id")
                room = data.get("room", current_room)
                if poll_id and option_id:
                    user = db.query(UserDB).filter(UserDB.username == client_id).first()
                    uid = user.id if user else None
                    poll = db.query(PollDB).filter(PollDB.id == poll_id).first()
                    if not poll:
                        continue
                    if poll.multiple:
                        # Toggle vote for this option
                        existing = db.query(PollVoteDB).filter(
                            PollVoteDB.poll_id == poll_id,
                            PollVoteDB.option_id == option_id,
                            PollVoteDB.user_id == uid
                        ).first()
                        if existing:
                            db.delete(existing)
                        else:
                            db.add(PollVoteDB(poll_id=poll_id, option_id=option_id, user_id=uid))
                    else:
                        # Remove previous vote, add new one
                        db.query(PollVoteDB).filter(
                            PollVoteDB.poll_id == poll_id,
                            PollVoteDB.user_id == uid
                        ).delete()
                        db.add(PollVoteDB(poll_id=poll_id, option_id=option_id, user_id=uid))
                    db.commit()
                # Broadcast updated poll
                opts = db.query(PollOptionDB).filter(PollOptionDB.poll_id == poll_id).all()
                opt_list = []
                for o in opts:
                    vote_count = db.query(PollVoteDB).filter(PollVoteDB.option_id == o.id).count()
                    voted = db.query(PollVoteDB).filter(
                        PollVoteDB.option_id == o.id,
                        PollVoteDB.user_id == (user.id if user else None)
                    ).first() is not None
                    opt_list.append({"id": o.id, "text": o.text, "votes": vote_count, "voted": voted})
                await manager.broadcast({
                    "type": "poll_update",
                    "poll_id": poll_id,
                    "options": opt_list,
                    "room": room,
                })

            elif msg_type == "sticker":
                room = data.get("room", current_room)
                sticker_id = data.get("sticker_id", "")
                pack = data.get("pack", "")
                await manager.broadcast({
                    "type": "sticker",
                    "sticker_id": sticker_id,
                    "pack": pack,
                    "sender": client_id,
                    "room": room,
                })

            elif msg_type == "create_reminder":
                content = data.get("content", "")
                minutes = data.get("minutes", 10)
                room = data.get("room", current_room)
                user = db.query(UserDB).filter(UserDB.username == client_id).first()
                if user and content:
                    remind_at = datetime.datetime.utcnow() + datetime.timedelta(minutes=minutes)
                    rem = ReminderDB(user_id=user.id, room=room, content=content, remind_at=remind_at)
                    db.add(rem)
                    db.commit()
                    await websocket.send_json({
                        "type": "reminder_set",
                        "content": content,
                        "minutes": minutes,
                        "remind_at": remind_at.isoformat()
                    })

            elif msg_type == "set_room":
                room = data.get("room", "default_room")
                manager.client_rooms[client_id] = room
                current_room = room
                await manager.send_to(client_id, {
                    "type": "system",
                    "content": f"🔄 Cambiaste a la sala {room}"
                })

            elif msg_type == "set_username":
                name = data.get("name", "").strip()[:20]
                if name:
                    manager.user_names[client_id] = name
                    await manager.send_to(client_id, {
                        "type": "system",
                        "content": f"✅ Ahora sos {name}"
                    })
                    await broadcast_user_list()

            elif msg_type == "get_users":
                ulist = []
                for cid, name in manager.user_names.items():
                    user = db.query(UserDB).filter(UserDB.username == cid).first()
                    ulist.append({
                        "id": cid,
                        "name": name,
                        "key": manager.user_data.get(cid, {}).get("public_key"),
                        "online": True,
                        "last_seen": None,
                        "read_receipts": user.read_receipts if user else True,
                        "online_status": user.online_status if user else 'all',
                        "last_seen_visibility": user.last_seen_visibility if user else 'all',
                    })
                await manager.send_to(client_id, {
                    "type": "user_list",
                    "users": ulist
                })

            elif msg_type == "public_key":
                key = data.get("key")
                if key:
                    if client_id in manager.user_data:
                        manager.user_data[client_id]["public_key"] = key
                    db.query(UserDB).filter(UserDB.username == client_id).update({"public_key": key})
                    db.commit()
                    await broadcast_user_list()

            elif msg_type == "room_key_share":
                target = data.get("target")
                room = data.get("room", "default_room")
                encrypted_key = data.get("encrypted_key")
                nonce_key = data.get("nonce")
                sender_key = data.get("sender_key")
                if target and encrypted_key and nonce_key and sender_key:
                    await manager.send_to(target, {
                        "type": "room_key_share",
                        "from": client_id,
                        "room": room,
                        "encrypted_key": encrypted_key,
                        "nonce": nonce_key,
                        "sender_key": sender_key
                    })

            elif msg_type == "schedule":
                content = data.get("content", "").strip()
                target = data.get("target", "").strip() or None
                dt_str = data.get("datetime", "")
                nonce = data.get("nonce")
                room = data.get("room", current_room)
                if not content or not dt_str:
                    continue
                try:
                    scheduled_at = datetime.datetime.fromisoformat(dt_str)
                except Exception:
                    continue
                sender_name = manager.user_names.get(client_id, client_id)
                db_msg = ScheduledMessageDB(
                    content=content,
                    nonce=nonce,
                    sender_client_id=client_id,
                    sender_name=sender_name,
                    target_username=target,
                    room=room,
                    scheduled_at=scheduled_at
                )
                db.add(db_msg)
                db.commit()
                db.refresh(db_msg)
                await manager.send_to(client_id, {
                    "type": "system",
                    "content": f"📅 Programado para {target or 'todos'} el {scheduled_at.strftime('%d/%m %H:%S')}"
                })

            elif msg_type == "list_scheduled":
                pending = db.query(ScheduledMessageDB).filter(
                    ScheduledMessageDB.sender_client_id == client_id,
                    ScheduledMessageDB.sent == False
                ).order_by(ScheduledMessageDB.scheduled_at).all()
                items = [{
                    "id": m.id,
                    "content": m.content,
                    "nonce": m.nonce,
                    "target": m.target_username or "Todos",
                    "scheduled_at": m.scheduled_at.isoformat()
                } for m in pending]
                await manager.send_to(client_id, {
                    "type": "scheduled_list",
                    "items": items
                })

            elif msg_type == "cancel_scheduled":
                msg_id = data.get("id")
                msg = db.query(ScheduledMessageDB).filter(
                    ScheduledMessageDB.id == msg_id,
                    ScheduledMessageDB.sender_client_id == client_id,
                    ScheduledMessageDB.sent == False
                ).first()
                if msg:
                    db.delete(msg)
                    db.commit()
                    await manager.send_to(client_id, {
                        "type": "system",
                        "content": "📅 Mensaje programado cancelado"
                    })

            elif msg_type in ("call_request", "call_accept", "call_reject", "call_end", "offer", "answer", "ice_candidate"):
                target = data.get("target")
                sender_name = manager.user_names.get(client_id, client_id)

                if msg_type == "call_request":
                    if target and target in manager.active_connections:
                        await manager.send_to(target, {
                            "type": "incoming_call",
                            "from": client_id,
                            "from_name": sender_name,
                            "has_video": data.get("has_video", False)
                        })
                        await manager.send_to(client_id, {
                            "type": "call_ringing"
                        })
                    else:
                        await manager.send_to(client_id, {
                            "type": "call_error",
                            "content": "Usuario no disponible"
                        })

                elif msg_type == "call_accept":
                    if target and target in manager.active_connections:
                        await manager.send_to(target, {
                            "type": "call_accepted",
                            "from": client_id
                        })

                elif msg_type == "call_reject":
                    if target and target in manager.active_connections:
                        await manager.send_to(target, {
                            "type": "call_rejected",
                            "from": client_id
                        })

                elif msg_type == "call_end":
                    if target and target in manager.active_connections:
                        await manager.send_to(target, {
                            "type": "call_ended",
                            "from": client_id
                        })

                elif msg_type == "offer":
                    if target and target in manager.active_connections:
                        await manager.send_to(target, {
                            "type": "offer",
                            "sdp": data.get("sdp"),
                            "from": client_id
                        })

                elif msg_type == "answer":
                    if target and target in manager.active_connections:
                        await manager.send_to(target, {
                            "type": "answer",
                            "sdp": data.get("sdp"),
                            "from": client_id
                        })

                elif msg_type == "ice_candidate":
                    if target and target in manager.active_connections:
                        await manager.send_to(target, {
                            "type": "ice_candidate",
                            "candidate": data.get("candidate"),
                            "from": client_id
                        })

            elif msg_type == "game_action":
                game_type = data.get("game")
                action = data.get("action", "play")
                sender_name = manager.user_names.get(client_id, client_id)
                room = current_room

                response_contents = []

                if game_type == "dados":
                    val = random.randint(1, 6)
                    response_contents.append(f"🎲 {sender_name} tiró el dado: ¡{val}!")

                elif game_type == "palito":
                    val = random.randint(1, 100)
                    if room not in game_states or game_states[room].get("type") != "palito":
                        game_states[room] = {"type": "palito", "entries": []}
                    game_states[room]["entries"].append({"name": sender_name, "val": val})
                    response_contents.append(f"🪵 {sender_name} sacó un palito...")

                elif game_type == "palito_result":
                    gs = game_states.get(room)
                    if gs and gs.get("type") == "palito" and gs["entries"]:
                        entries = gs["entries"]
                        best = max(entries, key=lambda e: e["val"])
                        response_contents.append(f"🏆 ¡{best['name']} gana con palito {best['val']}!")
                        ranking = sorted(entries, key=lambda e: e["val"], reverse=True)
                        lines = [f"   {i+1}. {e['name']}: {e['val']}" for i, e in enumerate(ranking)]
                        response_contents.append("📊 Ranking:\n" + "\n".join(lines))
                        del game_states[room]

                elif game_type == "ppt":
                    options = ["piedra", "papel", "tijera"]
                    choice = data.get("option", random.choice(options))
                    if choice not in options:
                        choice = random.choice(options)
                    if room not in game_states or game_states[room].get("type") != "ppt":
                        game_states[room] = {"type": "ppt", "plays": {}}
                    game_states[room]["plays"][client_id] = choice

                    current_plays = game_states[room]["plays"]
                    response_contents.append(f"✊✋✌️ {sender_name} ya eligió ({len(current_plays)}/2 jugadores)")

                    if len(current_plays) >= 2:
                        ids = list(current_plays.keys())
                        p1_id, p2_id = ids[0], ids[1]
                        p1_name = manager.user_names.get(p1_id, p1_id)
                        p2_name = manager.user_names.get(p2_id, p2_id)
                        c1, c2 = current_plays[p1_id], current_plays[p2_id]

                        beats = {"piedra": "tijera", "tijera": "papel", "papel": "piedra"}
                        if c1 == c2:
                            result = f"🤝 Empate! {p1_name} y {p2_name} sacaron {c1}"
                        elif beats[c1] == c2:
                            result = f"🏆 ¡{p1_name} gana! {c1} vence a {c2}"
                        else:
                            result = f"🏆 ¡{p2_name} gana! {c2} vence a {c1}"
                        response_contents.append(result)
                        del game_states[room]

                elif game_type == "papelitos":
                    if action == "start":
                        game_states[room] = {"type": "papelitos", "pool": []}
                        response_contents.append("📝 ¡Pozo de papelitos abierto! Manden sus opciones.")
                    elif action == "add":
                        option = data.get("option")
                        if room in game_states:
                            game_states[room]["pool"].append({"val": option, "by": sender_name})
                            count = len(game_states[room]["pool"])
                            response_contents.append(f"📝 {sender_name} agregó un papelito. Total: {count}")
                    elif action == "draw":
                        gs = game_states.get(room)
                        if gs and gs["pool"]:
                            pool = gs["pool"]
                            chosen = pool.pop(random.randrange(len(pool)))
                            response_contents.append(f"🎊 ¡Salió: '{chosen['val']}' (de {chosen['by']})!")
                            if not pool:
                                response_contents.append("📭 Pozo vacío. Manden más o inicien de nuevo.")
                                del game_states[room]

                elif game_type == "palabras":
                    word = random.choice(PALABRAS_POOL)
                    response_contents.append(f"🔤 {sender_name} sacó: **{word}**")
                    if action == "reassign":
                        if room not in game_states or game_states[room].get("type") != "palabras":
                            game_states[room] = {"type": "palabras", "pool": PALABRAS_POOL.copy(), "assigned": {}}
                        gs = game_states[room]
                        target = data.get("target", sender_name)
                        if gs["pool"]:
                            w = gs["pool"].pop(random.randrange(len(gs["pool"])))
                            gs["assigned"][target] = w
                            response_contents.append(f"🔤 A {target} le tocó: **{w}**")

                for resp in response_contents:
                    await manager.broadcast({
                        "type": "game_result",
                        "content": resp,
                        "room": room
                    })
                    chat_db_id = get_or_create_chat(db, room)
                    db_msg = MessageDB(content=resp, is_game_result=True, sender_id=1, chat_id=chat_db_id)
                    db.add(db_msg)
                    db.commit()

    except WebSocketDisconnect:
        manager.disconnect(client_id, websocket)
        now_str = datetime.datetime.utcnow().isoformat()
        try:
            db2 = SessionLocal()
            db2.query(UserDB).filter(UserDB.username == client_id).update({"last_seen": datetime.datetime.utcnow()})
            db2.commit()
            db2.close()
        except Exception:
            pass
        await broadcast_user_list()
        await manager.broadcast({
            "type": "user_offline",
            "username": client_id,
            "last_seen": now_str,
            "status_text": None,
            "allow_buzz": True,
        })
    finally:
        db.close()
