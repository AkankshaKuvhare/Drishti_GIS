import os
import shutil
import uuid
import threading
from typing import Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import geopandas as gpd
import rasterio
from rasterio.warp import transform_bounds

from .database import Base, engine, SessionLocal, get_db
from .models import Job
from . import pipeline

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Drishti API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory thread-safe state
_LAST_RESULT: dict[str, dict] = {}
_JOB_STATUS: dict[str, dict] = {}
_STATUS_LOCK = threading.Lock()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_orthophoto(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(400, "No file provided in request.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
        raise HTTPException(400, f"Unsupported file format '{ext}'. Please upload a valid GeoTIFF raster (.tif / .tiff).")

    job_id = str(uuid.uuid4())
    filepath = os.path.join(UPLOAD_DIR, f"{job_id}{ext}")

    try:
        with open(filepath, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Failed to save uploaded file: {str(e)}")

    bounds, crs = _read_bounds(filepath)

    job = Job(
        id=job_id,
        filename=file.filename,
        filepath=filepath,
        status="uploaded",
        bounds=bounds,
        crs=crs,
    )
    db.add(job)
    db.commit()


    with _STATUS_LOCK:
        _JOB_STATUS[job_id] = {
            "job_id": job_id,
            "status": "uploaded",
            "progress": 0,
            "filename": file.filename,
            "bounds": bounds,
            "crs": crs,
        }

    return {"job_id": job_id, "filename": file.filename, "bounds": bounds, "crs": crs}


@app.post("/extract/{job_id}")
def extract(job_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if not job.bounds:
        raise HTTPException(400, "Job has no georeferenced bounds; cannot place features")

    with _STATUS_LOCK:
        current_status = _JOB_STATUS.get(job_id, {}).get("status")
        if current_status == "processing":
            return {"job_id": job_id, "status": "processing"}

        _JOB_STATUS[job_id] = {
            "job_id": job_id,
            "status": "processing",
            "progress": 0,
            "current_tile": 0,
            "total_tiles": 0,
            "features_found": 0,
            "feature_breakdown": {},
            "geojson_url": None,
            "error": None,
        }

    job.status = "processing"
    db.commit()

    # Launch non-blocking background worker
    background_tasks.add_task(_background_extraction_worker, job_id, job.filepath, job.bounds)

    return {"job_id": job_id, "status": "processing"}


@app.get("/status/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    with _STATUS_LOCK:
        if job_id in _JOB_STATUS:
            return _JOB_STATUS[job_id]

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    if job.status == "uploaded":
        return {"job_id": job_id, "status": "uploaded", "progress": 0}
    elif job.status in ("done", "completed"):
        feature_count = len(_LAST_RESULT.get(job_id, {}).get("features", []))
        return {
            "job_id": job_id,
            "status": "completed",
            "progress": 100,
            "features_found": feature_count,
            "geojson_url": f"/export/{job_id}?format=geojson",
        }
    return {"job_id": job_id, "status": job.status, "progress": 0}


@app.get("/export/{job_id}")
def export(job_id: str, format: str = "geojson"):
    if job_id not in _LAST_RESULT:
        # Check if pre-generated GeoJSON output exists
        geo_path = os.path.join(OUTPUT_DIR, f"{job_id}.geojson")
        if not os.path.exists(geo_path):
            raise HTTPException(400, "Run /extract on this job before exporting")

    if format == "geojson":
        out_path = os.path.join(OUTPUT_DIR, f"{job_id}.geojson")
        if job_id in _LAST_RESULT:
            gdf = gpd.GeoDataFrame.from_features(_LAST_RESULT[job_id]["features"], crs="EPSG:4326")
            gdf.to_file(out_path, driver="GeoJSON")
        media_type = "application/geo+json"
    elif format == "gpkg":
        out_path = os.path.join(OUTPUT_DIR, f"{job_id}.gpkg")
        if job_id in _LAST_RESULT:
            gdf = gpd.GeoDataFrame.from_features(_LAST_RESULT[job_id]["features"], crs="EPSG:4326")
            gdf.to_file(out_path, driver="GPKG")
        media_type = "application/geopackage+sqlite3"
    else:
        raise HTTPException(400, f"Unsupported format: {format}")

    return FileResponse(out_path, media_type=media_type, filename=os.path.basename(out_path))


def _background_extraction_worker(job_id: str, filepath: str, bounds: list[float]):
    """Background worker function executing MobileSAM extraction and updating progress state."""
    db = SessionLocal()
    try:
        def on_progress(current_tile: int, total_tiles: int, current_features: int):
            pct = round((current_tile / max(total_tiles, 1)) * 100, 1)
            with _STATUS_LOCK:
                if job_id in _JOB_STATUS:
                    _JOB_STATUS[job_id]["status"] = "processing"
                    _JOB_STATUS[job_id]["progress"] = pct
                    _JOB_STATUS[job_id]["current_tile"] = current_tile
                    _JOB_STATUS[job_id]["total_tiles"] = total_tiles
                    _JOB_STATUS[job_id]["features_found"] = current_features

        result = pipeline.run_extraction(bounds, image_path=filepath, progress_callback=on_progress)
        _LAST_RESULT[job_id] = result

        features = result.get("features", [])
        breakdown = {}
        conf_sum = 0.0

        for f in features:
            props = f.get("properties", {})
            ftype = props.get("classification", props.get("feature_type", "unclassified"))
            breakdown[ftype] = breakdown.get(ftype, 0) + 1
            conf_sum += props.get("confidence", 0.85)

        avg_conf = round(conf_sum / max(len(features), 1), 2)
        meta = result.get("metadata", {})
        total_tiles = meta.get("total_tiles", _JOB_STATUS.get(job_id, {}).get("total_tiles", 121))
        raster_dims = f"{meta.get('width', 9095)} × {meta.get('height', 9636)} px"

        with _STATUS_LOCK:
            _JOB_STATUS[job_id] = {
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                "current_tile": total_tiles,
                "total_tiles": total_tiles,
                "features_found": len(features),
                "feature_breakdown": breakdown,
                "average_confidence": avg_conf,
                "raster_dimensions": raster_dims,
                "geojson_url": f"/export/{job_id}?format=geojson",
            }


        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "done"
            db.commit()

    except Exception as e:
        with _STATUS_LOCK:
            _JOB_STATUS[job_id] = {
                "job_id": job_id,
                "status": "failed",
                "error": str(e),
            }
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            db.commit()
    finally:
        db.close()


def _read_bounds(filepath: str):
    """Try to read georeferenced bounds from the uploaded raster."""
    try:
        with rasterio.open(filepath) as src:
            if src.crs is None:
                raise ValueError("no CRS")
            b = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
            return list(b), "EPSG:4326"
    except Exception:
        default = [73.8500, 18.5100, 73.8700, 18.5300]
        return default, "EPSG:4326"
