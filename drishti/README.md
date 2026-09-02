# Drishti — Working Skeleton

This is Build Steps 1-3 from the plan: Docker shell, upload flow, orthophoto
display, and a live map that renders extracted GIS features colored by
confidence. The `/extract` endpoint currently returns **mock features**
scattered realistically across the uploaded image's bounds — this is
intentional, so you can build and demo the full upload → map → export loop
before wiring in real AI models.

Verified working in isolation before packaging:
- Frontend builds cleanly (`npm run build`)
- Extraction pipeline logic produces valid GeoJSON
- GeoJSON and GeoPackage export both work against real GeoDataFrames

**Not yet tested here:** the live Postgres/PostGIS connection, since that
needs a running database — `docker-compose up` provides one, this sandbox
doesn't. Run it locally and confirm the backend starts cleanly before you
build on top of it.

## Run it

```bash
docker-compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs (auto-generated): http://localhost:8000/docs

## What to do first when you run it

1. `docker-compose up --build` — confirm all three containers start and the
   backend doesn't error on startup (that's your PostGIS connectivity check)
2. Open http://localhost:5173, upload any `.tif`/`.png`/`.jpg` — even a
   non-georeferenced image will work, it'll fall back to a demo AOI in Pune
3. Click "Run Extraction" — you'll see mock buildings/roads/trees/water
   appear on the map, color-coded by confidence
4. Click a feature — confirm the popup shows its type and confidence
5. Click Export — confirm a real `.geojson`/`.gpkg` file downloads

If all five steps work, your foundation is solid — everything from here is
replacing the mock pipeline with real models, not fixing infrastructure.

## Wiring in real AI models (Step 3-4 from the build plan)

Everything you need to change lives in **`backend/app/pipeline.py`** —
read the docstring at the top of that file. The API contract (what
`/extract` returns) is already correct; you're replacing the *inside* of
`run_extraction()`, not the interface, so nothing in the frontend needs to
change when you do this.

Suggested order:
1. SAMGeo (MobileSAM checkpoint) for buildings/water/farms — biggest visual
   payoff first
2. DeepForest for trees — pretrained, fastest to integrate
3. LULC via scikit-learn (Random Forest/XGBoost)
4. Roads (SAMGeo prompted, or YOLOv8n-seg if you have time to fine-tune)

## Known gaps (intentional, for a hackathon MVP — see the tech stack discussion)

- No auth — stubbed out on purpose
- FileGDB export not implemented — GeoJSON + GeoPackage cover the demo
- Celery/Redis not included — swap in only if you need true background
  jobs; FastAPI's request/response cycle is fine for demo-scale files
- The `Feature` DB model in `models.py` is defined but not yet written to —
  `/extract` caches results in memory. Wire it up if you want persistence
  across restarts or multi-user support.
