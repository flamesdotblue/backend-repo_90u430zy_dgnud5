# Backend API

A simple FastAPI backend with CORS enabled.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure port (optional):
   - Port is configured in `.env` file
   - Default: `PORT=8000`

3. Run the server:
```bash
python main.py
```
   Or with uvicorn directly:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints

- `GET /` - Root endpoint
- `GET /api/hello` - Hello API endpoint
- `GET /test` - Database connectivity test endpoint
