"""
Switch 2 Browser — Play Switch 2 in your browser
FastAPI + WebSocket + Serial + HDMI Capture (getUserMedia)
Usage: python server.py [COM_PORT]
"""
import sys
import json
import asyncio
import time
import serial
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.requests import Request
from pathlib import Path

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
BAUD = 115200
HEADER = 0xAA
CENTER = 128
HAT_NEUTRAL = 0x08
MACROS_FILE = Path(__file__).parent / "macros.json"
GAMES_DIR = Path(__file__).parent / "games"

# --- Active game config ---
active_game = None  # loaded game-info.json
active_game_name = None
input_min_ms = 33  # default: 2F @ 60fps

# --- Serial connection ---
ser = None
macro_running = False
last_ws_report = 0
# Macro state that can be OR'd with manual input
macro_btn0 = 0
macro_btn1 = 0
macro_hat = HAT_NEUTRAL
macro_lx = CENTER
macro_ly = CENTER
macro_rx = CENTER
macro_ry = CENTER

def serial_connect():
    global ser
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
        print(f"Serial connected: {PORT}")
        return True
    except Exception as e:
        print(f"Serial error: {e}")
        return False

def send_report(btn0=0, btn1=0, hat=HAT_NEUTRAL, lx=CENTER, ly=CENTER, rx=CENTER, ry=CENTER):
    if not ser or not ser.is_open:
        return False
    cksum = btn0 ^ btn1 ^ hat ^ lx ^ ly ^ rx ^ ry
    pkt = bytes([HEADER, btn0, btn1, hat, lx, ly, rx, ry, cksum])
    try:
        ser.write(pkt)
        return True
    except:
        return False

# --- Macro engine ---
def load_macros():
    if MACROS_FILE.exists():
        return json.loads(MACROS_FILE.read_text(encoding="utf-8"))
    return {"macros": []}

def save_macros(data):
    MACROS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

# --- Overlay state ---
overlay_config = {
    "grid": {"enabled": False, "rows": 10, "cols": 16, "color": "#00ff00", "opacity": 0.4, "showLabels": True, "labelColor": "#00ff00", "labelSize": 10},
    "boxes": [],
    "region": {"x": 0, "y": 0, "w": 1, "h": 1},
    "clip": None,
}

loop_task = None

async def run_macro(steps, loop=False):
    global macro_running, macro_btn0, macro_btn1, macro_hat, macro_lx, macro_ly, macro_rx, macro_ry
    macro_running = True
    try:
        while True:
            for step in steps:
                if not macro_running:
                    return
                macro_btn0 = step.get("btn0", 0)
                macro_btn1 = step.get("btn1", 0)
                macro_hat = step.get("hat", HAT_NEUTRAL)
                macro_lx = step.get("lx", CENTER)
                macro_ly = step.get("ly", CENTER)
                macro_rx = step.get("rx", CENTER)
                macro_ry = step.get("ry", CENTER)
                duration = step.get("duration_ms", 100) / 1000.0
                end = time.time() + duration
                while time.time() < end:
                    if not macro_running:
                        return
                    if time.time() - last_ws_report > 2.0:
                        send_report(macro_btn0, macro_btn1, macro_hat,
                                    macro_lx, macro_ly, macro_rx, macro_ry)
                    await asyncio.sleep(0.016)
            if not loop:
                break
    finally:
        macro_btn0 = macro_btn1 = 0
        macro_hat = HAT_NEUTRAL
        macro_lx = macro_ly = macro_rx = macro_ry = CENTER
        macro_running = False
        send_report()

# --- FastAPI ---
app = FastAPI()

@app.get("/")
async def index():
    html = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)

@app.get("/api/macros")
async def get_macros():
    return JSONResponse(load_macros())

@app.post("/api/macros")
async def post_macros(request: Request):
    data = await request.json()
    save_macros(data)
    return JSONResponse({"ok": True})

@app.post("/api/macros/run/{idx}")
async def run_macro_endpoint(idx: int):
    data = load_macros()
    if idx < 0 or idx >= len(data.get("macros", [])):
        return JSONResponse({"error": "invalid index"}, status_code=400)
    asyncio.create_task(run_macro(data["macros"][idx]["steps"]))
    return JSONResponse({"ok": True, "name": data["macros"][idx]["name"]})

