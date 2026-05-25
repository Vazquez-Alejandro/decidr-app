# Decidr

Mensajería instantánea con cifrado E2EE, llamadas, juegos y pagos integrados.

---

## Características

### Mensajería
- **Cifrado extremo a extremo** — Curve25519 + XSalsa20-Poly1305 (tweetnacl). Claves de sala compartidas entre pares con cifrado asimétrico.
- **Salas persistentes** — Grupos con membresía en DB, cada uno con su propia clave E2EE.
- **Canales** — Salas de solo-lectura donde solo los admins pueden enviar mensajes. Indicadas con 📢 en la lista.
- **Mensajes programados** — Redacción y envío en fecha/hora elegida.
- **Mensajes efímeros** — Auto-destrucción a los 5s/30s/1m/5m/1h con fade-out animado.
- **Notas de voz** — Grabación y envío con micrófono, cifrado E2EE, waveform y reproducción con velocidad ajustable (1x/1.5x/2x).
- **Selector de emojis** integrado con +500 emojis.
- **Editar y eliminar mensajes** — ✏️ y 🗑️ en burbujas propias, broadcast en tiempo real.
- **Responder mensajes (reply)** — ↩️ en burbujas ajenas, preview con cita. Soporte multi-reply seleccionando varios mensajes a la vez.
- **Reenviar mensajes** — Menú contextual (clic derecho) con "Copiar texto" y "Reenviar" a otra sala, re-cifrado automático.
- **Compartir contacto** — Botón 👤 que envía tarjeta con avatar, nombre, teléfono y botón "Ver perfil".
- **Reacciones** — 6 emojis (👍❤️😂😮😢😡) con badges que muestran quién reaccionó.
- **Stickers** — Selector por categorías (caritas, manos, corazones, animales, comida, objetos, banderas).
- **Encuestas** — Creación con opciones dinámicas, voto múltiple, barras de porcentaje.
- **Recordatorios** — ⏰ sobre cualquier mensaje (10min/30min/1h/2h/1d o personalizado).
- **Compartir archivos** — Imágenes, PDFs, documentos, audio/video hasta 50 MB. Cifrados E2EE con clave por archivo.
- **Ver una sola vez** — Contenido multimedia que se auto-destruye tras ser visto (server-side + client-side).
- **Indicador de escritura** — Muestra en tiempo real quién está escribiendo en la sala.
- **Confirmaciones de lectura** — Estados ✓ (enviado), ✓✓ (recibido), ✓✓ azul (leído).
- **Búsqueda de mensajes** — 🔍 en el header, resultados clickeables con scroll + highlight.
- **Enlace de invitación + QR** — Genera link único con QR escaneable para unirse a una sala.

### Llamadas
- **Voz y video** vía WebRTC con señalización WebSocket + STUN público + **TURN server local** (coturn) para conectividad NAT.
- Interface con silenciar, toggle de cámara y colgar.
- **Modal de llamada entrante** con accept/reject.

### Juegos
- 🎲 Dado más alto · 🪵 Palito más largo · ✊ PPT · 📝 Papelitos · 🔤 Palabras al azar

### Administración de grupos
- **Ver miembros** de una sala (modal 👥 desde el header).
- **Agregar miembros** por nombre de usuario.
- **Eliminar miembros** (solo admins).
- **Promover/deponer admins** con un clic.
- El creador de la sala es admin automático.

### Notificaciones push
- **Notificaciones Web Push** vía Service Worker + pywebpush.
- Suscripción automática al iniciar sesión.
- Notificaciones de mensajes nuevos en salas no visibles.

### Perfil
- Avatar, nombre visible, biografía, teléfono.
- **PIN público** (estilo BBM) — 6 caracteres únicos asignados al registrarse. Se puede buscar usuarios por PIN o teléfono.
- **Estado personalizado** — Texto libre + presets (Disponible, Ocupado, Ausente, En llamada, No molestar).

### Privacidad
- **Bloqueo de usuarios** — Bloquear/desbloquear desde perfil o lista de usuarios. Los mensajes no se entregan a usuarios que te bloquearon.
- **Confirmaciones de lectura** — Activar/desactivar.
- **Visibilidad de estado online** — Todos / Mis contactos / Nadie.
- **Visibilidad de última vez** — Todos / Mis contactos / Nadie.
- **Permitir buzz** — Activar/desactivar recibir vibraciones.

