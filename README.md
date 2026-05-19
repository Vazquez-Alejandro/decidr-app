# Decidr

Mensajería instantánea con cifrado E2EE, llamadas, juegos y pagos integrados.

---

## Características

### Mensajería
- **Cifrado extremo a extremo** — Curve25519 + XSalsa20-Poly1305 (tweetnacl). Claves de sala compartidas entre pares con cifrado asimétrico.
- **Salas persistentes** — Grupos con membresía en DB, cada uno con su propia clave E2EE.
- **Mensajes programados** — Redacción y envío en fecha/hora elegida.
- **Selector de emojis** integrado.

### Llamadas
- **Voz y video** vía WebRTC con señalización WebSocket + STUN público.
- Interface con silenciar, toggle de cámara y colgar.

### Juegos
- 🎲 Dado más alto · 🪵 Palito más largo · ✊ PPT · 📝 Papelitos · 🔤 Palabras al azar

### Perfil
- Avatar, nombre visible, biografía, teléfono.
- **PIN público** (estilo BBM) — 6 caracteres únicos asignados al registrarse. Se puede buscar usuarios por PIN o teléfono.

### Pagos con Mercado Pago
- 💰 Botón en la barra de herramientas para **solicitar pagos**.
- El que envía: completa monto + concepto, se crea una preferencia en Mercado Pago Checkout Pro y se envía al chat.
- El que recibe: ve una tarjeta con el monto y un botón **"Pagar con MP"** que abre el link de pago.
- **Protegido con PIN de pago** — antes de generar cualquier solicitud, el backend exige un PIN numérico de 4-6 dígitos configurado por el usuario y verificado contra un hash bcrypt. Sin el PIN correcto no se crea la preferencia.
- Configurable en perfil (requiere contraseña de la cuenta para cambiar el PIN).
- Token de acceso configurable por usuario o global (archivo `.mp_token`).

### Personalización
- Fondos: colores, degradados o imagen subida.
- Color de burbuja, tamaño de fuente (12-20px), familia tipográfica.
- Tema persistente en localStorage.

### Seguridad
- Autenticación con bcrypt + JWT (HS256, 24h).
- Rate limiting (120 req/min).
- Bloqueo de usuarios.
- PIN de pago hasheado — ni siquiera el servidor conoce el PIN en texto plano.

### Interfaz
- Responsive, sidebar colapsable, swipe gesture en móvil.
- PWA: instalable, manifest, service worker.
- Completamente en español.

---

## Tecnologías

| Capa | Tecnología |
|------|-----------|
| Backend | Python 3.11+ · FastAPI · SQLAlchemy · SQLite · bcrypt · PyJWT |
| Frontend | HTML + Tailwind CSS · tweetnacl-js · WebRTC · WebSocket · PWA |
| Pagos | Mercado Pago API (Checkout Pro) |

---

## Instalación

```bash
git clone https://github.com/Vazquez-Alejandro/decidr-app.git
cd decidr-app
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
# Desarrollo
uvicorn main:app --reload --host 0.0.0.0 --port 8222

# Producción (con HTTPS)
./run.sh
```

### Configurar Mercado Pago

Para que los pagos funcionen, crear el archivo `.mp_token` en la raíz del proyecto con tu access token de Mercado Pago:

```bash
echo "APP_USR-xxxxxxxxxxxxxxxxxxxxxxxx" > .mp_token
```

O configurarlo desde la app (usuario admin "Alejandro") vía `POST /admin/mp-token`.

---

## API

### Autenticación
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/register` | Registro (devuelve token + PIN) |
| POST | `/login` | Inicio de sesión |

### Perfil
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/profile/{username}` | Perfil público (incluye `has_payment_pin`) |
| PUT | `/profile` | Actualizar nombre, bio, teléfono |
| POST | `/profile/avatar` | Subir avatar |
| POST | `/profile/payment-pin` | Configurar PIN de pago (requiere contraseña) |
| POST | `/profile/mp-token` | Configurar token MP propio |
| GET | `/me/pin` | Obtener mi PIN público |

### Salas
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/rooms` | Crear sala (o unirse si ya existe con ese nombre) |
| GET | `/rooms` | Listar salas del usuario |
| POST | `/rooms/{id}/join` | Unirse a una sala |
| POST | `/rooms/dm/{username}` | Crear DM con otro usuario |

### Pagos
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/payments/create` | Crear preferencia MP (requiere `payment_pin` si está configurado) |
| GET | `/payments/{pref_id}` | Consultar estado de una preferencia |
| POST | `/admin/mp-token` | Configurar token global de MP |

### Búsqueda y Bloqueos
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/users/search?q=` | Buscar por username, PIN o teléfono |
| POST | `/profile/block/{username}` | Bloquear usuario |
| DELETE | `/profile/block/{username}` | Desbloquear |
| GET | `/profile/blocked/list` | Listar bloqueados |

### WebSocket
| Endpoint | Descripción |
|----------|-------------|
| `/ws/{client_id}?token={jwt}` | Conexión bidireccional en tiempo real |

Tipos de mensaje: `text`, `payment`, `set_room`, `public_key`, `room_key_share`, `get_users`, `schedule`, `call_*`, `offer`, `answer`, `ice_candidate`, `game_action`.

---

## Estructura

```
decidr-app/
├── main.py              # Servidor FastAPI (rutas, WS, juegos, pagos)
├── database.py          # Modelos SQLAlchemy
├── index.html           # SPA frontend (todo en un archivo)
├── run.sh               # Lanzamiento HTTPS
├── requirements.txt     # Dependencias Python
├── .mp_token            # Token de Mercado Pago (no se sube a git)
├── .jwt_secret          # Secreto JWT (no se sube a git)
├── decidr.db            # SQLite (se crea solo)
├── certs/               # Certificados TLS
└── static/              # Manifest, service worker, iconos, avatares
```