@app.post("/api/macros/loop/{idx}")
async def loop_macro_endpoint(idx: int):
    global loop_task, macro_running
    data = load_macros()
    if idx < 0 or idx >= len(data.get("macros", [])):
        return JSONResponse({"error": "invalid index"}, status_code=400)
    if loop_task and not loop_task.done():
        macro_running = False
        await asyncio.sleep(0.05)
    loop_task = asyncio.create_task(run_macro(data["macros"][idx]["steps"], loop=True))
    return JSONResponse({"ok": True, "name": data["macros"][idx]["name"]})

@app.post("/api/macros/stop")
async def stop_macro_endpoint():
    global macro_running
    macro_running = False
    send_report()
    return JSONResponse({"ok": True})

# --- Overlay API ---
@app.get("/api/overlay")
async def get_overlay():
    return JSONResponse(overlay_config)

@app.post("/api/overlay")
async def set_overlay(request: Request):
    global overlay_config
    overlay_config = await request.json()
    return JSONResponse({"ok": True})

@app.post("/api/overlay/grid")
async def set_grid(request: Request):
    data = await request.json()
    overlay_config["grid"].update(data)
    return JSONResponse({"ok": True, "grid": overlay_config["grid"]})

@app.post("/api/overlay/region")
async def set_region(request: Request):
    data = await request.json()
    overlay_config["region"].update(data)
    return JSONResponse({"ok": True, "region": overlay_config["region"]})

@app.post("/api/overlay/box")
async def add_or_update_box(request: Request):
    data = await request.json()
    box_id = data.get("id")
    if box_id:
        for i, b in enumerate(overlay_config["boxes"]):
            if b.get("id") == box_id:
                overlay_config["boxes"][i] = data
                return JSONResponse({"ok": True, "action": "updated"})
    overlay_config["boxes"].append(data)
    return JSONResponse({"ok": True, "action": "added"})

@app.delete("/api/overlay/box/{box_id}")
async def delete_box(box_id: str):
    overlay_config["boxes"] = [b for b in overlay_config["boxes"] if b.get("id") != box_id]
    return JSONResponse({"ok": True})

@app.post("/api/overlay/clip")
async def set_clip(request: Request):
    data = await request.json()
    overlay_config["clip"] = data if data else None
    return JSONResponse({"ok": True, "clip": overlay_config["clip"]})

@app.post("/api/overlay/clear")
async def clear_overlay():
    overlay_config["boxes"] = []
    overlay_config["grid"]["enabled"] = False
    overlay_config["region"] = {"x": 0, "y": 0, "w": 1, "h": 1}
    overlay_config["clip"] = None
    return JSONResponse({"ok": True})

@app.post("/api/overlay/save")
async def save_overlay_to_file():
    if not active_game_name:
        return JSONResponse({"error": "no game loaded"}, status_code=400)
    overlay_file = GAMES_DIR / active_game_name / "overlay.json"
    # Read existing file to preserve metadata
    if overlay_file.exists():
        data = json.loads(overlay_file.read_text(encoding="utf-8"))
    else:
        data = {}
    data["grid"] = overlay_config.get("grid", {})
    data["region"] = overlay_config.get("region", {})
    data["clip"] = overlay_config.get("clip")
    overlay_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True, "file": str(overlay_file)})

# --- Game API ---
@app.get("/api/games")
async def list_games():
    if not GAMES_DIR.exists():
        return JSONResponse({"games": []})
    games = []
    for d in sorted(GAMES_DIR.iterdir()):
        if d.is_dir() and (d / "game-info.json").exists():
            info = json.loads((d / "game-info.json").read_text(encoding="utf-8"))
            games.append({"id": d.name, "name": info.get("name", d.name)})
    return JSONResponse({"games": games})

