import asyncio
import json
import os
import time

from mcp.server.fastmcp import FastMCP

from siglent_spd_mcp.scpi_connection import SCPIConnection

mcp = FastMCP("siglent-spd")
conn: SCPIConnection | None = None


def _get_conn() -> SCPIConnection:
    global conn
    if conn is None:
        host = os.environ["SPD_HOST"]
        port = int(os.environ.get("SPD_PORT", "5025"))
        conn = SCPIConnection(host, port)
    return conn


# Background monitor state
_monitors: dict = {}
_monitor_counter = 0


# ---------------------------------------------------------------------------
# Permissions
#
# Environment variables (all optional, default: readonly):
#   CH1_PERM       — readwrite | readonly
#   CH2_PERM       — readwrite | readonly
#   CH3_PERM       — readwrite | readonly   (any discovered channel gets one)
#   NETWORK_PERM   — readwrite | readonly
#   MEMORY_PERM    — readwrite | readonly
#
# readonly  = queries/measurements allowed, changes blocked (default)
# readwrite = full access
# ---------------------------------------------------------------------------


def _get_perm(category: str) -> str:
    val = os.environ.get(f"{category}_PERM", "readonly").lower()
    return val if val in ("readwrite", "readonly") else "readonly"


def _require_write(category: str) -> str | None:
    """Return error string if write access is denied, else None."""
    if _get_perm(category) == "readonly":
        return f"DENIED: {category} is read-only"
    return None


# ---------------------------------------------------------------------------
# Safety limits
#
# Environment variables (all optional, per-channel):
#   CH1_MAX_VOLTAGE    — voltage limit for CH1 (V)
#   CH1_MAX_CURRENT    — current limit for CH1 (A)
#   CH2_MAX_VOLTAGE    — voltage limit for CH2 (V)
#   CH2_MAX_CURRENT    — current limit for CH2 (A)
# ---------------------------------------------------------------------------


def _get_limit(channel: str, param: str) -> float | None:
    """Get the safety limit for a channel."""
    val = os.environ.get(f"{channel.upper()}_MAX_{param}")
    if val is not None:
        return float(val)
    return None


def _check_voltage(channel: str, voltage: float) -> str | None:
    """Return error string if voltage exceeds limit, else None."""
    limit = _get_limit(channel, "VOLTAGE")
    if limit is not None and voltage > limit:
        return f"SAFETY: {voltage}V exceeds {channel} limit of {limit}V"
    return None


def _check_current(channel: str, current: float) -> str | None:
    """Return error string if current exceeds limit, else None."""
    limit = _get_limit(channel, "CURRENT")
    if limit is not None and current > limit:
        return f"SAFETY: {current}A exceeds {channel} limit of {limit}A"
    return None


def _check_both(channel: str, voltage: float, current: float) -> list[str]:
    """Check voltage and current, return list of violation strings."""
    errors = []
    v_err = _check_voltage(channel, voltage)
    if v_err:
        errors.append(v_err)
    i_err = _check_current(channel, current)
    if i_err:
        errors.append(i_err)
    return errors


async def _query_and_check_channel(channel: str) -> list[str]:
    """Query a channel's setpoints and return any limit violations."""
    v = float(await _get_conn().query(f"{channel}:VOLTage?"))
    i = float(await _get_conn().query(f"{channel}:CURRent?"))
    return _check_both(channel, v, i)


@mcp.tool()
async def get_safety_config() -> str:
    """Show configured permissions and safety limits."""
    config: dict = {}

    # Collect all configured permissions and limits from env vars
    perms = {}
    limits = {}
    for key, val in os.environ.items():
        if key.endswith("_PERM"):
            perms[key.removesuffix("_PERM")] = val.lower()
        elif "_MAX_VOLTAGE" in key:
            ch = key.removesuffix("_MAX_VOLTAGE")
            limits.setdefault(ch, {})["max_voltage"] = float(val)
        elif "_MAX_CURRENT" in key:
            ch = key.removesuffix("_MAX_CURRENT")
            limits.setdefault(ch, {})["max_current"] = float(val)

    config["permissions"] = perms if perms else "all default (readonly)"
    config["safety_limits"] = limits if limits else "none configured"

    return json.dumps(config)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@mcp.tool()
