"""LabData Analytics: small educational laboratory sample API.

Uses synthetic sample data only. SQLite is created on first startup and
seeded from data/samples.csv only when the sample table is empty.
"""
import os
import io
import math
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Date, Float, String, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "samples.csv"
DB_PATH = Path(os.environ.get("LABDATA_DB_PATH", str(BASE_DIR / "data" / "labdata.db"))).resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Status = Literal["received", "processing", "completed"]


class Base(DeclarativeBase):
    pass


class Sample(Base):
    __tablename__ = "samples"
    sample_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    sample_type: Mapped[str] = mapped_column(String(80), nullable=False)
    collected_at: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_value: Mapped[float | None] = mapped_column(Float, nullable=True)


class SampleCreate(BaseModel):
    sample_id: str = Field(min_length=1, max_length=50)
    sample_type: str = Field(min_length=1, max_length=80)
    collected_at: date
    status: Status = "received"
    result_value: float | None = Field(default=None, allow_inf_nan=False)


class SampleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status | None = None
    result_value: float | None = Field(default=None, allow_inf_nan=False)


class SampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sample_id: str
    sample_type: str
    collected_at: date
    status: Status
    result_value: float | None


def seed_from_csv_if_empty() -> None:
    """Import synthetic starter records once; never overwrite user changes."""
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(Sample)) != 0:
            return
        if not CSV_PATH.exists():
            return
        df = pd.read_csv(CSV_PATH, dtype={"sample_id": "string", "sample_type": "string", "status": "string"})
        required = {"sample_id", "sample_type", "collected_at", "status", "result_value"}
        if not required.issubset(df.columns):
            raise ValueError(f"CSV is missing columns: {sorted(required - set(df.columns))}")
        if df["sample_id"].isna().any() or df["sample_id"].duplicated().any():
            raise ValueError("CSV sample IDs must be present and unique")
        for row in df.to_dict(orient="records"):
            value = row["result_value"]
            item = SampleCreate(
                sample_id=str(row["sample_id"]),
                sample_type=str(row["sample_type"]),
                collected_at=date.fromisoformat(str(row["collected_at"])),
                status=str(row["status"]),
                result_value=None if pd.isna(value) else float(value),
            )
            session.add(Sample(**item.model_dump()))
        session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_from_csv_if_empty()
    yield


app = FastAPI(title="LabData Analytics", version="0.3.0", description="Educational demo using synthetic laboratory data only.", lifespan=lifespan)


def get_db():
    with SessionLocal() as session:
        yield session


@app.get("/")
def home():
    return {"message": "LabData Analytics API", "docs": "/docs", "storage": "SQLite"}


@app.get("/samples")
def get_samples(status: Status | None = None, db: Session = Depends(get_db)):
    stmt = select(Sample).order_by(Sample.sample_id)
    if status is not None:
        stmt = stmt.where(Sample.status == status)
    samples = db.scalars(stmt).all()
    return {"count": len(samples), "samples": [SampleOut.model_validate(item) for item in samples]}


@app.get("/samples/{sample_id}", response_model=SampleOut)
def get_sample(sample_id: str, db: Session = Depends(get_db)):
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="Sample not found")
    return sample


@app.post("/samples", response_model=SampleOut, status_code=201)
def create_sample(payload: SampleCreate, db: Session = Depends(get_db)):
    item = Sample(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Sample ID already exists") from exc
    db.refresh(item)
    return item


@app.patch("/samples/{sample_id}", response_model=SampleOut)
def update_sample(sample_id: str, payload: SampleUpdate, db: Session = Depends(get_db)):
    item = db.get(Sample, sample_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Sample not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "status" and value is None:
            raise HTTPException(status_code=422, detail="status cannot be null")
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@app.get("/summary")
def summary(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Sample.status, func.count()).group_by(Sample.status)).all())
    by_status = {status: counts.get(status, 0) for status in ("completed", "processing", "received")}
    return {"total_samples": sum(by_status.values()), "by_status": by_status}


@app.post("/samples/import-csv")
async def import_samples_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Validate and import all valid records atomically (no partial imports).

    This endpoint is for synthetic practice data only. Do not upload real patient data.
    Max 1 MiB, max 500 rows per import.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file")
    raw = await file.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV file is larger than 1 MiB")
    try:
        content = raw.decode("utf-8-sig")
        df = pd.read_csv(io.StringIO(content), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read UTF-8 CSV: {exc}") from exc

    required = ["sample_id", "sample_type", "collected_at", "status", "result_value"]
    if any(column not in df.columns for column in required):
        missing = [column for column in required if column not in df.columns]
        raise HTTPException(status_code=422, detail={"message": "Missing columns", "columns": missing})
    if len(df) > 500:
        raise HTTPException(status_code=413, detail="Maximum 500 data rows per import")
    if df.empty:
        raise HTTPException(status_code=422, detail="CSV must contain at least one data row")

    errors = []
    items = []
    seen = set()
    for index, row in df.iterrows():
        line = int(index) + 2  # CSV header is line 1
        values = {key: str(row[key]).strip() for key in required}
        sample_id = values["sample_id"]
        if sample_id in seen:
            errors.append({"row": line, "error": "Duplicate sample_id in CSV"})
            continue
        seen.add(sample_id)
        try:
            value = None if values["result_value"] == "" else float(values["result_value"])
            item = SampleCreate(
                sample_id=sample_id,
                sample_type=values["sample_type"],
                collected_at=date.fromisoformat(values["collected_at"]),
                status=values["status"],
                result_value=value,
            )
            items.append(item)
        except (ValueError, TypeError, __import__("pydantic").ValidationError) as exc:
            errors.append({"row": line, "error": str(exc)[:240]})

    if errors:
        raise HTTPException(status_code=422, detail={"message": "Validation failed; nothing imported", "errors": errors[:30]})

    existing_ids = set(db.scalars(select(Sample.sample_id).where(Sample.sample_id.in_([i.sample_id for i in items]))).all())
    if existing_ids:
        raise HTTPException(status_code=409, detail={"message": "Sample IDs already exist; nothing imported", "ids": sorted(existing_ids)})

    db.add_all([Sample(**item.model_dump()) for item in items])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting sample ID; nothing imported") from exc
    return {"imported": len(items), "sample_ids": [item.sample_id for item in items]}
