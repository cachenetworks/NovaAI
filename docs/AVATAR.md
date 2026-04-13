# 🧑‍🎤 Avatar System

> **🚧 Coming Soon** — The avatar system is under active development. Everything below describes the planned feature set. Some parts work today, others are still being built. Star the repo and watch for updates!

---

Your AI companion deserves a face. The avatar system gives NovaAI a full 3D VRM model that reacts to conversations in real-time — emotions, danger alerts, the works. Think VTuber, but it's your AI buddy staring back at you.

---

## ✨ What It Does

| | Feature | Details |
|---|---------|---------|
| 🧍 | **3D VRM Viewer** | Three.js-powered portal with drag-and-drop model upload |
| 🔌 | **WebSocket Bridge** | Real-time state updates between backend and avatar |
| 😄 | **Emotion Detection** | Keyword-based mood analysis pushed to the avatar |
| 🚨 | **Danger Detection** | Safety-critical keyword flagging with visual alerts |
| ⏰ | **Reminder Alerts** | Due reminders notify the avatar frontend too |
| 💾 | **Persistence** | Last loaded VRM is remembered and auto-restored |

---

## 🖥️ Avatar Portal

A standalone web page served at `http://localhost:8766/` that renders your VRM model in 3D.

**How to open it:**
- Click **"Open Avatar Portal"** from the GUI, or
- Navigate to `http://localhost:8766/` in any browser

**Portal sections:**

| Section | What It Shows |
|---------|-------------|
| 🎨 **Avatar Viewer** | 3D canvas rendering your VRM model |
| 📤 **VRM Upload** | Drag-drop zone or file picker |
| 🟢 **Connection Status** | WebSocket link indicator |
| 📋 **Activity Log** | Real-time event stream |

---

## 📤 Uploading a VRM Model

Three ways to get your model in:

| Method | How |
|--------|-----|
| **Drag & Drop** | Drop a `.vrm` file onto the portal upload zone |
| **File Picker** | Click "Load VRM File" in the GUI |
| **HTTP API** | `POST /upload` to the avatar bridge directly |

Models are copied to `data/avatars/` and the path is saved in your profile — so it auto-loads next time you start NovaAI.

---

## 😄 Emotion Detection

The system scans conversation text for mood keywords and pushes the detected emotion to the avatar.

| Emotion | Trigger Words |
|---------|--------------|
| 😊 `happy` | happy, love, excited, awesome, joy |
| 😢 `sad` | sad, upset, hurt, depressed |
| 😰 `anxious` | scared, afraid, nervous, worried |
| 😡 `angry` | angry, mad, furious, irritated |
| 😐 `neutral` | *(default — no strong keywords detected)* |

> This is keyword-based for now. ML-powered sentiment analysis is on the roadmap.

---

## 🚨 Danger Detection

Safety-critical keywords trigger a danger flag pushed to the avatar frontend.

**Trigger words:** `danger`, `fire`, `help`, `emergency`, `attack`, `threat`, `warning`, `alarm`

When triggered, the avatar can display visual/audio alerts or play specific animations. Works alongside emotion detection — both states are sent in a single WebSocket payload.

---

## 🔧 Architecture

### Backend — Avatar Bridge (`novaai/avatar.py`)

Runs an HTTP server + WebSocket server side by side:

| Port | Protocol | Purpose |
|------|----------|---------|
| `8766` | HTTP | Serves the avatar portal + handles VRM uploads |
| `8765` | WebSocket | Broadcasts state, emotion, danger, and reminder events |

**HTTP endpoints:**

| Route | Method | What It Does |
|-------|--------|-------------|
| `/` | GET | Serves the avatar portal HTML |
| `/upload` | POST | Receives VRM file uploads |
| `/uploads/` | GET | Serves uploaded VRM files |

**WebSocket payloads:**

```json
{ "type": "avatar",   "event": "load",  "url": "/uploads/model.vrm" }
{ "type": "state",    "payload": { "emotion": "happy", "danger": false } }
{ "type": "reminder", "event": "due",   "reminder": { "id": "...", "title": "..." } }
{ "type": "hello",    "status": "connected" }
```

### Frontend — Avatar Portal (`novaai/static/avatar.html`)

Standalone HTML5 app using:
- **Three.js** — 3D rendering engine
- **@pixiv/three-vrm** — VRM model loader
- **WebSocket API** — real-time backend connection

---

## 💾 Data Structures

### Avatar Settings (in profile JSON)

Stored under `profile_details.avatar`:

```json
{
  "avatar": {
    "enabled": false,
    "vrm_path": "path/to/model.vrm",
    "last_loaded_vrm_path": "data/avatars/model.vrm",
    "websocket_url": "ws://127.0.0.1:8765"
  }
}
```

### Reminder Events

When a reminder fires, the avatar bridge broadcasts:

```json
{
  "type": "reminder",
  "event": "due",
  "reminder": {
    "id": "reminder-1234567890",
    "title": "Take a break",
    "due": "2025-03-15 14:30"
  }
}
```

---

## 🔧 Troubleshooting

### Portal won't open

- Check ports `8765` (WebSocket) and `8766` (HTTP) are free
- Firewall might be blocking local connections
- Try `http://127.0.0.1:8766/` directly

### VRM model won't load

- Make sure it's a valid `.vrm` file
- Check `data/avatars/` to confirm the file landed
- Open browser dev console for error details
- Try refreshing the portal

### WebSocket won't connect

- Verify `websockets>=11` is installed
- Check port `8765` isn't taken by another process
- Restart NovaAI and try again
- Browser console will show connection errors

---

## 🗺️ Roadmap

- [ ] Animation and blend shape control from WebSocket messages
- [ ] ML-based sentiment analysis (replacing keyword matching)
- [ ] Avatar expression/gesture mapping to emotion states
- [ ] Multi-model support — switch VRMs on the fly
- [ ] Recurring reminder notifications to avatar
- [ ] Reminder snooze from the avatar portal
- [ ] Remote avatar deployment with CORS support
