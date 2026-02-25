# siglent-spd-mcp

MCP server for Siglent SPD Series Power Supplies (SPD3303X, SPD3303X-E, SPD1168X, etc.).

Exposes voltage/current control, measurement, monitoring, timer, and system
configuration as [Model Context Protocol](https://modelcontextprotocol.io/)
tools over SCPI/TCP.

## Installation

```bash
pip install siglent-spd-mcp
```

## Configuration

The server connects to the power supply via TCP/SCPI. Set the host and port
with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SPD_HOST` | *(required)* | IP address of the power supply |
| `SPD_PORT` | `5025` | SCPI TCP port |

### Permissions (default: readonly)

All channels default to read-only. Set to `readwrite` to allow control:

| Variable | Values | Description |
|----------|--------|-------------|
| `CH1_PERM` | `readonly` / `readwrite` | Channel 1 write access |
| `CH2_PERM` | `readonly` / `readwrite` | Channel 2 write access |
| `CH3_PERM` | `readonly` / `readwrite` | Channel 3 write access |
| `NETWORK_PERM` | `readonly` / `readwrite` | Network config write access |
| `MEMORY_PERM` | `readonly` / `readwrite` | Save/recall write access |

### Safety limits (optional)

Set per-channel voltage and current limits to prevent accidental damage:

| Variable | Example | Description |
|----------|---------|-------------|
| `CH1_MAX_VOLTAGE` | `5.0` | Max voltage for CH1 (V) |
| `CH1_MAX_CURRENT` | `1.0` | Max current for CH1 (A) |
| `CH2_MAX_VOLTAGE` | `32.0` | Max voltage for CH2 (V) |
| `CH2_MAX_CURRENT` | `3.2` | Max current for CH2 (A) |

## Usage

### Claude Desktop / Claude Code

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "siglent-spd": {
      "command": "siglent-spd-mcp",
      "env": {
        "SPD_HOST": "192.168.1.100",
        "CH1_PERM": "readwrite",
        "CH1_MAX_VOLTAGE": "5.0",
        "CH1_MAX_CURRENT": "1.0"
      }
    }
  }
}
```

### Direct execution

```bash
# Via entry point
siglent-spd-mcp

# Via module
python -m siglent_spd_mcp
```

## Tools

### Identification
- `identify` - Query instrument ID (manufacturer, model, serial, firmware)

### Measurement
- `measure_voltage` - Measure actual output voltage
- `measure_current` - Measure actual output current
- `measure_power` - Measure actual output power
- `measure_all` - Measure voltage, current, and power in one call

### Control
- `set_voltage` - Set voltage setpoint
- `get_voltage` - Query voltage setpoint
- `set_current` - Set current limit
- `get_current` - Query current setpoint
- `set_output` - Turn channel output on/off
- `set_tracking_mode` - Set tracking mode (independent/series/parallel)

### Monitoring
- `monitor` - Measure for a fixed duration, return time-series data
- `start_monitor` - Start continuous background measurement
- `stop_monitor` - Stop background monitor and return collected data
- `get_monitor_data` - Peek at data from a running monitor

### Timer
- `set_timer` - Configure timer group parameters
- `get_timer` - Query timer group parameters
- `set_timer_state` - Enable/disable timer function

### System
- `get_system_status` - Query decoded system status flags
- `get_error` - Query error code
- `get_version` - Query software version
- `get_safety_config` - Show configured permissions and safety limits

### Save/Recall
- `save_state` - Save instrument state to nonvolatile memory
- `recall_state` - Recall instrument state (with safety limit checks)

### Network
- `set_ip` / `get_ip` - Static IP address
- `set_mask` / `get_mask` - Subnet mask
- `set_gateway` / `get_gateway` - Gateway address
- `set_dhcp` / `get_dhcp` - DHCP enable/disable

### Display
- `set_waveform_display` - Toggle waveform display per channel

## License

GPLv3+
