# LabData Analytics — Starter (Phase 1)

Python/FastAPI/Pandas portfolio project demonstrating **synthetic** laboratory CSV ingestion, basic validation, and sample query endpoints. No real patient information.

## Setup (Windows PowerShell)

```powershell
cd .\LabData-Analytics-Starter
py --version
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

If `py` is not recognized, install Python 3.11+ from python.org, enable Python launcher, and open a new PowerShell window.

Open **http://127.0.0.1:8000/docs** and try:

- `GET /` (health greeting)
- `GET /samples` (all five records)
- `GET /samples?status=completed` (filtered)
- `GET /samples/LAB-001` (one sample)
- `GET /summary` (counts by status)

**Data is read from a CSV on every request.** Persistence/import uploads, SQLite, tests, Docker, and GitHub Actions will be added in later phases.

## CSV schema

`sample_id,sample_type,collected_at,status,result_value`

Allowed statuses: `received`, `processing`, `completed`. Missing results are allowed for unfinished tests.