### Pagos con Mercado Pago
- 💰 Botón en la barra de herramientas para **solicitar pagos**.
- El que envía: completa monto + concepto, se crea una preferencia en Mercado Pago Checkout Pro y se envía al chat.
- El que recibe: ve una tarjeta con el monto y un botón **"Pagar con MP"** que abre el link de pago.
- **Protegido con PIN de pago** — antes de generar cualquier solicitud, el backend exige un PIN numérico de 4-6 dígitos configurado por el usuario y verificado contra un hash bcrypt. Sin el PIN correcto no se crea la preferencia.
- Configurable en perfil (requiere contraseña de la cuenta para cambiar el PIN).
- Token de acceso configurable por usuario o global (archivo `.mp_token`).
- **Contacto de emergencia** — Usuario de confianza que puede desactivar/activar pagos remotos.

### Personalización
- Fondos: colores, degradados o imagen subida.
- Color de burbuja (6 presets), tamaño de fuente (12-20px), familia tipográfica.
- Tema persistente en localStorage (vinculado al usuario).

### Seguridad
- Autenticación con bcrypt + JWT (HS256, 24h configurable).
- Rate limiting (120 req/min).
- Bloqueo de usuarios (server-side enforcement en broadcast).
- PIN de pago hasheado — ni siquiera el servidor conoce el PIN en texto plano.
- TURN server autenticado (username/password estático).
- Headers de seguridad (HSTS, XSS, Content-Type, Frame-Options, etc.).

### Interfaz
- Responsive, sidebar colapsable, swipe gesture en móvil.
- PWA: instalable, manifest, service worker.
- Completamente en español.

---

## Tecnologías

| Capa | Tecnología |
|------|-----------|
| Backend | Python 3.11+ · FastAPI · SQLAlchemy · SQLite/PostgreSQL · bcrypt · PyJWT · pywebpush |
| Frontend | HTML + Tailwind CSS · tweetnacl-js · WebRTC · WebSocket · PWA |
| Llamadas | WebRTC + coturn (TURN local) |
| Pagos | Mercado Pago API (Checkout Pro) |
| Notificaciones | Web Push API + VAPID |

---

## Instalación

```bash
git clone https://github.com/Vazquez-Alejandro/decidr-app.git
cd decidr-app
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### PostgreSQL (opcional)

Por defecto usa SQLite. Para PostgreSQL, configurar la variable de entorno:

```bash
export DATABASE_URL="postgresql://user:pass@localhost/decidr"
```

## Uso

```bash
# Desarrollo
DATABASE_URL="sqlite:///./decidr.db" uvicorn main:app --reload --host 0.0.0.0 --port 8222

# Producción (con HTTPS + TURN)
./run.sh
```

### Configurar Mercado Pago

```bash
# Opción A: archivo directo
echo "APP_USR-xxxxxxxxxxxxxxxxxxxxxxxx" > .mp_token

# Opción B: variable de entorno (en .env)
echo "MP_ACCESS_TOKEN=APP_USR-xxxxxxxxxxxxxxxxxxxxxxxx" >> .env
```

O configurarlo desde la app (usuario admin "Alejandro") vía `POST /admin/mp-token`.

### Variables de entorno

Todas las configuraciones sensibles son configurables vía `.env`:

| Variable | Default | Descripción |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./decidr.db` | Conexión a DB |
| `JWT_SECRET` | (auto-generado) | Secreto para firmar tokens |
| `JWT_EXPIRY` | `86400` | Expiración del token en segundos |
| `MP_ACCESS_TOKEN` | (desde `.mp_token`) | Token de Mercado Pago |

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
| PUT | `/status` | Actualizar estado personalizado |
| GET | `/status` | Obtener estado actual |

