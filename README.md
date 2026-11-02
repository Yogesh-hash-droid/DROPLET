# IoT-Based Smart Water Quality Monitoring and Machine Learning-Based Potability Prediction System

> **⚠️ Educational Prototype Disclaimer**: This system is an educational prototype and does not replace certified laboratory water testing. Prototype prediction only. TDS readings are NOT temperature-compensated. Certified laboratory testing is required for actual drinking-water safety assessment.

---

## 1. Project Objective
To design and build an end-to-end intelligent water monitoring system that ingests key physical/chemical water quality parameters (TDS, Turbidity, and optionally pH/Temperature from legacy hardware or simulation), stores them in a relational database, performs real-time deterministic safety threshold evaluations alongside an empirical Machine Learning potability classifier (Random Forest), and visualizes health metrics on an interactive web dashboard.

## 2. Problem Statement
Access to safe drinking water is critical to human health. Traditional laboratory testing of water quality is accurate but slow, expensive, and incapable of providing real-time warnings. Conventional automated systems typically only check fixed thresholds without multi-parameter probabilistic modeling, or obscure safety violations behind black-box ML predictions. There is a need for a modular, transparent hybrid architecture that combines rigorous rule-based safety alerts with machine-learning potability inference.

## 3. Proposed Solution
A decoupled, service-oriented system featuring:
- **Pluggable Data Ingestion**: Accepts readings from Arduino Uno via USB Serial Gateway (`ARDUINO_UNO`), realistic multi-scenario software simulator (`SIMULATION`), and legacy ESP8266/ESP32 microcontrollers (`ESP8266`, `ESP32`).
- **Dual-Engine Evaluation**:
  - **Safety Rule Engine**: Enforces configurable regulatory/operational thresholds with explicit violation explanations.
  - **Machine Learning Classifier**: Evaluates multi-parameter potability probability when full parameters are available, or reports transparent availability reasons (`PH_NOT_MEASURED`) when running 2-parameter hardware without inventing numbers.
  - **Water Quality Score**: Calculates a normalized 0-100 composite score (`quality_score`; an internal prototype metric, not an official Water Quality Index/WQI).
- **Modern Observability**: A responsive React + Vite web dashboard displaying real-time telemetry cards, trend charts, tabular history, and system configurations.

## 4. System Architecture

```
PRIMARY (Arduino Uno Hardware Mode):
    Sensors (TDS on A0, Turbidity on A1)
                 │
                 ▼
         Arduino Uno (water_quality_uno_final.ino)
                 │
                 ▼  (USB Serial @ 9600 baud JSON)
         Serial-to-HTTP Gateway (arduino/gateway.py)
                 │
                 ▼  (HTTP POST /api/readings, source=ARDUINO_UNO)
         FastAPI Backend
                 ├── MySQL 8+ / Aiven Cloud (Readings, Predictions, Devices)
                 ├── Safety Rule Engine (Deterministic Thresholds)
                 ├── Quality Scoring Engine (Two-parameter screening score)
                 └── ML Classifier (Unavailable notice without fake numbers)
                 │
                 ▼  (REST API / Polling)
         React + Vite Dashboard (https://droplet-cyan.vercel.app/)

SIMULATION / LEGACY:
    Simulator / ESP8266 / ESP32 ──► FastAPI Backend ──► Dashboard
```

## 5. Technology Stack
- **Hardware**: Arduino Uno (ATmega328P), Analog TDS module, Analog Turbidity sensor
- **Serial Gateway**: Python 3.10+, PySerial, Requests, Python-dotenv
- **Backend**: Python 3.10+, FastAPI, Uvicorn, SQLAlchemy, Pydantic, PyMySQL / mysql-connector-python
- **Database**: MySQL 8.0+ / Aiven Cloud MySQL
- **Machine Learning**: Scikit-Learn (Random Forest Classifier), Pandas, NumPy, Joblib
- **Frontend**: React 18+, Vite, Axios, Recharts, Lucide Icons, Modern CSS
- **Simulation**: Python multi-scenario telemetry generator

