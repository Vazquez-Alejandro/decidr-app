import os
import random
import json
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import SessionLocal, MessageDB, UserDB, ChatDB, engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI()

INDEX_HTML = Path(__file__).parent / "index.html"


@app.get("/")
async def get_index():
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))

PALABRAS_POOL = [
    "Cerveza", "Hielo", "Carbon", "Carne", "Ensalada", "Pan",
    "Salsa", "Vaso", "Plato", "Servilleta", "Pizza", "Helado",
    "Dip", "Galletas", "Frutas", "Facturas", "Chori", "Papas fritas",
    "Bebida", "Hamburguesa", "Lomito", "Empanadas", "Tabla de quesos",
    "Fernet", "Vino tinto", "Vino blanco", "Agua", "Gaseosa",
    "Mayonesa", "Ketchup", "Mostaza", "Chimichurri",
]

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.user_names: dict[str, str] = {}

    async def connect(self, client_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        db = SessionLocal()
        user = db.query(UserDB).filter(UserDB.username == client_id).first()
        if not user:
            user = UserDB(username=client_id)
            db.add(user)
            db.commit()
        db.close()
        self.user_names[client_id] = client_id
        await self.broadcast({
            "type": "system",
            "content": f"🟢 {client_id} se conectó"
        })

    def disconnect(self, client_id: str):
        self.active_connections.pop(client_id, None)
        self.user_names.pop(client_id, None)

    async def broadcast(self, message_dict: dict, exclude: str = None):
        for cid, conn in self.active_connections.items():
            if cid != exclude:
                await conn.send_json(message_dict)

    async def send_to(self, client_id: str, message_dict: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message_dict)

manager = ConnectionManager()


# ─── Gestión de juegos ─────────────────────────────────────────────
# chat_id -> { game_type, state }
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
    await manager.connect(client_id, websocket)
    db = SessionLocal()
    chat_id = "default_room"

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "text":
                content = data.get("content")
                chat_db_id = get_or_create_chat(db, chat_id)
                db_msg = MessageDB(content=content, is_game_result=False, sender_id=1, chat_id=chat_db_id)
                db.add(db_msg)
                db.commit()

                await manager.broadcast({
                    "type": "chat",
                    "sender": manager.user_names.get(client_id, client_id),
                    "content": content,
                    "client_id": client_id
                })

            elif msg_type == "game_action":
                game_type = data.get("game")
                action = data.get("action", "play")
                sender_name = manager.user_names.get(client_id, client_id)

                response_contents = []

                # ── DADOS ──
                if game_type == "dados":
                    val = random.randint(1, 6)
                    response_contents.append(f"🎲 {sender_name} tiró el dado: ¡{val}!")

                # ── PALITO MÁS LARGO ──
                elif game_type == "palito":
                    val = random.randint(1, 100)
                    if chat_id not in game_states or game_states[chat_id].get("type") != "palito":
                        game_states[chat_id] = {"type": "palito", "entries": []}
                    game_states[chat_id]["entries"].append({"name": sender_name, "val": val})
                    response_contents.append(f"🪵 {sender_name} sacó un palito...")

                elif game_type == "palito_result":
                    gs = game_states.get(chat_id)
                    if gs and gs.get("type") == "palito" and gs["entries"]:
                        entries = gs["entries"]
                        best = max(entries, key=lambda e: e["val"])
                        response_contents.append(f"🏆 ¡{best['name']} gana con palito {best['val']}!")
                        ranking = sorted(entries, key=lambda e: e["val"], reverse=True)
                        lines = [f"   {i+1}. {e['name']}: {e['val']}" for i, e in enumerate(ranking)]
                        response_contents.append("📊 Ranking:\n" + "\n".join(lines))
                        del game_states[chat_id]

                # ── PIEDRA, PAPEL O TIJERA ──
                elif game_type == "ppt":
                    options = ["piedra", "papel", "tijera"]
                    choice = data.get("option", random.choice(options))
                    if choice not in options:
                        choice = random.choice(options)
                    if chat_id not in game_states or game_states[chat_id].get("type") != "ppt":
                        game_states[chat_id] = {"type": "ppt", "plays": {}}
                    game_states[chat_id]["plays"][client_id] = choice

                    current_plays = game_states[chat_id]["plays"]
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
                        del game_states[chat_id]

                # ── PAPELITOS ──
                elif game_type == "papelitos":
                    if action == "start":
                        game_states[chat_id] = {"type": "papelitos", "pool": []}
                        response_contents.append("📝 ¡Pozo de papelitos abierto! Manden sus opciones.")
                    elif action == "add":
                        option = data.get("option")
                        if chat_id in game_states:
                            game_states[chat_id]["pool"].append({"val": option, "by": sender_name})
                            count = len(game_states[chat_id]["pool"])
                            response_contents.append(f"📝 {sender_name} agregó un papelito. Total: {count}")
                    elif action == "draw":
                        gs = game_states.get(chat_id)
                        if gs and gs["pool"]:
                            pool = gs["pool"]
                            chosen = pool.pop(random.randrange(len(pool)))
                            response_contents.append(f"🎊 ¡Salió: '{chosen['val']}' (de {chosen['by']})!")
                            if not pool:
                                response_contents.append("📭 Pozo vacío. Manden más o inicien de nuevo.")
                                del game_states[chat_id]

                # ── PALABRAS (sacar una palabra al azar) ──
                elif game_type == "palabras":
                    word = random.choice(PALABRAS_POOL)
                    response_contents.append(f"🔤 {sender_name} sacó: **{word}**")
                    if action == "reassign":
                        if chat_id not in game_states or game_states[chat_id].get("type") != "palabras":
                            game_states[chat_id] = {"type": "palabras", "pool": PALABRAS_POOL.copy(), "assigned": {}}
                        gs = game_states[chat_id]
                        target = data.get("target", sender_name)
                        if gs["pool"]:
                            w = gs["pool"].pop(random.randrange(len(gs["pool"])))
                            gs["assigned"][target] = w
                            response_contents.append(f"🔤 A {target} le tocó: **{w}**")

                for resp in response_contents:
                    await manager.broadcast({
                        "type": "game_result",
                        "content": resp
                    })
                    chat_db_id = get_or_create_chat(db, chat_id)
                    db_msg = MessageDB(content=resp, is_game_result=True, sender_id=1, chat_id=chat_db_id)
                    db.add(db_msg)
                    db.commit()

    except WebSocketDisconnect:
        manager.disconnect(client_id)
        await manager.broadcast({
            "type": "system",
            "content": f"🔴 {client_id} se desconectó"
        })
    finally:
        db.close()