### Privacidad
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/privacy/settings` | Obtener ajustes de privacidad |
| PUT | `/privacy/settings` | Actualizar ajustes de privacidad |
| POST | `/profile/block/{username}` | Bloquear usuario |
| DELETE | `/profile/block/{username}` | Desbloquear |
| GET | `/profile/blocked/list` | Listar bloqueados |
| POST | `/profile/emergency` | Configurar contacto de emergencia |
| POST | `/payments/remote-disable` | Contacto de emergencia desactiva pagos |
| POST | `/payments/remote-enable` | Contacto de emergencia reactiva pagos |

### Salas
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/rooms` | Crear sala (opcionalmente como canal) |
| GET | `/rooms` | Listar salas del usuario (incluye `is_admin`, `is_channel`) |
| POST | `/rooms/{id}/join` | Unirse a una sala |
| DELETE | `/rooms/{id}` | Eliminar sala (y todos sus mensajes) |
| POST | `/rooms/dm/{username}` | Crear DM con otro usuario |
| POST | `/rooms/{id}/invite` | Generar código de invitación |
| GET | `/invite/{code}` | Obtener info de invitación |
| POST | `/invite/{code}/join` | Unirse por código de invitación |
| GET | `/rooms/{id}/members` | Listar miembros de la sala |
| POST | `/rooms/{id}/members` | Admin agrega miembro |
| DELETE | `/rooms/{id}/members/{username}` | Admin elimina miembro |
| PUT | `/rooms/{id}/members/{username}` | Admin cambia rol (admin/no-admin) |

### Mensajes
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/rooms/{room_id}/search?q=` | Buscar mensajes por contenido |
| PUT | `/messages/{message_id}` | Editar mensaje (dueño solamente) |
| DELETE | `/messages/{message_id}` | Eliminar mensaje (dueño solamente) |

### Cifrado
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/rooms/{room_id}/key` | Almacenar clave de sala cifrada |

### Archivos
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/files/upload` | Subir archivo cifrado (max 50 MB, opcional `view_once`) |
| GET | `/files/{file_id}` | Descargar archivo (verifica membresía, enforce view_once) |
| POST | `/files/{file_id}/mark-viewed` | Marcar view_once como visto (borra del disco) |

### Pagos
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/payments/create` | Crear preferencia MP (requiere `payment_pin` si está configurado) |
| GET | `/payments/{pref_id}` | Consultar estado de una preferencia |
| POST | `/admin/mp-token` | Configurar token global de MP |

### Búsqueda
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/users/search?q=` | Buscar por username, PIN o teléfono |

### Push / Llamadas
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/push/subscribe` | Suscribir a notificaciones push |
| POST | `/push/unsubscribe` | Desuscribir |
| GET | `/push/vapid-public-key` | Obtener clave pública VAPID |
| GET | `/ice-config` | Configuración STUN/TURN para WebRTC |

### WebSocket
| Endpoint | Descripción |
|----------|-------------|
| `/ws/{client_id}?token={jwt}` | Conexión bidireccional en tiempo real |

Tipos de mensaje cliente→servidor: `text`, `payment`, `set_room`, `public_key`, `room_key_share`, `get_users`, `schedule`, `list_scheduled`, `cancel_scheduled`, `call_*`, `offer`, `answer`, `ice_candidate`, `game_action`, `typing`, `stop_typing`, `edit_message`, `delete_message`, `delivered`, `read`, `reaction`, `create_poll`, `vote_poll`, `sticker`, `create_reminder`, `get_user_status`, `set_status`, `buzz`, `set_allow_buzz`, `set_username`.

---

## Estructura

```
decidr-app/
├── main.py              # Servidor FastAPI (rutas, WS, juegos, pagos, push, TURN)
├── database.py          # Modelos SQLAlchemy
├── index.html           # SPA frontend (todo en un archivo)
├── run.sh               # Lanzamiento HTTPS + TURN server
├── turn.sh              # Gestor de coturn (start/stop/status)
├── turnserver.conf      # Configuración de coturn
├── requirements.txt     # Dependencias Python
├── .env                 # Variables de entorno (configurable)
├── .mp_token            # Token de Mercado Pago (no se sube a git)
├── .jwt_secret          # Secreto JWT (no se sube a git)
├── .vapid_keys          # Claves VAPID para push (no se sube a git)
├── .vapid_public        # Clave pública VAPID (no se sube a git)
├── decidr.db            # SQLite (se crea solo)
├── certs/               # Certificados TLS
└── static/              # Manifest, service worker, iconos, avatares
```
