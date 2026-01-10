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
    ErdCode.LAUNDRY_WASHER_SMART_DISPENSE_ADJUSTABILITY_OPTION,
    ErdCode.LAUNDRY_WASHER_LINK_DATA,
    ErdCode.LAUNDRY_WASHER_DOOR_LOCK,
    ErdCode.LAUNDRY_WASHER_POWERSTEAM,
    ErdCode.LAUNDRY_WASHER_PREWASH,
    ErdCode.LAUNDRY_WASHER_TIMESAVER,
]

DRYER_ERDS = [
    ErdCode.LAUNDRY_DRYER_TEMPERATURENEW_OPTION,
    ErdCode.LAUNDRY_DRYER_DRYNESSNEW_LEVEL,
    ErdCode.LAUNDRY_DRYER_ECODRY_OPTION_SELECTION,
    ErdCode.LAUNDRY_DRYER_EXTENDED_TUMBLE_OPTION_SELECTION,
    ErdCode.LAUNDRY_DRYER_SHEET_INVENTORY,
    ErdCode.LAUNDRY_DRYER_WASHERLINK_STATUS,
    ErdCode.LAUNDRY_DRYER_DAMP_ALERT_STATUS,
    # Allowables (what can be controlled)
    ErdCode.LAUNDRY_DRYER_TEMPERATURE_OPTION_ALLOWABLES,
    ErdCode.LAUNDRY_DRYER_DRYNESS_OPTION_ALLOWABLES,
    ErdCode.LAUNDRY_DRYER_ECODRY_OPTION_ALLOWABLES,
    ErdCode.LAUNDRY_DRYER_EXTENDED_TUMBLE_OPTION_ALLOWABLES,
    ErdCode.LAUNDRY_DRYER_DAMP_ALERT_OPTION_ALLOWABLES,
    ErdCode.LAUNDRY_DRYER_SHEET_USAGE_CONFIGURATION,
    ErdCode.LAUNDRY_DRYER_WASHERLINK_CONTROL,
    ErdCode.LAUNDRY_DRYER_RECOMMENDED_WASHERLINK_CYCLE,
    ErdCode.LAUNDRY_DRYER_BLOCKED_VENT_FAULT,
]


def parse_complex_value(value, erd_name):
    """Parse complex ERD values into structured data"""
    value_str = str(value)

    # Smart Dispense - extract loads_left and signal (tank percentage)
    if 'ErdSmartDispense' in value_str:
        import re
        loads_match = re.search(r'loads_left=(\d+)', value_str)
        signal_match = re.search(r'signal=(\d+)', value_str)
        loads = loads_match.group(1) if loads_match else '?'
        signal = signal_match.group(1) if signal_match else '?'
        return {"display": f"{loads} loads left ({signal}%)", "loads_left": loads, "tank_percent": signal}

    # EcoDry Selection - just show enabled/disabled
    if 'ErdEcoDryOptionSelection' in value_str:
        return {"display": "Enabled" if 'ENABLED' in value_str else "Disabled"}

    # Sheet Usage Configuration - format nicely
    if 'ErdSheetUsageConfiguration' in value_str:
        import re
        s = re.search(r'small_load_size=(\d+)', value_str)
        m = re.search(r'medium_load_size=(\d+)', value_str)
        l = re.search(r'large_load_size=(\d+)', value_str)
        xl = re.search(r'extra_large_load_size=(\d+)', value_str)
        return {
            "display": f"S:{s.group(1) if s else '?'} M:{m.group(1) if m else '?'} L:{l.group(1) if l else '?'} XL:{xl.group(1) if xl else '?'}",
            "small": s.group(1) if s else 0,
            "medium": m.group(1) if m else 0,
            "large": l.group(1) if l else 0,
            "xl": xl.group(1) if xl else 0
        }

    # WasherLink Data - extract useful stats
    if 'ErdWasherLinkData' in value_str:
        import re
        count = re.search(r'washer_cycle_count=(\d+)', value_str)
        extraction = re.search(r'water_extraction_level_index=(\d+)', value_str)
        load_size = re.search(r'washer_load_size_index=(\d+)', value_str)
        cycle_type = re.search(r'base_cycle_type=<BaseCycleType\.(\w+)', value_str)
        return {
            "display": f"Cycles: {count.group(1) if count else '?'}",
            "cycle_count": count.group(1) if count else 0,
            "extraction_level": extraction.group(1) if extraction else 0,
            "load_size_index": load_size.group(1) if load_size else 0,
            "base_cycle": cycle_type.group(1) if cycle_type else "Unknown"
        }

    # Smart Dispense Adjustability
    if 'ErdSmartDispenseAdjustabilityOption' in value_str:
        import re
        dosage = re.search(r'dosage=<ErdSmartDispenseDosageType\.(\w+)', value_str)
        return {"display": f"Dosage: {dosage.group(1).title() if dosage else 'Auto'}"}

    # Allowables - parse what options are allowed (for controls)
    if 'Allowables' in value_str:
        import re
        # Find all "name=True" or "name_allowed=True" patterns
        allowed = re.findall(r'(\w+)(?:_allowed)?=True', value_str)
        if allowed:
            # Clean up names
            clean = [a.replace('_', ' ').title() for a in allowed if 'raw' not in a.lower()]
            return {"display": ", ".join(clean) if clean else "None", "options": clean}
        return {"display": "None", "options": []}

    # Raw bytes - show as hex or "inactive"
    if value_str.startswith("b'"):
        if value_str == "b'\\x00\\x00'" or value_str == "b'\\x00'":
            return {"display": "Inactive"}
        return {"display": "Active"}

    return None


