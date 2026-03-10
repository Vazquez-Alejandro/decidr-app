import random
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from database import SessionLocal, MessageDB, GameSession, engine, Base

# Inicializar las tablas de la base de datos
Base.metadata.create_all(bind=engine)

app = FastAPI()

# Diccionario para mantener el estado de los juegos en memoria (opcional, para velocidad)
active_games = {}

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
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            content = data.get("content")
            
            response_content = ""
            is_game = False

            if msg_type == "text":
                response_content = content
            
            elif msg_type == "game_cmd":
                is_game = True
                game_name = data.get("game")
                
                # Lógica simple: Azar inmediato
                if game_name == "dados":
                    response_content = f"🎲 Dados: ¡Salió un {random.randint(1, 6)}!"
                
                elif game_name == "moneda":
                    response_content = f"🪙 Moneda: ¡Cayó {random.choice(['Cara', 'Seca'])}!"
                
                # Lógica compleja: Juego de Papelitos (Estado persistente)
                elif game_name == "papelitos":
                    options = data.get("options", [])
                    if options:
                        # Guardamos el "pozo" de papelitos en memoria para este chat
                        chat_id = "default" # En el futuro usar chat_id real
                        active_games[chat_id] = options
                        response_content = f"📝 Papelitos: ¡Se cargaron {len(options)} papeles al pozo!"
                    else:
                        # Sacar un papelito del pozo
                        chat_id = "default"
                        if chat_id in active_games and active_games[chat_id]:
                            elegido = active_games[chat_id].pop(random.randrange(len(active_games[chat_id])))
                            restantes = len(active_games[chat_id])
                            response_content = f"📝 Papelitos: Alguien sacó '{elegido}'. Quedan {restantes}."
                        else:
                            response_content = "📝 Papelitos: El pozo está vacío. ¡Cargá más!"

            # Persistencia
            db_msg = MessageDB(
                content=response_content, 
                is_game_result=is_game, 
                sender_id=1, 
                chat_id=1
            )
            db.add(db_msg)
            db.commit()

            await manager.broadcast({
                "sender": f"Usuario {client_id}" if msg_type == "text" else "Decidr Bot",
                "content": response_content,
                "is_game": is_game,
                "client_id": client_id
            })
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        db.close()