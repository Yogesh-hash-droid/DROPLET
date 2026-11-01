# Backend Service - Smart Water Quality Monitoring API

Built with **FastAPI**, **SQLAlchemy**, and **Pydantic**. Provides endpoints for ingesting water telemetry, persisting records in MySQL, running safety rules, computing the Water Quality Score, and serving the **EXPERIMENTAL / ADVISORY** ML potability verdict (`prediction`, `confidence`) from the Phase 4 model.

## Directory Structure
```
backend/
├── app/
│   ├── main.py          # Application entrypoint & middleware
│   ├── config.py        # Settings & environment configuration
│   ├── database.py      # SQLAlchemy connection & session management
│   ├── models/          # SQLAlchemy ORM models
│   ├── schemas/         # Pydantic request/response schemas
│   ├── routers/         # API route handlers (/readings, /config, /predictions)
│   ├── services/        # Safety rule engine, Water Quality Score, reading/config services
│   └── ml/              # Model loader & inference service (EXPERIMENTAL, Phase 5)
├── tests/               # Backend unit and integration tests
├── requirements.txt     # Python dependencies
├── .env.example         # Environment template
└── README.md
```

## Running Locally

1. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   venv\Scripts\activate   # Windows
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up `.env` from `.env.example`:
   ```bash
   cp .env.example .env
   ```
4. Start the development server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
5. Open interactive docs at: `http://localhost:8000/docs`
