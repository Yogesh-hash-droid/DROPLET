"""
DROPLET — Arduino Uno Serial-to-Cloud Gateway
==============================================
Reads sensor telemetry from an Arduino Uno over USB serial, validates each
JSON line, and POSTs valid readings to the DROPLET backend REST API.

Hardware:  Arduino Uno running water_quality_uno_final.ino
Protocol:  9600 baud, one JSON object per line (newline-terminated)
Expected:  {"device_id":"UNO-001","tds":250.0,"turbidity":3.5,"source":"ARDUINO_UNO"}

DISCLAIMER: This is an educational prototype. TDS readings are NOT
temperature-compensated and do not certify water potability or safety.

Configuration (via environment variables or .env file):
    SERIAL_PORT   — COM port or /dev/ttyUSBx  (default: auto-detect)
    SERIAL_BAUD   — baud rate                  (default: 9600)
    API_URL       — backend base URL           (default: http://localhost:8000)
    RETRY_LIMIT   — max retries per reading    (default: 3)
    RETRY_DELAY_S — initial backoff in seconds (default: 2.0)

Usage:
    pip install pyserial requests python-dotenv
    python arduino/gateway.py

    # Or override via environment:
    SERIAL_PORT=COM5 API_URL=https://droplet-api-byl8.onrender.com python arduino/gateway.py
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# ── dependency checks ────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    load_dotenv()          # also load from cwd if a .env exists there
except ImportError:
    pass  # python-dotenv is optional; env vars can be set directly

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[FATAL] 'pyserial' not installed. Run: pip install pyserial requests python-dotenv")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("[FATAL] 'requests' not installed. Run: pip install pyserial requests python-dotenv")
    sys.exit(1)

# ── configuration (all from env; no hard-coded port or URL) ─────────────────
SERIAL_PORT   = os.environ.get("SERIAL_PORT", "")          # empty → auto-detect
SERIAL_BAUD   = int(os.environ.get("SERIAL_BAUD", "9600"))
API_URL       = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
RETRY_LIMIT   = int(os.environ.get("RETRY_LIMIT", "3"))
RETRY_DELAY_S = float(os.environ.get("RETRY_DELAY_S", "2.0"))

API_ENDPOINT  = f"{API_URL}/api/readings"

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("droplet.gateway")


# ── port auto-detection ──────────────────────────────────────────────────────
def detect_serial_port() -> str:
    """Return the first Arduino-like USB serial port found, or ask the user."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        log.warning("No serial ports detected. Connect Arduino Uno via USB and retry.")
        return ""

    log.info("Detected serial ports:")
    priority_port = None
    fallback_port = None
    for p in ports:
        log.info("  %s — %s", p.device, p.description)
        desc = (p.description or "").lower()
        # Ignore Bluetooth virtual COM ports
        if "bluetooth" in desc:
            continue
        if any(kw in desc for kw in ("arduino", "ch340", "cp210", "ftdi", "usb", "serial", "uart")):
            if priority_port is None:
                priority_port = p.device
        elif fallback_port is None:
            fallback_port = p.device

    chosen = priority_port or fallback_port or (ports[0].device if ports else "")
    log.info("Auto-selected: %s", chosen)
    return chosen


# ── validation ───────────────────────────────────────────────────────────────
def validate_reading(data: dict) -> tuple[bool, str]:
    """
    Return (True, "") if the reading is valid and should be posted.
    Return (False, reason) if it should be skipped (never post partial data).

    Rules:
    - 'tds' must be a finite float >= 0
    - 'turbidity' must be a finite float >= 0
    - 'device_id' must be a non-empty string
    - pH and temperature are NOT required and are intentionally absent for Uno
    - source must be a non-empty string (gateway enforces ARDUINO_UNO if absent)
    """
    import math

    tds = data.get("tds")
    turbidity = data.get("turbidity")

    if not isinstance(tds, (int, float)) or isinstance(tds, bool):
        return False, f"'tds' is not numeric: {tds!r}"
    if not math.isfinite(float(tds)) or float(tds) < 0:
        return False, f"'tds' is out of range or non-finite: {tds}"

    if not isinstance(turbidity, (int, float)) or isinstance(turbidity, bool):
        return False, f"'turbidity' is not numeric: {turbidity!r}"
    if not math.isfinite(float(turbidity)) or float(turbidity) < 0:
        return False, f"'turbidity' is out of range or non-finite: {turbidity}"

    device_id = data.get("device_id", "")
    if not device_id or not isinstance(device_id, str):
        return False, "Missing or invalid 'device_id'"

    return True, ""


