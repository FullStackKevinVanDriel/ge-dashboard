#!/usr/bin/env python3
"""
GE Appliances Dashboard - Real-time monitoring for washer and dryer
"""

import asyncio
import json
import queue
import threading
import time
from datetime import datetime
from flask import Flask, render_template, Response, jsonify
import aiohttp

from gehomesdk import (
    GeWebsocketClient,
    ErdCode,
    ErdCodeType,
    EVENT_ADD_APPLIANCE,
    EVENT_APPLIANCE_STATE_CHANGE,
    EVENT_APPLIANCE_AVAILABLE,
    EVENT_APPLIANCE_UNAVAILABLE,
    EVENT_CONNECTED,
    EVENT_DISCONNECTED,
)

# Configuration
SMARTHQ_EMAIL = "delynn.vandriel@gmail.com"
SMARTHQ_PASSWORD = "Family2021!!"
SMARTHQ_REGION = "US"

app = Flask(__name__)

# Global state
appliance_data = {}
connection_status = {"connected": False, "last_update": None}
update_queue = queue.Queue()

# ERD codes we want to track for each appliance type
COMMON_ERDS = [
    ErdCode.MODEL_NUMBER,
    ErdCode.SERIAL_NUMBER,
    ErdCode.APPLIANCE_TYPE,
    ErdCode.LAUNDRY_MACHINE_STATE,
    ErdCode.LAUNDRY_SUB_CYCLE,
    ErdCode.LAUNDRY_CYCLE,
    ErdCode.LAUNDRY_TIME_REMAINING,
    ErdCode.LAUNDRY_DOOR,
    ErdCode.LAUNDRY_REMOTE_STATUS,
]

WASHER_ERDS = [
    ErdCode.LAUNDRY_WASHER_SOIL_LEVEL,
    ErdCode.LAUNDRY_WASHER_WASHTEMP_LEVEL,
    ErdCode.LAUNDRY_WASHER_RINSE_OPTION,
    ErdCode.LAUNDRY_WASHER_SPINTIME_LEVEL,
    ErdCode.LAUNDRY_WASHER_TANK_STATUS,
    ErdCode.LAUNDRY_WASHER_TANK_SELECTED,
    ErdCode.LAUNDRY_WASHER_SMART_DISPENSE,
    ErdCode.LAUNDRY_WASHER_SMART_DISPENSE_TANK_STATUS,
]

DRYER_ERDS = [
    ErdCode.LAUNDRY_DRYER_TEMPERATURENEW_OPTION,
    ErdCode.LAUNDRY_DRYER_DRYNESSNEW_LEVEL,
    ErdCode.LAUNDRY_DRYER_ECODRY_OPTION_SELECTION,
    ErdCode.LAUNDRY_DRYER_EXTENDED_TUMBLE_OPTION_SELECTION,
    ErdCode.LAUNDRY_DRYER_SHEET_INVENTORY,
    ErdCode.LAUNDRY_DRYER_WASHERLINK_STATUS,
    ErdCode.LAUNDRY_DRYER_DAMP_ALERT_STATUS,
]


def stringify_value(appliance, erd_code, value):
    """Convert ERD value to display string"""
    if value is None:
        return "N/A"
    try:
        result = appliance.stringify_erd_value(value)
        if result:
            return str(result)
        return str(value)
    except:
        return str(value)


def get_appliance_state(appliance):
    """Extract all relevant state from an appliance"""
    mac = appliance.mac_addr

    # Determine appliance type (handle missing data gracefully)
    try:
        app_type = appliance.get_erd_value(ErdCode.APPLIANCE_TYPE)
    except (KeyError, AttributeError):
        app_type = None

    app_type_str = stringify_value(appliance, ErdCode.APPLIANCE_TYPE, app_type)
    is_dryer = "DRYER" in str(app_type_str).upper()
    is_washer = "WASHER" in str(app_type_str).upper()

    state = {
        "mac": mac,
        "type": "dryer" if is_dryer else "washer" if is_washer else "unknown",
        "type_display": app_type_str,
        "available": appliance.available,
        "last_update": datetime.now().isoformat(),
        "properties": {}
    }

    # Get common properties
    erds_to_check = COMMON_ERDS.copy()
    if is_dryer:
        erds_to_check.extend(DRYER_ERDS)
    elif is_washer:
        erds_to_check.extend(WASHER_ERDS)

    for erd_code in erds_to_check:
        try:
            value = appliance.get_erd_value(erd_code)
            if value is not None:
                state["properties"][erd_code.name] = {
                    "raw": str(value),
                    "display": stringify_value(appliance, erd_code, value)
                }
        except (KeyError, AttributeError, Exception):
            pass

    # Also get any other known properties (known_properties is a set of keys)
    for erd_code in appliance.known_properties:
        if isinstance(erd_code, ErdCode):
            erd_name = erd_code.name
        else:
            erd_name = str(erd_code)

        if erd_name not in state["properties"]:
            try:
                value = appliance.get_erd_value(erd_code)
                state["properties"][erd_name] = {
                    "raw": str(value),
                    "display": stringify_value(appliance, erd_code, value)
                }
            except (KeyError, AttributeError, Exception):
                pass

    return state


