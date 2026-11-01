"""
DROPLET - Serial to API Telemetry Bridge
========================================
Reads real-time sensor telemetry from a hardware microcontroller connected
via USB Serial (e.g., COM9) and forwards each reading to the DROPLET backend
API endpoint: POST /api/readings.

Requirements:
    pip install pyserial requests

Usage:
    python esp32/serial_to_api_bridge.py [--port COM9] [--baud 115200] [--api http://localhost:8000]
"""

import argparse
import json
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[ERROR] 'pyserial' package is not installed.")
    print("Please install it by running: pip install pyserial requests")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("[ERROR] 'requests' package is not installed.")
    print("Please install it by running: pip install requests")
    sys.exit(1)


def detect_serial_port() -> str:
    """Auto-detect available USB serial COM port."""
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("[WARN] No COM ports detected. Please connect your microcontroller via USB.")
        return "COM9"

    print("\n--- Detected Serial Ports ---")
    selected_port = None
    for p in ports:
        print(f"  * {p.device}: {p.description}")
        # Favor common USB-to-UART bridge chips
        desc = (p.description or "").lower()
        if "ch340" in desc or "cp210" in desc or "ftdi" in desc or "usb-serial" in desc or "arduino" in desc:
            selected_port = p.device

    if not selected_port:
        selected_port = ports[0].device

    print(f"--> Auto-selected: {selected_port}\n")
    return selected_port


def run_bridge(port: str, baudrate: int, api_url: str):
    target_endpoint = f"{api_url.rstrip('/')}/api/readings"
    print("==================================================")
    print("      DROPLET Hardware-to-Software Bridge         ")
    print("==================================================")
    print(f" Serial Port : {port} @ {baudrate} baud")
    print(f" Target API  : {target_endpoint}")
    print(" Connecting to microcontroller... (Ctrl+C to stop)")
    print("==================================================\n")

    try:
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=2.0)
        time.sleep(2.0)  # Allow Arduino/ESP32 reset sequence to complete
        ser.reset_input_buffer()
        print(f"[SUCCESS] Connected to {port}! Listening for live sensor data...\n")
    except Exception as e:
        print(f"[ERROR] Could not open {port}: {e}")
        print("Tip: Close Arduino Serial Monitor if it is currently open.")
        sys.exit(1)

    successful_reads = 0

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            # Ignore non-JSON status logs
            if not (line.startswith("{") and line.endswith("}")):
                print(f"[MCU LOG] {line}")
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                print(f"[CORRUPT DATA] {line}")
                continue

            # Ensure minimum required keys
            if "tds" not in data or "turbidity" not in data:
                print(f"[IGNORED] Missing required fields: {data}")
                continue

            # Ensure valid source tag
            if "source" not in data or data["source"] not in ("ESP32", "ESP8266"):
                data["source"] = "ESP32"

            if "device_id" not in data:
                data["device_id"] = "ESP32-WATER-001"

            # Post to DROPLET REST API
            start_t = time.time()
            try:
                resp = requests.post(
                    target_endpoint,
                    json=data,
                    headers={"Content-Type": "application/json"},
                    timeout=5.0
                )
                latency_ms = int((time.time() - start_t) * 1000)

                if resp.status_code == 201:
                    successful_reads += 1
                    res_json = resp.json()
                    rule_status = res_json.get("parameter_rule_check", {}).get("status", "N/A")
                    score = res_json.get("quality_score", "N/A")
                    print(
                        f"[SYNC #{successful_reads:04d} | {latency_ms}ms] "
                        f"TDS: {data['tds']:>5.1f} ppm | "
                        f"Turbidity: {data['turbidity']:>5.2f} NTU | "
                        f"Rule Status: {rule_status} | "
                        f"Score: {score}"
                    )
                else:
                    print(f"[API ERROR {resp.status_code}] {resp.text}")

            except requests.exceptions.ConnectionError:
                print(f"[HTTP FAIL] Could not reach {target_endpoint}. Is the DROPLET backend running?")
            except Exception as http_err:
                print(f"[HTTP ERROR] {http_err}")

        except KeyboardInterrupt:
            print("\n[STOPPING] Bridge stopped by user.")
            break
        except Exception as err:
            print(f"[STREAM ERROR] {err}")
            time.sleep(1)

    ser.close()
    print("[DISCONNECTED] Serial port closed.")


def main():
    parser = argparse.ArgumentParser(description="DROPLET Serial-to-API Hardware Bridge")
    parser.add_argument("--port", type=str, default=None, help="COM port (e.g. COM9). If omitted, auto-detects.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (default: 115200)")
    parser.add_argument("--api", type=str, default="http://localhost:8000", help="DROPLET backend base URL")

    args = parser.parse_args()
    port = args.port or detect_serial_port()
    run_bridge(port=port, baudrate=args.baud, api_url=args.api)


if __name__ == "__main__":
    main()