async def identify() -> str:
    """Query instrument identification (manufacturer, model, serial, firmware, hardware version)."""

    return await _get_conn().query("*IDN?")


# ---------------------------------------------------------------------------
# Save / Recall
# ---------------------------------------------------------------------------


@mcp.tool()
async def save_state(slot: int) -> str:
    """Save current instrument state to nonvolatile memory (slot 1-5). Requires MEMORY write permission."""

    err = _require_write("MEMORY")
    if err:
        return err
    if slot < 1 or slot > 5:
        return "Error: slot must be 1-5"
    await _get_conn().write(f"*SAV {slot}")
    return f"State saved to slot {slot}"


@mcp.tool()
async def recall_state(slot: int) -> str:
    """Recall instrument state from nonvolatile memory (slot 1-5). Requires MEMORY write permission
    because recall activates the stored values (changes device voltage, current, output state).

    After recall, checks all channel setpoints against safety limits.
    If any channel violates a limit, its output is disabled immediately.
    """

    err = _require_write("MEMORY")
    if err:
        return err
    if slot < 1 or slot > 5:
        return "Error: slot must be 1-5"
    await _get_conn().write(f"*RCL {slot}")
    await asyncio.sleep(0.5)

    # Check channels that have safety limits configured
    limit_channels = set()
    for key in os.environ:
        if key.endswith("_MAX_VOLTAGE") or key.endswith("_MAX_CURRENT"):
            limit_channels.add(key.split("_MAX_")[0])

    warnings = []
    for ch in sorted(limit_channels):
        try:
            errors = await _query_and_check_channel(ch)
        except Exception:
            continue  # channel may not support setpoint queries
        if errors:
            await _get_conn().write(f"OUTPut {ch},OFF")
            await asyncio.sleep(0.1)
            warnings.append(f"{ch} output DISABLED: {'; '.join(errors)}")

    msg = f"State recalled from slot {slot}"
    if warnings:
        msg += "\nSAFETY ACTIONS:\n" + "\n".join(warnings)
    return msg


# ---------------------------------------------------------------------------
# Measure (actual readings)# ---------------------------------------------------------------------------


@mcp.tool()
async def measure_voltage(channel: str = "CH1") -> str:
    """Measure actual output voltage on a channel."""

    ch = channel.upper()

    return await _get_conn().query(f"MEASure:VOLTage? {ch}")


@mcp.tool()
async def measure_current(channel: str = "CH1") -> str:
    """Measure actual output current on a channel."""

    ch = channel.upper()

    return await _get_conn().query(f"MEASure:CURRent? {ch}")


@mcp.tool()
async def measure_power(channel: str = "CH1") -> str:
    """Measure actual output power on a channel."""

    ch = channel.upper()

    return await _get_conn().query(f"MEASure:POWEr? {ch}")


@mcp.tool()
async def measure_all(channel: str = "CH1") -> str:
    """Measure voltage, current, and power on a channel in one call."""

    ch = channel.upper()

    v = await _get_conn().query(f"MEASure:VOLTage? {ch}")
    i = await _get_conn().query(f"MEASure:CURRent? {ch}")
    p = await _get_conn().query(f"MEASure:POWEr? {ch}")
    return json.dumps({"channel": ch, "voltage": v, "current": i, "power": p})


# ---------------------------------------------------------------------------
# Voltage setpoint# ---------------------------------------------------------------------------


@mcp.tool()
async def set_voltage(channel: str, voltage: float) -> str:
    """Set voltage setpoint for a channel (e.g. channel=CH1, voltage=3.3).

    Requires channel write permission. Blocked if the value exceeds the safety limit.
    """

    ch = channel.upper()

    err = _require_write(ch)
    if err:
        return err
    err = _check_voltage(ch, voltage)
    if err:
        return f"REFUSED: {err}"
    await _get_conn().write(f"{ch}:VOLTage {voltage}")
    return f"Set {ch} voltage to {voltage} V"


@mcp.tool()
async def get_voltage(channel: str = "CH1") -> str:
    """Query the voltage setpoint for a channel."""

    ch = channel.upper()

    return await _get_conn().query(f"{ch}:VOLTage?")


# ---------------------------------------------------------------------------
# Current setpoint# ---------------------------------------------------------------------------