@app.post("/api/games/load/{game_id}")
async def load_game(game_id: str):
    global active_game, active_game_name, input_min_ms, overlay_config
    game_dir = GAMES_DIR / game_id
    if not (game_dir / "game-info.json").exists():
        return JSONResponse({"error": "game not found"}, status_code=404)
    active_game = json.loads((game_dir / "game-info.json").read_text(encoding="utf-8"))
    active_game_name = game_id
    # Apply input settings
    inp = active_game.get("input", {})
    input_min_ms = inp.get("min_duration_ms", 33)
    # Load overlay if exists
    overlay_file = game_dir / "overlay.json"
    if overlay_file.exists():
        ov = json.loads(overlay_file.read_text(encoding="utf-8"))
        overlay_config["grid"] = ov.get("grid", overlay_config["grid"])
        overlay_config["region"] = ov.get("region", overlay_config["region"])
        overlay_config["clip"] = ov.get("clip", overlay_config["clip"])
    return JSONResponse({"ok": True, "game": active_game_name, "input_min_ms": input_min_ms})

@app.get("/api/games/current")
async def current_game():
    return JSONResponse({"game": active_game_name, "config": active_game, "input_min_ms": input_min_ms})

# --- Screen API (switch screen overlay presets) ---
active_screen = None

@app.get("/api/screens")
async def list_screens():
    if not active_game_name:
        return JSONResponse({"screens": []})
    screens_dir = GAMES_DIR / active_game_name / "screens"
    if not screens_dir.exists():
        return JSONResponse({"screens": []})
    screens = []
    for f in sorted(screens_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        screens.append({"id": f.stem, "description": data.get("description", f.stem)})
    return JSONResponse({"screens": screens, "active": active_screen})

@app.post("/api/screens/load/{screen_id}")
async def load_screen(screen_id: str):
    global active_screen, overlay_config
    if not active_game_name:
        return JSONResponse({"error": "no game loaded"}, status_code=400)
    screen_file = GAMES_DIR / active_game_name / "screens" / f"{screen_id}.json"
    if not screen_file.exists():
        return JSONResponse({"error": "screen not found"}, status_code=404)
    data = json.loads(screen_file.read_text(encoding="utf-8"))
    overlay_config["boxes"] = data.get("boxes", [])
    active_screen = screen_id
    return JSONResponse({"ok": True, "screen": screen_id, "boxes": len(overlay_config["boxes"])})

@app.post("/api/screens/save/{screen_id}")
async def save_screen(screen_id: str, request: Request):
    if not active_game_name:
        return JSONResponse({"error": "no game loaded"}, status_code=400)
    screens_dir = GAMES_DIR / active_game_name / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    screen_file = screens_dir / f"{screen_id}.json"
    # Merge with existing or create new
    if screen_file.exists():
        data = json.loads(screen_file.read_text(encoding="utf-8"))
    else:
        data = {"screen": screen_id, "description": screen_id}
    body = await request.json()
    if "boxes" in body:
        data["boxes"] = body["boxes"]
    elif "description" in body:
        data["description"] = body["description"]
    else:
        # Save current overlay boxes
        data["boxes"] = overlay_config.get("boxes", [])
    screen_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True, "screen": screen_id})

@app.post("/api/screens/clear")
async def clear_screen():
    global active_screen
    overlay_config["boxes"] = []
    active_screen = None
    return JSONResponse({"ok": True})

@app.post("/api/screens/signature/{screen_id}")
async def save_screen_signature(screen_id: str, request: Request):
    """Save pixel signature for a screen (for auto-detection). Body: {signature: [{x,y,r,g,b},...]}"""
    if not active_game_name:
        return JSONResponse({"error": "no game loaded"}, status_code=400)
    screens_dir = GAMES_DIR / active_game_name / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)
    screen_file = screens_dir / f"{screen_id}.json"
    if screen_file.exists():
        data = json.loads(screen_file.read_text(encoding="utf-8"))
    else:
        data = {"screen": screen_id, "description": screen_id}
    body = await request.json()
    data["signature"] = body.get("signature", [])
    screen_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return JSONResponse({"ok": True, "screen": screen_id, "points": len(data["signature"])})

