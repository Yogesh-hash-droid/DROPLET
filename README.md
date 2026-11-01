# IoT-Based Smart Water Quality Monitoring and Machine Learning-Based Potability Prediction System

> **Disclaimer**: This system is an educational prototype and does not replace certified laboratory water testing. Prototype prediction only. Certified laboratory testing is required for actual drinking-water safety assessment.

---

## 1. Project Objective
To design and build an end-to-end intelligent water monitoring system that ingests key physical/chemical water quality parameters (pH, TDS, Turbidity, Temperature), stores them in a relational database, performs real-time deterministic safety threshold evaluations alongside an empirical Machine Learning potability classifier (Random Forest), and visualizes health metrics on an interactive web dashboard.

## 2. Problem Statement
Access to safe drinking water is critical to human health. Traditional laboratory testing of water quality is accurate but slow, expensive, and incapable of providing real-time warnings. Conventional automated systems typically only check fixed thresholds without multi-parameter probabilistic modeling, or obscure safety violations behind black-box ML predictions. There is a need for a modular, transparent hybrid architecture that combines rigorous rule-based safety alerts with machine-learning potability inference.

## 3. Proposed Solution
A decoupled, service-oriented system featuring:
- **Pluggable Data Ingestion**: Accepts readings from a realistic multi-scenario software simulator today, and identical HTTP JSON payloads from ESP32 microcontrollers in the field later.
- **Dual-Engine Evaluation**:
  - **Safety Rule Engine**: Enforces configurable regulatory/operational thresholds with explicit violation explanations.
  - **Machine Learning Classifier**: Evaluates multi-parameter potability probability using a trained Random Forest model.
  - **Water Quality Score**: Calculates a normalized 0-100 composite score (`quality_score`; an internal prototype metric, not an official Water Quality Index/WQI).
- **Modern Observability**: A responsive React + Vite web dashboard displaying real-time telemetry cards, trend charts, tabular history, and system configurations.

## 4. System Architecture

```
CURRENT (Simulation Mode):
    Simulator (Simulated Scenarios)
                 │
                 ▼  (HTTP POST /api/readings)
         FastAPI Backend
                 ├── MySQL 8+ (Readings, Predictions, Devices, Config)
                 ├── Safety Rule Engine (Deterministic Thresholds)
                 ├── Quality Scoring Engine (Water Quality Score 0-100)
                 └── ML Potability Model (Completed - Phase 4, served in Phase 5)
                 │
                 ▼  (REST API / Polling)
         React + Vite Dashboard (Recharts telemetry & alerts)

FUTURE (Hardware Mode):
    Sensors (pH, TDS, Turbidity, Temp)
                 │
                 ▼
          ESP32 Microcontroller
                 │
                 ▼  (Wi-Fi HTTP POST /api/readings)
         FastAPI Backend  <-- Identical API contract!
```

## 5. Technology Stack
- **Backend**: Python 3.10+, FastAPI, Uvicorn, SQLAlchemy, Pydantic, PyMySQL / mysql-connector-python
- **Database**: MySQL 8.0+
- **Machine Learning**: Scikit-Learn (Random Forest Classifier), Pandas, NumPy, Joblib
- **Frontend**: React 18+, Vite, Axios, Recharts, Lucide Icons, Modern CSS
- **Simulation**: Python multi-scenario telemetry generator
- **Hardware Integration (Future)**: ESP32, Arduino C/C++, HTTP/REST client

## 6. Monorepo Structure
```
smart-water-quality/
├── backend/            # FastAPI REST API, SQLAlchemy models, services, tests
├── frontend/           # React + Vite web dashboard & analytics
├── ml/                 # Model training, dataset handling, evaluation scripts
├── simulator/          # Multi-scenario water quality telemetry simulator
├── database/           # MySQL DDL schemas and seed scripts
├── esp32/              # Hardware wiring, firmware templates & pinouts
└── docs/               # Architecture, API specifications, hardware integration
```

## 7. Setup & Run Instructions

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

### Step 4: Run Simulator
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
## 8. Limitations & Future Improvements
- **Educational Prototype**: Not a substitute for certified bacteriological, radiological, or trace chemical lab testing.
- **Future Hardware**: Ready for seamless drop-in integration with physical ESP32 analog/digital sensor probes.