async def on_appliance_added(appliance):
    """Handle new appliance discovery"""
    mac = appliance.mac_addr
    print(f"[+] Appliance added: {mac}")
    appliance_data[mac] = get_appliance_state(appliance)
    update_queue.put({"event": "appliance_added", "mac": mac, "data": appliance_data[mac]})


async def on_state_change(data):
    """Handle appliance state updates"""
    appliance, state_changes = data
    mac = appliance.mac_addr
    print(f"[~] State change for {mac}: {len(state_changes)} properties")

    # Update our cached state
    appliance_data[mac] = get_appliance_state(appliance)

    # Build change summary for frontend
    changes = {}
    for erd_code, value in state_changes.items():
        if isinstance(erd_code, ErdCode):
            erd_name = erd_code.name
        else:
            erd_name = str(erd_code)
        changes[erd_name] = stringify_value(appliance, erd_code, value)

    update_queue.put({
        "event": "state_change",
        "mac": mac,
        "changes": changes,
        "data": appliance_data[mac]
    })


async def on_appliance_available(appliance):
    """Handle appliance coming online"""
    mac = appliance.mac_addr
    print(f"[+] Appliance available: {mac}")
    if mac in appliance_data:
        appliance_data[mac]["available"] = True
    update_queue.put({"event": "available", "mac": mac})


async def on_appliance_unavailable(appliance):
    """Handle appliance going offline"""
    mac = appliance.mac_addr
    print(f"[-] Appliance unavailable: {mac}")
    if mac in appliance_data:
        appliance_data[mac]["available"] = False
    update_queue.put({"event": "unavailable", "mac": mac})


async def on_connected(_=None):
    """Handle successful connection to SmartHQ"""
    print("[+] Connected to GE SmartHQ")
    connection_status["connected"] = True
    connection_status["last_update"] = datetime.now().isoformat()
    update_queue.put({"event": "connected"})


async def on_disconnected(_=None):
    """Handle disconnection from SmartHQ"""
    print("[-] Disconnected from GE SmartHQ")
    connection_status["connected"] = False
    update_queue.put({"event": "disconnected"})


async def run_ge_client():
    """Main async loop for GE SDK client"""
    client = GeWebsocketClient(
        username=SMARTHQ_EMAIL,
        password=SMARTHQ_PASSWORD,
        region=SMARTHQ_REGION
    )

    # Register event handlers
    client.add_event_handler(EVENT_ADD_APPLIANCE, on_appliance_added)
    client.add_event_handler(EVENT_APPLIANCE_STATE_CHANGE, on_state_change)
    client.add_event_handler(EVENT_APPLIANCE_AVAILABLE, on_appliance_available)
    client.add_event_handler(EVENT_APPLIANCE_UNAVAILABLE, on_appliance_unavailable)
    client.add_event_handler(EVENT_CONNECTED, on_connected)
    client.add_event_handler(EVENT_DISCONNECTED, on_disconnected)

    print("[*] Connecting to GE SmartHQ...")

    async with aiohttp.ClientSession() as session:
        await client.async_get_credentials_and_run(session)


def start_ge_client_thread():
    """Start the GE client in a background thread"""
    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_ge_client())
        except Exception as e:
            print(f"[!] GE Client error: {e}")
            connection_status["connected"] = False
            update_queue.put({"event": "error", "message": str(e)})

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


# Flask Routes

@app.route("/")
def index():
    """Serve the main dashboard page"""
    return render_template("dashboard.html")


@app.route("/api/appliances")
def api_appliances():
    """Get current state of all appliances"""
    return jsonify({
        "connection": connection_status,
        "appliances": appliance_data
    })


@app.route("/stream")
def stream():
    """Server-Sent Events endpoint for real-time updates"""
    def generate():
        # Send initial state
        yield f"data: {json.dumps({'event': 'init', 'connection': connection_status, 'appliances': appliance_data})}\n\n"

        while True:
            try:
                # Wait for updates with timeout
                update = update_queue.get(timeout=30)
                yield f"data: {json.dumps(update)}\n\n"
            except queue.Empty:
                # Send keepalive
                yield f"data: {json.dumps({'event': 'keepalive'})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


if __name__ == "__main__":
    print("=" * 50)
    print("GE Appliances Dashboard")
    print("=" * 50)

    # Start GE client in background
    start_ge_client_thread()

    # Give it a moment to connect
    time.sleep(2)

    # Start Flask server
    print("[*] Starting web server on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