# ── HTTP post with exponential backoff ───────────────────────────────────────
def post_reading(payload: dict) -> bool:
    """POST payload to API. Returns True on HTTP 200/201, False otherwise."""
    delay = RETRY_DELAY_S
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            resp = requests.post(
                API_ENDPOINT,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code in (200, 201):
                res = resp.json()
                rule_status = (res.get("parameter_rule_check") or {}).get("status", "N/A")
                score = res.get("quality_score", "N/A")
                log.info(
                    "[OK] TDS=%.1f ppm | Turbidity=%.2f NTU | Rule=%s | Score=%s",
                    payload["tds"], payload["turbidity"], rule_status, score,
                )
                return True
            else:
                log.warning("[API %d] attempt %d/%d — %s", resp.status_code, attempt, RETRY_LIMIT, resp.text[:200])
        except requests.exceptions.ConnectionError:
            log.warning("[NO CONN] attempt %d/%d — cannot reach %s", attempt, RETRY_LIMIT, API_ENDPOINT)
        except requests.exceptions.Timeout:
            log.warning("[TIMEOUT] attempt %d/%d", attempt, RETRY_LIMIT)
        except Exception as exc:
            log.warning("[HTTP ERR] attempt %d/%d — %s", attempt, RETRY_LIMIT, exc)

        if attempt < RETRY_LIMIT:
            log.info("  Retrying in %.1fs…", delay)
            time.sleep(delay)
            delay = min(delay * 2, 30.0)   # cap backoff at 30 s

    log.error("[DROPPED] Failed after %d attempts: %s", RETRY_LIMIT, payload)
    return False


# ── main bridge loop (reconnects on USB unplug) ──────────────────────────────
def run_bridge(port: str):
    log.info("=" * 58)
    log.info("  DROPLET Arduino Uno → Cloud Gateway")
    log.info("=" * 58)
    log.info("  Serial  : %s @ %d baud", port, SERIAL_BAUD)
    log.info("  API     : %s", API_ENDPOINT)
    log.info("  Retries : %d (backoff %.1fs)", RETRY_LIMIT, RETRY_DELAY_S)
    log.info("  Stop    : Ctrl+C")
    log.info("=" * 58)

    total_posted = 0
    total_skipped = 0

    while True:   # outer loop: reconnect after USB unplug
        ser = None
        try:
            log.info("Opening %s…", port)
            ser = serial.Serial(port=port, baudrate=SERIAL_BAUD, timeout=3.0)
            time.sleep(2.0)           # allow Arduino reset sequence to finish
            ser.reset_input_buffer()
            log.info("Connected to %s. Listening for sensor data…\n", port)

            while True:   # inner loop: read lines
                try:
                    raw = ser.readline()
                except serial.SerialException as e:
                    log.warning("Serial read error: %s — reconnecting in 3s…", e)
                    break  # break inner loop → reconnect

                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                # Print non-JSON device logs (calibration output, status, etc.)
                if not (line.startswith("{") and line.endswith("}")):
                    log.info("[UNO] %s", line)
                    continue

                # Parse JSON
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    log.warning("[CORRUPT JSON] %s — %s", exc, line[:120])
                    total_skipped += 1
                    continue

                # Ensure correct source tag (Uno firmware should set it; gateway enforces it)
                if not data.get("source"):
                    data["source"] = "ARDUINO_UNO"
                elif data["source"] not in ("ARDUINO_UNO", "ESP32", "ESP8266", "SIMULATION"):
                    log.warning("[BAD SOURCE] Overriding '%s' → 'ARDUINO_UNO'", data["source"])
                    data["source"] = "ARDUINO_UNO"

                # Default device_id if firmware omitted it
                if not data.get("device_id"):
                    data["device_id"] = "UNO-001"

                # Validate — never post incomplete or fabricated data
                valid, reason = validate_reading(data)
                if not valid:
                    log.warning("[SKIP] %s — raw: %s", reason, line[:120])
                    total_skipped += 1
                    continue

                # Remove pH and temperature entirely if None/missing (Uno has neither sensor)
                # The backend accepts them as absent; we must not invent values.
                for key in ("ph", "temperature"):
                    if key in data and data[key] is None:
                        del data[key]
                    elif key not in data:
                        pass   # absent is fine — backend stores NULL

                if post_reading(data):
                    total_posted += 1
                else:
                    total_skipped += 1

        except KeyboardInterrupt:
            log.info("\n[STOP] Ctrl+C received. Shutting down.")
            log.info("Summary: %d posted, %d skipped.", total_posted, total_skipped)
            break
        except serial.SerialException as exc:
            msg = str(exc)
            if "PermissionError" in msg or "Access is denied" in msg:
                log.error("[PORT BUSY] %s is currently locked by another program!", port)
                log.error("  -> If the Arduino IDE Serial Monitor is open, please CLOSE IT.")
                log.error("  -> Windows only allows one program to use %s at a time.", port)
                log.error("  -> Retrying in 4s (will connect automatically once Serial Monitor is closed)...")
            else:
                log.error("[SERIAL] %s — retrying in 5s…", exc)
            time.sleep(4.0)
        finally:
            if ser and ser.is_open:
                try:
                    ser.close()
                    log.info("Serial port %s closed.", port)
                except Exception:
                    pass


# ── entry point ───────────────────────────────────────────────────────────────
def main():
    port = SERIAL_PORT or detect_serial_port()
    if not port:
        log.error("No serial port specified and auto-detection found nothing.")
        log.error("Set SERIAL_PORT in your .env file, e.g.:  SERIAL_PORT=COM5")
        sys.exit(1)
    run_bridge(port)


if __name__ == "__main__":
    main()
