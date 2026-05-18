# Decidr

**Decidr** es una aplicación de mensajería instantánea con cifrado de extremo a extremo (E2EE), llamadas de voz/video, grupos persistentes y juegos integrados. Diseñada con un enfoque en privacidad, seguridad y usabilidad, similar a WhatsApp o Telegram pero autogestionada.

---

## Tabla de Contenidos

- [Características](#características)
- [Capturas](#capturas)
- [Tecnologías](#tecnologías)
- [Arquitectura](#arquitectura)
- [Seguridad](#seguridad)
- [Instalación](#instalación)
- [Uso](#uso)
- [API](#api)
- [Estructura del Proyecto](#estructura-del-proyecto)
- [Licencia](#licencia)

---

## Características

### Mensajería
- **Cifrado de extremo a extremo (E2EE)** — Todos los mensajes se cifran con **Curve25519 + XSalsa20-Poly1305** (tweetnacl) antes de salir del dispositivo. Las claves de sala se comparten entre pares mediante cifrado asimétrico.
- **Grupos reales** — Creación de salas persistentes con membresía en base de datos. Cada grupo tiene su propia clave E2EE.
- **Mensajes programados** — Programa mensajes para una fecha/hora específica, dirigidos a un usuario o a todo el grupo.
- **Selector de emojis** — Picker emoji integrado con cientos de emojis.

### Llamadas
- **Llamadas de voz** — WebRTC con señalización vía WebSocket y servidor STUN público.
- **Videollamadas** — Misma infraestructura con toggle de cámara, picture-in-picture del video local y soporte para pantalla completa.
- **Interfaz en llamada** — Barra superior con botones para silenciar, toggle de cámara y colgar.

### Juegos
- **🎲 Dado más alto** — Tira un dado y ve quién saca el número más alto.
- **🪵 Palito más largo** — Cada participante saca un número aleatorio; se revela el ranking.
- **✊ Piedra, Papel o Tijera** — Duelo 1 vs 1 con interfaz visual.
- **📝 Papelitos** — Pozo colaborativo de opciones; se sortea una al azar.
- **🔤 Palabras al azar** — Saca palabras de un pool temático (asados, bebidas, comidas).

### Perfil y Personalización
- **Perfil de usuario** — Foto de avatar (JPEG/PNG/WebP), nombre visible, biografía y número de teléfono.
- **Sistema PIN** — A cada usuario se le asigna un PIN único de 6 caracteres alfanuméricos al registrarse. Se puede compartir el PIN para que otros te agreguen sin exponer tu número de teléfono (estilo BlackBerry Messenger).
- **Búsqueda por PIN o teléfono** — La búsqueda de usuarios encuentra resultados por nombre de usuario, PIN o número de teléfono.
- **Configuración de Apariencia**:
  - Fondos de chat: presets de colores, degradados o imagen personalizada.
  - Color de burbuja propia: 6 colores predefinidos.
  - Tamaño de fuente: slider ajustable (12px–20px).
  - Familia tipográfica: Sistema, Segoe UI, Helvetica, Georgia, Courier New.
- **Privacidad** — Bloqueo de usuarios con filtrado server-side (los mensajes de usuarios bloqueados no se entregan).

### Seguridad
- **Autenticación** — Registro e inicio de sesión con contraseñas hasheadas (bcrypt) y tokens JWT (HS256, expiración 24h).
- **Rate Limiting** — 120 solicitudes por minuto por IP/usuario (HTTP) y por IP (WebSocket).
- **Cabeceras de seguridad** — HSTS, X-Frame-Options, X-Content-Type-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy.
- **HTTPS/WSS** — Soporte TLS incorporado con certificados autofirmados para desarrollo.
- **WebSocket autenticado** — El token JWT se valida al establecer la conexión WebSocket.

### Interfaz
- **Interfaz responsive** — Sidebar colapsable en móvil, soporte para swipe gesture.
- **PWA** — Service worker, manifest, iconos e instalación como app.
- **Idioma** — Completamente en español.

---

## Tecnologías

### Backend
- **Python 3.11+** — Lenguaje principal.
- **FastAPI** — Framework web asíncrono.
- **SQLAlchemy** — ORM para persistencia.
- **SQLite** — Base de datos embebida.
- **bcrypt** — Hashing de contraseñas.
- **PyJWT** — Generación y validación de tokens.
- **python-multipart** — Soporte para subida de archivos.
- **Uvicorn** — Servidor ASGI.

### Frontend
- **HTML5 + CSS3** — Interfase limpia y funcional.
- **Tailwind CSS** — Framework de utilidades CSS (vía CDN).
- **tweetnacl-js** — Criptografía de curva elíptica en el navegador.
- **WebRTC** — Llamadas de voz y video peer-to-peer.
- **WebSocket** — Comunicación bidireccional en tiempo real.
- **Service Worker** — Capacidades PWA.

---

## Arquitectura

```
┌──────────────────────────────────────────────────┐
│                   Cliente (Navegador)              │
│  ┌─────────┐  ┌──────────┐  ┌─────────────────┐  │
│  │ Chat UI │  │ Crypto   │  │ WebRTC (P2P)    │  │
│  │ (HTML)  │  │ (tweet-  │  │ STUN → Google   │  │
│  │         │  │ nacl)    │  │                 │  │
│  └────┬────┘  └────┬─────┘  └────────┬────────┘  │
│       │            │                  │           │
│       └──────┬─────┴──────────────────┘           │
│              │ WebSocket (+ JWT token)            │
└──────────────┼────────────────────────────────────┘
               │
┌──────────────┼────────────────────────────────────┐
│              │   Servidor FastAPI                  │
│  ┌───────────┴────────────┐                       │
│  │  WebSocket Manager     │  ┌─────────────────┐  │
│  │  - Conexiones activas  │  │ REST API        │  │
│  │  - Broadcast por sala  │  │ /login, /register│  │
│  │  - Filtro de bloqueos  │  │ /rooms, /profile │  │
│  │  - Señalización WebRTC │  │ /profile/block   │  │
│  └───────────┬────────────┘  └────────┬────────┘  │
│              │                        │           │
│              └──────────┬─────────────┘           │
│                         │                         │
│              ┌──────────┴──────────┐              │
│              │   SQLAlchemy + SQLite│              │
│              │  - users, messages   │              │
│              │  - rooms, members    │              │
│              │  - blocked_users     │              │
│              │  - scheduled_messages│              │
│              └─────────────────────┘              │
└──────────────────────────────────────────────────┘
```

### Flujo de Cifrado E2EE

1. **Cada usuario** genera un par de llaves (Curve25519) al registrarse y las almacena en `localStorage`.
2. **Al unirse a una sala**, si no existe clave de sala, el primer usuario la genera (`nacl.secretbox` keyLength = 32 bytes).
3. **Distribución**: la clave de sala se cifra con la clave pública de cada par (`nacl.box`) y se envía por WebSocket.
4. **Mensajes**: se cifran con `nacl.secretbox()` (XSalsa20-Poly1305) usando la clave de sala.
5. **Recepción**: se descifran con `nacl.secretbox.open()`. Si falla (clave no disponible), se muestra "🔒 Mensaje cifrado".

---

## Seguridad

| Aspecto | Implementación |
|---|---|
| Contraseñas | bcrypt con salt generado automáticamente |
| Tokens | JWT HS256 con expiración de 24 horas |
| WebSocket | Validación de token en cada conexión |
| Rate Limiting | 120 req/min por IP/usuario (HTTP) + IP (WebSocket) |
| CORS | No expuesto (no hay orígenes cruzados) |
| Headers | HSTS, XFO, X-Content-Type-Options, X-XSS-Protection, Referrer-Policy, Permissions-Policy |
| Cifrado | E2EE vía tweetnacl (Curve25519 + XSalsa20-Poly1305) |
| Transporte | HTTPS/WSS con TLS |

---

## Instalación

### Requisitos

- Python 3.11 o superior

### Pasos

```bash
# Clonar el repositorio
git clone https://github.com/tuusuario/decidr-app.git
cd decidr-app

# (Opcional) Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Instalar dependencias
pip install -r requirements.txt
```

---

## Uso

### Producción

```bash
./run.sh
```

El script `run.sh`:
1. Instala dependencias si es necesario.
2. Genera certificados TLS autofirmados en `certs/`.
3. Inicia el servidor con `uvicorn` sobre HTTPS (`https://localhost`).

### Desarrollo (sin HTTPS)

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Accedé a `http://localhost:8000` (sin cifrado E2EE funcional si el navegador bloquea `getUserMedia` en HTTP).

### Variables de Entorno

| Variable | Descripción | Default |
|---|---|---|
| `JWT_SECRET` | Secreto para firmar tokens JWT | Generado aleatoriamente |

---

## API

### Autenticación

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/register` | Registro de usuario |
| `POST` | `/login` | Inicio de sesión |

### Salas

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/rooms` | Crear sala |
| `GET` | `/rooms` | Listar salas del usuario |
| `POST` | `/rooms/{id}/join` | Unirse a una sala |
| `POST` | `/rooms/{id}/key` | Almacenar clave de sala |

### Perfil

| Método | Ruta | Descripción |
|---|---|---|
| `PUT` | `/profile` | Actualizar nombre visible, biografía y teléfono |
| `POST` | `/profile/avatar` | Subir foto de perfil |
| `GET` | `/profile/{username}` | Obtener perfil público (incluye PIN y teléfono) |
| `GET` | `/me/pin` | Obtener mi propio PIN |

### Búsqueda

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/users/search?q=` | Buscar usuarios por username, PIN o teléfono |

### Bloqueos

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/profile/block/{username}` | Bloquear usuario |
| `DELETE` | `/profile/block/{username}` | Desbloquear usuario |
| `GET` | `/profile/blocked/list` | Listar usuarios bloqueados |

### WebSocket

| Endpoint | Descripción |
|---|---|
| `/ws/{client_id}?token={jwt}` | Conexión bidireccional en tiempo real |

Tipos de mensajes WebSocket: `text`, `set_room`, `public_key`, `room_key_share`, `get_users`, `schedule`, `cancel_scheduled`, `list_scheduled`, `call_request`, `call_accept`, `call_reject`, `call_end`, `offer`, `answer`, `ice_candidate`, `game_action`.

---

## Estructura del Proyecto

```
decidr-app/
├── main.py              # Servidor FastAPI (rutas, WS, lógica de juegos)
├── database.py          # Modelos SQLAlchemy (UserDB, RoomDB, MessageDB, etc.)
├── index.html           # SPA frontend (login, chat, settings, perfil, juegos, llamadas)
├── run.sh               # Script de lanzamiento (certs + uvicorn SSL)
├── requirements.txt     # Dependencias Python
├── README.md            # Este archivo
├── decidr.db            # Base de datos SQLite (se crea automáticamente)
├── certs/               # Certificados TLS (generados por run.sh)
│   ├── cert.pem
│   └── key.pem
└── static/              # Archivos estáticos
    ├── manifest.json    # Manifiesto PWA
    ├── sw.js            # Service worker
    ├── icons/           # Iconos de la app
    │   ├── icon.svg
    │   └── logo.svg
    └── avatars/         # Avatares subidos por usuarios
```

---

## Licencia

Este proyecto es de uso privado. Todos los derechos reservados.