@mcp.tool()
async def set_current(channel: str, current: float) -> str:
    """Set current limit for a channel (e.g. channel=CH1, current=0.5).

    Requires channel write permission. Blocked if the value exceeds the safety limit.
    """

    ch = channel.upper()

    err = _require_write(ch)
    if err:
        return err
    err = _check_current(ch, current)
    if err:
        return f"REFUSED: {err}"
    await _get_conn().write(f"{ch}:CURRent {current}")
    return f"Set {ch} current to {current} A"


@mcp.tool()
async def get_current(channel: str = "CH1") -> str:
    """Query the current setpoint for a channel."""

    ch = channel.upper()

    return await _get_conn().query(f"{ch}:CURRent?")


# ---------------------------------------------------------------------------
# Output control — all channels (full + output-only)
# ---------------------------------------------------------------------------


@mcp.tool()
async def set_output(channel: str, state: str) -> str:
    """Turn channel output on or off (state: ON/OFF).

    Requires channel write permission. For full channels, enabling (ON) also
    checks voltage and current setpoints against safety limits.
    """

    ch = channel.upper()
    st = state.upper()
    if st not in ("ON", "OFF"):
        return "Error: state must be ON or OFF"

    err = _require_write(ch)
    if err:
        return err

    if st == "ON":
        try:
            errors = await _query_and_check_channel(ch)
            if errors:
                return f"REFUSED to enable {ch}: {'; '.join(errors)}"
        except Exception:
            pass  # channel may not support setpoint queries (e.g. output-only)

    await _get_conn().write(f"OUTPut {ch},{st}")

    if st == "ON":
        try:
            conn = _get_conn()
            voltage = await conn.query(f"MEASure:VOLTage? {ch}")
            current = await conn.query(f"MEASure:CURRent? {ch}")
            raw = await conn.query("SYSTem:STATus?")
            mode = "unknown"
            try:
                val = int(raw, 16)
                bit = {"CH1": 0x01, "CH2": 0x02}.get(ch)
                if bit is not None:
                    mode = "CC" if val & bit else "CV"
            except ValueError:
                pass
            result = {
                "channel": ch,
                "output": "ON",
                "voltage": voltage,
                "current": current,
                "mode": mode,
            }
            return json.dumps(result)
        except Exception:
            return f"{ch} output ON"

    return f"{ch} output {st}"


@mcp.tool()
async def set_tracking_mode(mode: int) -> str:
    """Set output tracking mode: 0=independent, 1=series, 2=parallel.

    Requires write permission on CH1 and CH2 (affects both).
    """
    for ch in ("CH1", "CH2"):
        err = _require_write(ch)
        if err:
            return err
    if mode not in (0, 1, 2):
        return "Error: mode must be 0 (independent), 1 (series), or 2 (parallel)"
    await _get_conn().write(f"OUTPut:TRACK {mode}")
    labels = {0: "independent", 1: "series", 2: "parallel"}
    return f"Tracking mode set to {labels[mode]}"


@mcp.tool()
async def set_waveform_display(channel: str, state: str) -> str:
    """Turn waveform display on/off for a channel (state: ON/OFF). Always allowed (display-only)."""

    ch = channel.upper()

    st = state.upper()
    await _get_conn().write(f"OUTPut:WAVE {ch},{st}")
    return f"{ch} waveform display {st}"


# ---------------------------------------------------------------------------
# Timer# ---------------------------------------------------------------------------


@mcp.tool()
async def set_timer(channel: str, group: int, voltage: float, current: float, time_s: float) -> str:
    """Set timer parameters for a channel group (group 1-5, voltage in V, current in A, time in seconds).

    Requires channel write permission. Blocked if voltage or current exceed safety limits.
    """

    ch = channel.upper()

    err = _require_write(ch)
    if err:
        return err
    if group < 1 or group > 5:
        return "Error: group must be 1-5"
    errors = _check_both(ch, voltage, current)
    if errors:
        return f"REFUSED: {'; '.join(errors)}"
    await _get_conn().write(f"TIMEr:SET {ch},{group},{voltage},{current},{time_s}")
    return f"Timer {ch} group {group}: {voltage}V, {current}A, {time_s}s"