def stringify_value(appliance, erd_code, value):
    """Convert ERD value to display string"""
    if value is None:
        return "N/A"

    # Try our custom parser first
    erd_name = erd_code.name if hasattr(erd_code, 'name') else str(erd_code)
    parsed = parse_complex_value(value, erd_name)
    if parsed:
        return parsed.get("display", str(value))

    try:
        result = appliance.stringify_erd_value(value)
        if result:
            return str(result)
        return str(value)
    except:
        return str(value)


def get_appliance_state(appliance):
    """Extract all relevant state from an appliance"""
    import re
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
        "properties": {},
        "controls": {},  # What options can be set
        "stats": {}      # Lifetime statistics
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

    # Extract controls (what can be set) from allowables
    props = state["properties"]

    if is_dryer:
        # Temperature control
        if "LAUNDRY_DRYER_TEMPERATURE_OPTION_ALLOWABLES" in props:
            raw = props["LAUNDRY_DRYER_TEMPERATURE_OPTION_ALLOWABLES"]["raw"]
            options = []
            if "low_allowed=True" in raw: options.append("Low")
            if "medium_allowed=True" in raw: options.append("Medium")
            if "high_allowed=True" in raw: options.append("High")
            if "noheat_allowed=True" in raw: options.append("No Heat")
            if "extralow_allowed=True" in raw: options.append("Extra Low")
            current = props.get("LAUNDRY_DRYER_TEMPERATURENEW_OPTION", {}).get("display", "")
            if options:
                state["controls"]["temperature"] = {"current": current, "options": options}

        # Dryness control
        if "LAUNDRY_DRYER_DRYNESS_OPTION_ALLOWABLES" in props:
            raw = props["LAUNDRY_DRYER_DRYNESS_OPTION_ALLOWABLES"]["raw"]
            options = []
            if "damp_allowed=True" in raw: options.append("Damp")
            if "lessdry_allowed=True" in raw: options.append("Less Dry")
            if "dry_allowed=True" in raw: options.append("Dry")
            if "moredry_allowed=True" in raw: options.append("More Dry")
            if "extradry_allowed=True" in raw: options.append("Extra Dry")
            current = props.get("LAUNDRY_DRYER_DRYNESSNEW_LEVEL", {}).get("display", "")
            if options:
                state["controls"]["dryness"] = {"current": current, "options": options}

        # EcoDry control
        if "LAUNDRY_DRYER_ECODRY_OPTION_ALLOWABLES" in props:
            raw = props["LAUNDRY_DRYER_ECODRY_OPTION_ALLOWABLES"]["raw"]
            can_enable = "enable_allowed=True" in raw
            can_disable = "disable_allowed=True" in raw
            current = props.get("LAUNDRY_DRYER_ECODRY_OPTION_SELECTION", {}).get("display", "")
            if can_enable or can_disable:
                state["controls"]["ecodry"] = {"current": current, "can_toggle": can_enable and can_disable}

        # Extended Tumble
        if "LAUNDRY_DRYER_EXTENDED_TUMBLE_OPTION_ALLOWABLES" in props:
            raw = props["LAUNDRY_DRYER_EXTENDED_TUMBLE_OPTION_ALLOWABLES"]["raw"]
            can_enable = "enable_allowed=True" in raw
            current = props.get("LAUNDRY_DRYER_EXTENDED_TUMBLE_OPTION_SELECTION", {}).get("display", "")
            if can_enable:
                state["controls"]["extended_tumble"] = {"current": current, "available": True}

        # Damp Alert
        if "LAUNDRY_DRYER_DAMP_ALERT_OPTION_ALLOWABLES" in props:
            raw = props["LAUNDRY_DRYER_DAMP_ALERT_OPTION_ALLOWABLES"]["raw"]
            can_toggle = "enable_allowed=True" in raw and "disable_allowed=True" in raw
            current = props.get("LAUNDRY_DRYER_DAMP_ALERT_OPTION_SELECTION", {}).get("display", "")
            if can_toggle:
                state["controls"]["damp_alert"] = {"current": current, "can_toggle": True}

    # Extract stats
    if "LAUNDRY_WASHER_LINK_DATA" in props:
        raw = props["LAUNDRY_WASHER_LINK_DATA"]["raw"]
        cycle_match = re.search(r'washer_cycle_count=(\d+)', raw)
        if cycle_match:
            state["stats"]["total_cycles"] = int(cycle_match.group(1))

    # Remote control status
    remote_status = props.get("LAUNDRY_REMOTE_STATUS", {}).get("display", "False")
    state["remote_enabled"] = remote_status == "True"

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