## 6. Monorepo Structure
```
smart-water-quality/
├── arduino/            # Arduino Uno firmware, serial-to-HTTP gateway, wiring docs
│   ├── water_quality_uno_final/
│   │   └── water_quality_uno_final.ino   # Authoritative Uno firmware
│   ├── gateway.py      # USB Serial-to-HTTP cloud gateway
│   └── .env.example    # Gateway configuration template
├── backend/            # FastAPI REST API, SQLAlchemy models, services, tests
├── frontend/           # React + Vite web dashboard & analytics
├── ml/                 # Model training, dataset handling, evaluation scripts
├── simulator/          # Multi-scenario water quality telemetry simulator
├── database/           # MySQL DDL schemas and seed scripts
├── esp32/archive/      # Archived legacy ESP8266/ESP32 firmware for reference
└── docs/               # Architecture, API specifications, hardware integration
```

---

## 7. Arduino Uno Hardware Setup & Wiring

### Wiring Table (authoritative — match this exactly)

| From | To |
|------|----|
| TDS red (+) | Uno D7 (digital pin 7, powered only while reading; 5V is an acceptable fallback) |
| TDS black (-) | Uno GND |
| TDS yellow (A) | Uno A0 |
| Turbidity V | Uno 5V |
| Turbidity G | Uno GND |
| Turbidity signal | Uno A1 |

**No I2C wires are used any more (no SDA, SCL, ADDR).** The Uno ADC is 10-bit at about 5 V. The firmware measures the real 5V rail itself, averages samples, and saves calibration in EEPROM through Serial Monitor commands (`tds <ppm>`, `clear`, `turb <ntu>`, `show`, `reset`).

### Arduino IDE Setup
1. Board: **Arduino Uno**
2. Baud Rate: **9600** (in Serial Monitor)
3. Line Ending: **Newline**

### Calibration Serial Commands
Open the Arduino IDE Serial Monitor at 9600 baud (Newline line ending) and enter:
- `tds <ppm>`: Calibrate TDS with a known standard (e.g. `tds 500`)
- `turb <ntu>`: Calibrate turbidity with a known NTU standard (e.g. `turb 4.5`)
- `show`: Print current calibration values stored in EEPROM
- `reset`: Reset calibration to factory defaults
- `clear`: Clear all stored calibration from EEPROM

### Serial-to-HTTP Gateway Setup
The Arduino Uno does not have Wi-Fi. It streams JSON telemetry over USB Serial. The Python gateway forwards readings to the backend.

```bash
# 1. Install dependencies
pip install pyserial requests python-dotenv

# 2. Configure gateway
cd arduino
cp .env.example .env
# Edit .env with your COM port (or leave blank for auto-detection) and API URL:
# SERIAL_PORT=COM3
# API_URL=https://droplet-api-byl8.onrender.com

# 3. Run gateway
python gateway.py
```
Gateway features:
- Automatically scans and connects to Arduino Uno COM port
- Validates every reading; discards malformed lines; never invents fake data
- Exponential backoff retry on network drops
- Auto-reconnects when USB cable is unplugged and re-plugged
- Graceful shutdown on Ctrl+C

---

## 8. General Setup & Run Instructions

### Prerequisites
- Python 3.10+
- Node.js 18+ & npm
- MySQL Server 8.0+

### Step 1: Database Setup
```bash
mysql -u root -p < database/schema.sql
```

### Step 2: Backend Setup
```bash
cd backend
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env with your MySQL credentials

uvicorn app.main:app --reload --port 8000
```
Backend health check: `http://localhost:8000/health`  
Interactive Swagger docs: `http://localhost:8000/docs`

### Step 3: Train Machine Learning Model
```bash
cd ../ml
python train.py
```

### Step 4: Run Simulator (Alternative to Hardware)
```bash
cd ../simulator
python simulator.py
```

### Step 5: Frontend Dashboard
```bash
cd ../frontend
npm install
npm run dev
```
Dashboard available at: `http://localhost:5173`

---

## 9. Limitations & Disclaimer
- **Educational Prototype**: Not a substitute for certified bacteriological, radiological, or trace chemical lab testing.
- **Temperature Compensation**: Analog TDS readings on Arduino Uno are not temperature-compensated. Readings reflect electrical conductivity at ambient temperature.
- **Two-Parameter Screening**: When running without pH and temperature, ML potability prediction is marked as `UNAVAILABLE` (`PH_NOT_MEASURED`) rather than substituting fabricated numbers.
