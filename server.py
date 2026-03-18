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
                    btn0=u_btn0 | macro_btn0,
                    btn1=u_btn1 | macro_btn1,
                    hat=u_hat if u_hat != HAT_NEUTRAL else macro_hat,
                    lx=u_lx if u_lx != CENTER else macro_lx,
                    ly=u_ly if u_ly != CENTER else macro_ly,
                    rx=u_rx if u_rx != CENTER else macro_rx,
                    ry=u_ry if u_ry != CENTER else macro_ry,
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
        if not macro_running and (time.time() - last_ws_report > 2.0):
            send_report()
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