@app.get("/api/screens/signatures")
async def get_screen_signatures():
    """Get all screen signatures for client-side auto-detection."""
    if not active_game_name:
        return JSONResponse({"signatures": {}})
    screens_dir = GAMES_DIR / active_game_name / "screens"
    if not screens_dir.exists():
        return JSONResponse({"signatures": {}})
    sigs = {}
    for f in sorted(screens_dir.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("signature"):
            sigs[f.stem] = {
                "description": data.get("description", f.stem),
                "signature": data["signature"],
            }
    return JSONResponse({"signatures": sigs})

# --- Screen State & Log (AI writes, WebUI reads) ---
from collections import deque
screen_state = {}  # { box_id: { "value": "フシギダネ", "updated": timestamp } }
screen_log = deque(maxlen=100)  # last 100 entries

@app.get("/api/screen/state")
async def get_screen_state():
    return JSONResponse({"state": screen_state, "screen": active_screen})

@app.post("/api/screen/state")
async def set_screen_state(request: Request):
    """AI posts read values for each box. Example: {"enemy_name": "フシギダネ", "enemy_hp": "20/20"}"""
    data = await request.json()
    ts = time.time()
    for box_id, value in data.items():
        old_value = screen_state.get(box_id, {}).get("value")
        screen_state[box_id] = {"value": value, "updated": ts}
        if old_value != value:
            screen_log.append({"time": ts, "box": box_id, "old": old_value, "new": value})
    return JSONResponse({"ok": True, "updated": list(data.keys())})

@app.get("/api/screen/log")
async def get_screen_log():
    return JSONResponse({"log": list(screen_log), "count": len(screen_log)})

@app.post("/api/screen/log/clear")
async def clear_screen_log():
    screen_log.clear()
    return JSONResponse({"ok": True})

# --- Input API (AI/programmatic control) ---
# Button name mapping (same as frontend BTN)
INPUT_BTN = {
    "y": (0, 1<<0), "b": (0, 1<<1), "a": (0, 1<<2), "x": (0, 1<<3),
    "l": (0, 1<<4), "r": (0, 1<<5), "zl": (0, 1<<6), "zr": (0, 1<<7),
    "minus": (1, 1<<0), "plus": (1, 1<<1), "lstick": (1, 1<<2),
    "rstick": (1, 1<<3), "home": (1, 1<<4), "capture": (1, 1<<5),
}
INPUT_HAT = {"up":0, "upright":1, "right":2, "downright":3, "down":4, "downleft":5, "left":6, "upleft":7}

# Persistent API input state (OR'd with WS input)
api_btn0 = 0
api_btn1 = 0
api_hat = HAT_NEUTRAL
api_lx = CENTER
api_ly = CENTER
api_rx = CENTER
api_ry = CENTER

@app.post("/api/input/press")
async def input_press(request: Request):
    """Press button(s) for min_frames duration. buttons: ["a"], ["up","a"], duration_ms: optional override"""
    global api_btn0, api_btn1, api_hat
    data = await request.json()
    buttons = data.get("buttons", [])
    duration_ms = data.get("duration_ms", input_min_ms)

    btn0 = 0; btn1 = 0; hat = HAT_NEUTRAL
    for b in buttons:
        b = b.lower()
        if b in INPUT_BTN:
            byte_idx, bit = INPUT_BTN[b]
            if byte_idx == 0: btn0 |= bit
            else: btn1 |= bit
        elif b in INPUT_HAT:
            hat = INPUT_HAT[b]

    # Set state
    api_btn0 |= btn0; api_btn1 |= btn1
    if hat != HAT_NEUTRAL: api_hat = hat
    send_report(api_btn0 | macro_btn0, api_btn1 | macro_btn1,
                api_hat if api_hat != HAT_NEUTRAL else macro_hat,
                api_lx, api_ly, api_rx, api_ry)

    # Hold for duration
    await asyncio.sleep(duration_ms / 1000.0)

    # Release
    api_btn0 &= ~btn0; api_btn1 &= ~btn1
    if hat != HAT_NEUTRAL: api_hat = HAT_NEUTRAL
    send_report(api_btn0 | macro_btn0, api_btn1 | macro_btn1,
                api_hat if api_hat != HAT_NEUTRAL else macro_hat,
                api_lx, api_ly, api_rx, api_ry)

    return JSONResponse({"ok": True, "buttons": buttons, "duration_ms": duration_ms})

@app.post("/api/input/hold")
async def input_hold(request: Request):
    """Hold button(s) until released"""
    global api_btn0, api_btn1, api_hat
    data = await request.json()
    buttons = data.get("buttons", [])
    for b in buttons:
        b = b.lower()
        if b in INPUT_BTN:
            byte_idx, bit = INPUT_BTN[b]
            if byte_idx == 0: api_btn0 |= bit
            else: api_btn1 |= bit
        elif b in INPUT_HAT:
            api_hat = INPUT_HAT[b]
    send_report(api_btn0 | macro_btn0, api_btn1 | macro_btn1,
                api_hat if api_hat != HAT_NEUTRAL else macro_hat,
                api_lx, api_ly, api_rx, api_ry)
    return JSONResponse({"ok": True, "holding": buttons})

@app.post("/api/input/release")
async def input_release(request: Request):
    """Release button(s)"""
    global api_btn0, api_btn1, api_hat
    data = await request.json()
    buttons = data.get("buttons", data.get("all", []))
    if buttons == "all" or data.get("all"):
        api_btn0 = api_btn1 = 0; api_hat = HAT_NEUTRAL
    else:
        for b in buttons:
            b = b.lower()
            if b in INPUT_BTN:
                byte_idx, bit = INPUT_BTN[b]
                if byte_idx == 0: api_btn0 &= ~bit
                else: api_btn1 &= ~bit
            elif b in INPUT_HAT:
                api_hat = HAT_NEUTRAL
    send_report(api_btn0 | macro_btn0, api_btn1 | macro_btn1,
                api_hat if api_hat != HAT_NEUTRAL else macro_hat,
                api_lx, api_ly, api_rx, api_ry)
    return JSONResponse({"ok": True})

@app.post("/api/input/stick")
async def input_stick(request: Request):
    """Set analog stick. stick: "l"/"r", x: -1.0~1.0, y: -1.0~1.0"""
    global api_lx, api_ly, api_rx, api_ry
    data = await request.json()
    stick = data.get("stick", "l")
    x = max(-1, min(1, data.get("x", 0)))
    y = max(-1, min(1, data.get("y", 0)))
    val_x = round(128 + x * 127)
    val_y = round(128 + y * 127)
    if stick == "l":
        api_lx, api_ly = val_x, val_y
    else:
        api_rx, api_ry = val_x, val_y
    send_report(api_btn0 | macro_btn0, api_btn1 | macro_btn1,
                api_hat if api_hat != HAT_NEUTRAL else macro_hat,
                api_lx, api_ly, api_rx, api_ry)
    return JSONResponse({"ok": True, "stick": stick, "x": x, "y": y})

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            cmd = msg.get("cmd")

            if cmd == "report":
                global last_ws_report
                last_ws_report = time.time()
                u_btn0 = msg.get("btn0", 0)
                u_btn1 = msg.get("btn1", 0)
                u_hat = msg.get("hat", HAT_NEUTRAL)
                u_lx = msg.get("lx", CENTER)
                u_ly = msg.get("ly", CENTER)
                u_rx = msg.get("rx", CENTER)
                u_ry = msg.get("ry", CENTER)
                send_report(
                    btn0=u_btn0 | macro_btn0 | api_btn0,
                    btn1=u_btn1 | macro_btn1 | api_btn1,
                    hat=u_hat if u_hat != HAT_NEUTRAL else (api_hat if api_hat != HAT_NEUTRAL else macro_hat),
                    lx=u_lx if u_lx != CENTER else (api_lx if api_lx != CENTER else macro_lx),
                    ly=u_ly if u_ly != CENTER else (api_ly if api_ly != CENTER else macro_ly),
                    rx=u_rx if u_rx != CENTER else (api_rx if api_rx != CENTER else macro_rx),
                    ry=u_ry if u_ry != CENTER else (api_ry if api_ry != CENTER else macro_ry),
                )
                await ws.send_text(json.dumps({"ok": True, "macro": macro_running}))

            elif cmd == "status":
                await ws.send_text(json.dumps({
                    "connected": ser is not None and ser.is_open,
                    "port": PORT, "macro_running": macro_running,
                }))

    except WebSocketDisconnect:
        pass

# --- Keepalive ---
async def keepalive():
    while True:
        if time.time() - last_ws_report > 2.0:
            send_report(macro_btn0, macro_btn1, macro_hat,
                        macro_lx, macro_ly, macro_rx, macro_ry)
        await asyncio.sleep(0.05)

@app.on_event("startup")
async def startup():
    serial_connect()
    asyncio.create_task(keepalive())

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Switch 2 Browser on http://localhost:8765")
    print(f"Serial port: {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")