@mcp.tool()
async def get_timer(channel: str, group: int) -> str:
    """Query timer parameters for a channel group (returns voltage,current,time)."""

    ch = channel.upper()

    if group < 1 or group > 5:
        return "Error: group must be 1-5"
    return await _get_conn().query(f"TIMEr:SET? {ch},{group}")


@mcp.tool()
async def set_timer_state(channel: str, state: str) -> str:
    """Turn timer function on/off for a channel (state: ON/OFF). Requires channel write permission."""

    ch = channel.upper()

    err = _require_write(ch)
    if err:
        return err
    st = state.upper()
    await _get_conn().write(f"TIMEr {ch},{st}")
    return f"{ch} timer {st}"


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_system_status() -> str:
    """Query system status with decoded bit flags (output state, CV/CC mode, tracking, timers, display)."""

    raw = await _get_conn().query("SYSTem:STATus?")
    try:
        val = int(raw, 16)
        tracking_bits = (val >> 2) & 0x03
        tracking_map = {0: "unknown", 1: "independent", 2: "parallel", 3: "series"}
        status = {
            "raw": raw,
            "ch1_mode": "CC" if val & 0x01 else "CV",
            "ch2_mode": "CC" if val & 0x02 else "CV",
            "tracking": tracking_map.get(tracking_bits, "unknown"),
            "ch1_output": "ON" if val & 0x10 else "OFF",
            "ch2_output": "ON" if val & 0x20 else "OFF",
            "timer1": "ON" if val & 0x40 else "OFF",
            "timer2": "ON" if val & 0x80 else "OFF",
            "ch1_display": "waveform" if val & 0x100 else "digital",
            "ch2_display": "waveform" if val & 0x200 else "digital",
        }
        return json.dumps(status)
    except ValueError:
        return f"Raw status: {raw}"


@mcp.tool()
async def get_error() -> str:
    """Query the error code and information."""

    return await _get_conn().query("SYSTem:ERRor?")


@mcp.tool()
async def get_version() -> str:
    """Query the software version."""

    return await _get_conn().query("SYSTem:VERSion?")


# ---------------------------------------------------------------------------
# Network configuration
# ---------------------------------------------------------------------------


@mcp.tool()
async def set_ip(ip: str) -> str:
    """Set static IP address (DHCP must be off). Requires NETWORK write permission."""

    err = _require_write("NETWORK")
    if err:
        return err
    await _get_conn().write(f"IPaddr {ip}")
    return f"IP set to {ip}"


@mcp.tool()
async def get_ip() -> str:
    """Query current IP address."""

    return await _get_conn().query("IPaddr?")


@mcp.tool()
async def set_mask(mask: str) -> str:
    """Set subnet mask (DHCP must be off). Requires NETWORK write permission."""

    err = _require_write("NETWORK")
    if err:
        return err
    await _get_conn().write(f"MASKaddr {mask}")
    return f"Subnet mask set to {mask}"


@mcp.tool()
async def get_mask() -> str:
    """Query current subnet mask."""

    return await _get_conn().query("MASKaddr?")


@mcp.tool()
async def set_gateway(gateway: str) -> str:
    """Set gateway address (DHCP must be off). Requires NETWORK write permission."""

    err = _require_write("NETWORK")
    if err:
        return err
    await _get_conn().write(f"GATEaddr {gateway}")
    return f"Gateway set to {gateway}"


@mcp.tool()
async def get_gateway() -> str:
    """Query current gateway."""

    return await _get_conn().query("GATEaddr?")


@mcp.tool()
async def set_dhcp(state: str) -> str:
    """Enable or disable DHCP (ON/OFF). Requires NETWORK write permission."""

    err = _require_write("NETWORK")
    if err:
        return err
    st = state.upper()
    await _get_conn().write(f"DHCP {st}")
    return f"DHCP {st}"


@mcp.tool()
async def get_dhcp() -> str:
    """Query DHCP status."""

    return await _get_conn().query("DHCP?")


# ---------------------------------------------------------------------------
# Monitor — fixed duration (full channels only)
# ---------------------------------------------------------------------------


