# Decidr — Roadmap

## ✅ Done
- E2EE key exchange, key versioning, crypto self-test
- Per-user themes via `decidr_theme_{username}` localStorage key
- Auto-login block now calls `loadTheme(myUsername)`
- PIN system (6-char alphanumeric, BBM-style)
- Mercado Pago payments + payment PIN protection
- Emergency contact / remote disable for stolen devices
- Unread badges + notification sound + page title counter
- Message timestamps + info popup on click
- Profile modal for other users (click DM title)
- Settings modal with Guardar/Cancelar (theme live-preview)
- CSS: `background-color` + `background-image` separated (fixes solid colors)
- `switchRoom` no longer clears unread counts on auto-switch (`noClear` param)
- `handleMessage` wrapped in try-catch, each notification step individually caught
- Close chat button (✕) + `DELETE /rooms/{id}` endpoint
- Gradient wallpapers now set as `--chat-bg-image` instead of `--chat-bg`
- `loadTheme` backward compat: gradients stored in `bg` are migrated to `bgImage`
- File sharing (E2EE upload/download, 50MB limit)
- Push notifications (VAPID, service worker)
- TURN server (coturn, /ice-config)
- Edit/delete messages
- Reply to messages
- Multi-reply
- Typing indicator
- PostgreSQL support (DATABASE_URL)
- Environment variables (JWT_SECRET, MP_ACCESS_TOKEN)
- View once (bomb image)
- Message status (pending/sent/delivered/read)
- Online / last seen
- Privacy settings (read receipts, online status, last seen)
- Custom status text (presets + free text)
- Buzz (nudge) with configurable allow_buzz
- Audio/video file support (inline player with speed 1x/1.5x/2x, view once)
- Voice notes (record, encrypt, upload, playback with waveform)
- Ephemeral messages (auto-delete after timer, fade-out animation)
- Group admin (backend): is_admin column, promote/demote, add/remove members
- Group admin UI: room info modal with member list, admin controls, add member
- Message search (ILINE, 30 results, scroll-to + highlight)
- Forward/copy message (context menu, re-encrypt for target room)
- Channels (is_channel, admin-only messaging, 📢 icon, channel notice)
- Share contact (vCard-style card with avatar, name, phone, "Ver perfil")
- Block users (server-side enforcement in WS broadcast)
- Invite link + QR (InviteDB, generate, join, QR from api.qrserver.com)
- Message reactions (6 emoji picker, badges with user list)
- Polls (create with dynamic options, vote, percentage bars)
- Stickers (categorized picker, emoji + custom)
- Reminders (set from any message, configurable timer)
- Scheduled messages (date/time picker, target selector)
- Confirmaciones de lectura (✓, ✓✓, ✓✓ azul; delivered/read via WS)

## 🔜 Next

### 1. Multidispositivo — pendiente de implementar
**Objetivo:** Permitir que un usuario tenga múltiples sesiones (dispositivos) activas simultáneamente, con sincronización de claves E2EE.

**Plan tentativo:**
- Almacenar room-keys cifradas por usuario en el servidor (cifradas con su clave pública)
- Al iniciar sesión en un nuevo dispositivo, recuperar y descifrar las room-keys
- Sincronización vía WS cuando se agrega un nuevo dispositivo

### 2. Spotify integration — requires user action
**What the user needs to do:**
1. Go to https://developer.spotify.com/dashboard
2. Log in with your Spotify account
3. Click "Create App" → name: "Decidr", description: "Mostrar lo que escucho en el chat"
4. Copy **Client ID** and **Client Secret**
5. Add `http://localhost:8000/spotify/callback` (or your domain) as Redirect URI
6. Pass those values to the dev when implementing

**What the code will do:**
- `UserDB.spotify_access_token`, `spotify_refresh_token`
- OAuth flow: `/spotify/login` → Spotify → `/spotify/callback` → store tokens
- Background task: poll `https://api.spotify.com/v1/me/player/currently-playing` every 30s
- Broadcast `set_status` via WS when track changes
- Frontend shows "🎵 *Song* — *Artist*" in status

### 3. Full-screen animations (beso, corazones, etc.) — requires user action
**What the user needs to do:**
- Find/buy/create animated GIFs or CSS animations (e.g., kiss, hearts, fireworks)
- Options:
  a) **GIFs** — search Tenor/Giphy for "kiss animation", etc., download or hotlink
  b) **CSS particles** — heart-shaped divs that float upward with CSS animation
  c) **Lottie animations** — lightweight JSON animations from lottiefiles.com

**What the code will do:**
- WS type `animation` with `type: "kiss" | "hearts" | ...`
- Receiver shows fullscreen overlay with the animation for 3s
- Configurable "allow_animations" toggle in privacy
- Button next to buzz in chat footer to send animation

## 🔧 Backlog (Technical debt / improvements)
- Alembic migrations (instead of manual DB recreate on schema changes)
- Logging (instead of print())
- Message history loading / infinite scroll
- Read receipts respect privacy completely (contacts mode needs contact list)
- Notification click opens correct chat

## Key Context for Next Time
- **Crypto.encryptRoomKeyFor** must receive `Uint8Array` (peer public key bytes), not string
- Key convergence: `handleRoomKeyShare` shares smaller key back to peer on collision
- `requestRoomKey` times out at 800ms → generates local key if peer hasn't shared
- `broadcast_user_list` uses `manager.user_data` for public keys (not DB)
- `.mp_token` file = Mercado Pago production access token
- `payments_disabled` flag checked at `/payments/create`
- Notification uses Web Audio API beep (520 Hz sine, 300ms) — no audio file
- Per-user theme key: `decidr_theme_{username}`
- Room IDs are strings in `currentRoom`, numbers in `r.id` -> use `r.id.toString()`
- `active_connections` is `dict[str, WebSocket]` — only ONE connection per username
- Status presets: Disponible, Ocupado, Ausente, En llamada, No molestar
- Buzz anim: CSS `@keyframes buzzShake` + `navigator.vibrate(400)` + square wave 200Hz
- Cualquier cambio de esquema SQLite requiere borrar `decidr.db` y recrear
- Token file en `/home/alejandro/Escritorio/Proyectos/token.txt` con formato `github: ghp_...`
- Remote real: `https://github.com/Vazquez-Alejandro/decidr-app.git`
- Push con: `git -c credential.helper=... push` o seteando remote URL con token
- Restaurar remote a `git@github.com:anomalyco/decidr-app.git` después del push
