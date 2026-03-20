import random
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import SessionLocal, MessageDB, engine, Base

# Inicializar las tablas de la base de datos
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Memoria para juegos activos: { chat_id: { "type": "papelitos", "pool": [] } }
game_states = {}

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message_dict: dict):
        for connection in self.active_connections:
            await connection.send_json(message_dict)

manager = ConnectionManager()

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket)
    db = SessionLocal()
    chat_id = "default_room" # Por ahora simplificado a una sola sala
    
    try:
        while True:
            # Recibimos el JSON del frontend
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "text":
                content = data.get("content")
                # Guardar mensaje de texto en DB
                db_msg = MessageDB(content=content, is_game_result=False, sender_id=1, chat_id=1)
                db.add(db_msg)
                db.commit()
                
                await manager.broadcast({
                    "type": "chat", 
                    "sender": f"User {client_id}", 
                    "content": content,
                    "client_id": client_id
                })
            
            elif msg_type == "game_action":
                game_type = data.get("game")
                action = data.get("action")
                
                response_content = ""
                
                if game_type == "papelitos":
                    if action == "start":
                        game_states[chat_id] = {"type": "papelitos", "pool": []}
                        response_content = "📝 ¡Pozo de papelitos abierto! Empiecen a mandar opciones."
                        await manager.broadcast({"type": "system", "content": response_content})
                    
                    elif action == "add":
                        option = data.get("option")
                        if chat_id in game_states:
                            game_states[chat_id]["pool"].append({"val": option, "by": client_id})
                            count = len(game_states[chat_id]["pool"])
                            await manager.broadcast({"type": "system", "content": f"✅ Nuevo papelito agregado. Total: {count}"})
                    
                    elif action == "draw":
                        if chat_id in game_states and game_states[chat_id]["pool"]:
                            pool = game_states[chat_id]["pool"]
                            chosen = pool.pop(random.randrange(len(pool)))
                            response_content = f"🎊 ¡Salió el papelito de {chosen['by']}: '{chosen['val']}'!"
                            await manager.broadcast({
                                "type": "game_result", 
                                "content": response_content
                            })
                
                elif game_type == "dados":
                    val = random.randint(1, 6)
                    response_content = f"🎲 Dado: ¡Salió un {val}!"
                    await manager.broadcast({"type": "game_result", "content": response_content})

                # Guardar resultados de juego en DB si hubo respuesta
                if response_content:
                    db_msg = MessageDB(content=response_content, is_game_result=True, sender_id=1, chat_id=1)
                    db.add(db_msg)
                    db.commit()

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        db.close()