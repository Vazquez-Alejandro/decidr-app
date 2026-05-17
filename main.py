import os
import random
import json
import asyncio
import datetime
import time
import secrets
from pathlib import Path
from collections import defaultdict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from database import SessionLocal, MessageDB, UserDB, ChatDB, RoomDB, RoomMemberDB, ScheduledMessageDB, engine, Base
import bcrypt
import jwt
from pydantic import BaseModel

Base.metadata.create_all(bind=engine)

# ─── JWT ────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(64))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY = 24 * 3600


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
        user = UserDB(username=req.username, password_hash=hashed.decode())
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_token(user.id, user.username)
        return {"token": token, "username": user.username, "user_id": user.id}
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
    db = SessionLocal()
    try:
        room = RoomDB(name=name, creator_id=user["id"])
        db.add(room)
        db.commit()
        db.refresh(room)
        member = RoomMemberDB(room_id=room.id, user_id=user["id"])
        db.add(member)
        db.commit()
        return {"id": room.id, "name": room.name, "created_at": room.created_at.isoformat()}
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
            result.append({
                "id": r.id,
                "name": r.name,
                "member_count": member_count,
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
        await self.broadcast({
            "type": "system",
            "content": f"🟢 {client_id} se conectó"
        })

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        self.user_names.pop(client_id, None)
        self.user_data.pop(client_id, None)

    async def broadcast(self, message_dict: dict, exclude: str = None):
        for cid, conn in self.active_connections.items():
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
        for cid in manager.user_names:
            name = manager.user_names[cid]
            user = db.query(UserDB).filter(UserDB.username == name).first()
            users.append({
                "id": cid,
                "name": name,
                "key": user.public_key if user else None
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
                    "scheduled_id": msg.id
                })
                msg.sent = True
                db.commit()
            db.close()
        except Exception:
            pass
        await asyncio.sleep(30)


@app.on_event("startup")
async def startup():
    asyncio.create_task(scheduled_message_checker())


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
                manager.client_rooms[client_id] = room
                current_room = room
                # Get or create ChatDB entry for this room name
                chat_db_id = get_or_create_chat(db, room)
                user = db.query(UserDB).filter(UserDB.username == client_id).first()
                db_msg = MessageDB(
                    content=content,
                    nonce=nonce,
                    is_game_result=False,
                    sender_id=user.id if user else 1,
                    chat_id=chat_db_id
                )
                db.add(db_msg)
                db.commit()

                await manager.broadcast({
                    "type": "chat",
                    "sender": manager.user_names.get(client_id, client_id),
                    "content": content,
                    "nonce": nonce,
                    "client_id": client_id,
                    "room": room
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
                await manager.send_to(client_id, {
                    "type": "user_list",
                    "users": [{
                        "id": cid,
                        "name": name,
                        "key": manager.user_data.get(cid, {}).get("public_key")
                    } for cid, name in manager.user_names.items()]
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
                    room=chat_id,
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
        manager.disconnect(client_id)
        await broadcast_user_list()
        await manager.broadcast({
            "type": "system",
            "content": f"🔴 {client_id} se desconectó"
        })
    finally:
        db.close()
