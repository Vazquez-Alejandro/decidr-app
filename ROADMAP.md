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

## ❌ Remaining Issues (for next session)

### 1. Notifications still don't fire
**To debug:**
1. Open Console (F12) in both browser windows
2. Make sure both accounts are logged in
3. Make sure each account is in a DIFFERENT room
4. Send a message from account A
5. Look for these logs in account B's console:
   - `handleMessage type: chat room: <id> cid: <from> myId: <to> currRoom: <current>`
   - `notify: FIRING for room ...` (if room differs)
   - If "notify: SAME room msg" → B is in the same room as A
   - If neither → the `else` block isn't reached; check `d.type`
   - If `d.room !== currentRoom` is false but should be true → type mismatch (string vs string?)
   - If any error, it will show as `handleMessage error: ...`

**Possible causes:**
- `currentRoom` not properly set at message arrival time
- Both accounts somehow in the same room
- WebSocket not receiving the broadcast (unlikely)

### 2. Close chat button (✕) doesn't appear
**Possible causes:**
- Page not refreshed after code changes (Ctrl+F5 needed)
- `myRooms.find(r => r.id.toString() === currentRoom)` returns undefined
  - If `fetchRooms()` failed, `myRooms` is empty
  - If `currentRoom` doesn't match any room ID
  - Check console for `switchRoom called` -> what `id` and `name`?

### 3. (Fixed) Gradients not rendering
Gradients were being set as `background-color: linear-gradient(...)` which is invalid.
**Fixed:** Now sets gradient as `--chat-bg-image` with `--chat-bg: #f0f5f9` as fallback.
Old saved themes with gradient in `bg` are auto-migrated on `loadTheme`.

### 4. (Fixed) Auto-login per-user theme
`(async function(){...})()` IIFE that auto-logs in skipped `loadTheme(myUsername)`.
**Fixed:** Added `loadTheme(myUsername)` before `initApp()` in the IIFE.

## Next Session Kickoff
1. Read this ROADMAP.md
2. Fix notifications (ask user for console logs first)
3. Fix close chat button (check console logs for `switchRoom called`)
4. Deploy, play, profit

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