@mcp.tool()
async def monitor(
    channel: str = "CH1",
    interval_ms: int = 1000,
    duration_s: float = 10.0,
    voltage: bool = True,
    current: bool = True,
    power: bool = True,
) -> str:
    """Continuously measure voltage/current/power for a fixed duration.

    Returns a JSON time-series of readings. Use the boolean flags to
    include or exclude specific measurements (all enabled by default).
    """

    ch = channel.upper()

    interval = interval_ms / 1000.0
    data = []
    start_time = time.time()

    while time.time() - start_time < duration_s:
        t0 = asyncio.get_event_loop().time()
        reading = {"time": round(time.time() - start_time, 3)}
        try:
            if voltage:
                reading["voltage"] = float(await _get_conn().query(f"MEASure:VOLTage? {ch}"))
            if current:
                reading["current"] = float(await _get_conn().query(f"MEASure:CURRent? {ch}"))
            if power:
                reading["power"] = float(await _get_conn().query(f"MEASure:POWEr? {ch}"))
        except Exception as e:
            reading["error"] = str(e)
        data.append(reading)
        elapsed = asyncio.get_event_loop().time() - t0
        await asyncio.sleep(max(0, interval - elapsed))

    return json.dumps({"channel": ch, "samples": len(data), "readings": data})


# ---------------------------------------------------------------------------
# Monitor — open-ended (start/stop/get)# ---------------------------------------------------------------------------


async def _monitor_loop(monitor_id: str):
    mon = _monitors[monitor_id]
    interval = mon["interval_ms"] / 1000.0
    start_time = time.time()

    while mon["running"]:
        t0 = asyncio.get_event_loop().time()
        reading = {"time": round(time.time() - start_time, 3)}
        try:
            if mon["voltage"]:
                reading["voltage"] = float(await _get_conn().query(f"MEASure:VOLTage? {mon['channel']}"))
            if mon["current"]:
                reading["current"] = float(await _get_conn().query(f"MEASure:CURRent? {mon['channel']}"))
            if mon["power"]:
                reading["power"] = float(await _get_conn().query(f"MEASure:POWEr? {mon['channel']}"))
        except Exception as e:
            reading["error"] = str(e)
        mon["data"].append(reading)
        elapsed = asyncio.get_event_loop().time() - t0
        await asyncio.sleep(max(0, interval - elapsed))


@mcp.tool()
async def start_monitor(
    channel: str = "CH1",
    interval_ms: int = 1000,
    voltage: bool = True,
    current: bool = True,
    power: bool = True,
) -> str:
    """Start continuous background measurement. Returns a monitor_id to use with stop_monitor / get_monitor_data."""

    ch = channel.upper()

    global _monitor_counter
    _monitor_counter += 1
    monitor_id = str(_monitor_counter)

    mon = {
        "channel": ch,
        "interval_ms": interval_ms,
        "voltage": voltage,
        "current": current,
        "power": power,
        "running": True,
        "data": [],
        "task": None,
    }
    _monitors[monitor_id] = mon
    mon["task"] = asyncio.create_task(_monitor_loop(monitor_id))

    return json.dumps({"monitor_id": monitor_id, "channel": ch, "interval_ms": interval_ms})


@mcp.tool()
async def stop_monitor(monitor_id: str) -> str:
    """Stop a background monitor and return all collected data."""
    if monitor_id not in _monitors:
        return f"Error: monitor {monitor_id} not found"

    mon = _monitors[monitor_id]
    mon["running"] = False
    if mon["task"]:
        await mon["task"]

    data = mon["data"]
    del _monitors[monitor_id]

    return json.dumps({"monitor_id": monitor_id, "samples": len(data), "readings": data})


@mcp.tool()
async def get_monitor_data(monitor_id: str) -> str:
    """Get data collected so far by a running monitor (non-destructive peek)."""
    if monitor_id not in _monitors:
        return f"Error: monitor {monitor_id} not found"

    mon = _monitors[monitor_id]
    data = list(mon["data"])

    return json.dumps({"monitor_id": monitor_id, "running": mon["running"], "samples": len(data), "readings": data})


# ---------------------------------------------------------------------------


@mcp.tool()
async def disconnect() -> str:
    """Close the SCPI connection to the power supply, freeing the TCP port for other clients."""
    global conn
    if conn is None:
        return "No active connection"
    await conn.disconnect()
    conn = None
    return "Disconnected"


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
