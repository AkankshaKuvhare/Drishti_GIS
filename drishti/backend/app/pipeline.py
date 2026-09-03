"""
Feature extraction pipeline using SAMGeo (MobileSAM).

This module replaces mock feature extraction with real segment anything AI inference.
MobileSAM (vit_t) is used to perform CPU-friendly automatic mask generation on orthophoto rasters.

WHY MOBILESAM OVER FULL SAM (ViT-H):
1. Parameter Count: Full SAM (ViT-H) has ~636 Million parameters (~2.5 GB model weights),
   whereas MobileSAM uses a decoupled ViT-Tiny encoder with only ~5 Million parameters (~40 MB weights).
2. Hardware Constraints: Full SAM requires a high-end GPU with 12GB+ VRAM for interactive performance.
   MobileSAM is optimized for laptop CPUs, offering up to ~50x faster encoder inference while preserving SAM mask quality.
3. Memory Footprint: MobileSAM can run comfortably within standard application server memory limits without OOM risks.

WHAT AUTOMATIC MASK GENERATION IS DOING:
1. Dense Point Grid Sampling: Rather than relying on user prompts (points/boxes), SamAutomaticMaskGenerator
   samples a uniform 2D grid of point prompts (e.g., 16x16 = 256 points) across the input image.
2. Multi-Mask Prediction: For each prompt point, the model generates multiple mask candidates, calculating
   both a predicted Intersection-over-Union (predicted_iou) and a mask stability score.
3. Non-Maximum Suppression (NMS) & Filtering: Overlapping masks are filtered using NMS and confidence thresholds
   to remove duplicates and low-quality artifacts, returning a clean array of object masks.

HOW A RAW SAM MASK BECOMES A SHAPELY POLYGON:
1. 2D Boolean Array to Contours: SAM outputs a binary boolean matrix (H x W) indicating object pixels.
2. Raster Vectorization: `rasterio.features.shapes()` extracts vector boundary rings from contiguous True pixel clusters.
3. Spatial Affine Transformation: Raster pixel coordinates (column, row) are transformed into geographic coordinates
   (longitude, latitude) using the GeoTIFF's affine transformation matrix.
4. Reprojection & Shapely Conversion: Coordinates are reprojected to EPSG:4326 if necessary and parsed into a
   `shapely.geometry.Polygon` object, which is cleaned with `.buffer(0)` and formatted as GeoJSON.
"""

import os
import urllib.request
from typing import Any

import numpy as np
import pyproj

import rasterio
from rasterio.enums import Resampling
from rasterio.features import shapes
from rasterio.transform import Affine
from rasterio.warp import transform_geom
from rasterio.windows import Window, transform as window_transform
import shapely.geometry
from shapely.geometry import shape, Polygon

import torch
from mobile_sam import sam_model_registry, SamAutomaticMaskGenerator


# Model Caching Global State
_MODEL_INSTANCE = None
_MASK_GENERATOR = None

CHECKPOINT_URL = "https://raw.githubusercontent.com/ChaoningZhang/MobileSAM/master/weights/mobile_sam.pt"
CHECKPOINT_PATH = os.path.join(os.path.expanduser("~"), ".cache", "mobile_sam", "mobile_sam.pt")
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")

# Tiling configuration for CPU performance & memory safety
TILE_SIZE = 1024              # 1024px tile window size as requested
OVERLAP = 128                 # 128px overlap margin between adjacent tiles
MAX_TILE_INFERENCE_DIM = 1024  # Max dimension for per-tile MobileSAM memory safety



def get_mask_generator() -> SamAutomaticMaskGenerator:
    """
    Lazy-load MobileSAM model checkpoint and return singleton SamAutomaticMaskGenerator.
    Downloads mobile_sam.pt checkpoint (~40MB) if not present locally.
    """
    global _MODEL_INSTANCE, _MASK_GENERATOR

    if _MASK_GENERATOR is not None:
        return _MASK_GENERATOR

    os.makedirs(os.path.dirname(CHECKPOINT_PATH), exist_ok=True)
    if not os.path.exists(CHECKPOINT_PATH):
        print(f"Downloading MobileSAM checkpoint from {CHECKPOINT_URL}...")
        urllib.request.urlretrieve(CHECKPOINT_URL, CHECKPOINT_PATH)
        print("MobileSAM download complete.")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    mobile_sam_model = sam_model_registry["vit_t"](checkpoint=CHECKPOINT_PATH)
    mobile_sam_model.to(device=device)
    mobile_sam_model.eval()

    # Configure automatic mask generator for CPU inference efficiency
    _MASK_GENERATOR = SamAutomaticMaskGenerator(
        model=mobile_sam_model,
        points_per_side=12,  # 12x12 prompt grid per tile for high speed & precision
        pred_iou_thresh=0.82,
        stability_score_thresh=0.85,
        crop_n_layers=0,
        min_mask_region_area=30,  # filter out noise pixels
    )
    _MODEL_INSTANCE = mobile_sam_model
    return _MASK_GENERATOR


_DEEPFOREST_MODEL = None

def get_deepforest_model():
    """
    Lazy-load DeepForest neural RGB tree crown object detector.
    """
    global _DEEPFOREST_MODEL
    if _DEEPFOREST_MODEL is None:
        try:
            from deepforest import main as df_main
            df = df_main.deepforest()
            _DEEPFOREST_MODEL = df
        except Exception as e:
            print(f"DeepForest initialization fallback: {e}")
            _DEEPFOREST_MODEL = False
    return _DEEPFOREST_MODEL if _DEEPFOREST_MODEL is not False else None


def run_deepforest_trees(tile_rgb: np.ndarray, transform, tile_path: str = None) -> list[dict]:
    """
    Extract neural tree crown bounding box polygons using DeepForest model.
    """
    df_model = get_deepforest_model()
    if df_model is None:
        return []

    try:
        if tile_path and os.path.exists(tile_path):
            boxes = df_model.predict_image(path=tile_path)
        else:
            img_float = (tile_rgb.astype("float32") / 255.0)
            boxes = df_model.predict_image(image=img_float)
    except Exception as e:


        print(f"DeepForest inference warning: {e}")
        return []

    if boxes is None or len(boxes) == 0:
        return []

    tree_features = []
    for idx, row in boxes.iterrows():
        score = float(row["score"]) if "score" in row else float(row.get("confidence", 0.85))
        if score < 0.35:
            continue

        xmin, ymin, xmax, ymax = float(row["xmin"]), float(row["ymin"]), float(row["xmax"]), float(row["ymax"])
        x1, y1 = rasterio.transform.xy(transform, ymin, xmin)
        x2, y2 = rasterio.transform.xy(transform, ymax, xmax)

        poly_coords = [[
            [x1, y1], [x2, y1], [x2, y2], [x1, y2], [x1, y1]
        ]]

        poly = shape({"type": "Polygon", "coordinates": poly_coords})
        if not poly.is_valid:
            poly = poly.buffer(0)

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": poly_coords
            },
            "properties": {
                "classification": "tree",
                "feature_type": "tree",
                "confidence": round(score, 2),
                "classification_method": "deepforest_neural",
                "area_m2": round(float(poly.area * 111000 * 111000), 1)
            }
        }
        tree_features.append(feature)

    return tree_features


def classify_mask_heuristic(

    mask_bool: np.ndarray,
    bbox: list[int],
    area: int,
    image_rgb: np.ndarray,
) -> tuple[str, float]:
    """
    Classify a segmented mask into semantic categories ('water', 'farm', 'building', or 'unclassified').

    Returns:
        tuple[feature_type, confidence_multiplier]
        For 'unclassified' features, confidence_multiplier is 0.5 to visibly reflect lower certainty.

    HEURISTIC LOGIC COMPARISON:
    - Farm / Agriculture Check: Uses Excess Green Index (ExG = 2G - R - B > 15.0 or green dominance).
    - Water Check: Uses relative channel dominance (Blue and Green both exceed Red by a margin).
    - Building Check: Uses compact rectangular aspect ratio (0.35 <= aspect_ratio <= 2.85) and rectangularity (> 0.45).
    - Default Fallback: Explicit 'unclassified' category with 0.5 confidence penalty multiplier.

    KNOWN LIMITATION (WATER VS SHADOW AMBIGUITY):
    Dark shadow regions (such as mountain shadows, building shadows, or dense forest canopy shadows)
    exhibit low red reflectance and low overall brightness, mimicking natural dark water bodies in RGB space.
    True disambiguation requires Near-Infrared (NIR) band data for NDWI calculation or elevation analysis.
    """
    x, y, w, h = bbox
    aspect_ratio = float(w) / max(float(h), 1.0)
    rectangularity = float(area) / max(float(w * h), 1.0)

    mask_pixels = image_rgb[mask_bool]
    if mask_pixels.size == 0:
        return "unclassified", 0.5

    mean_r = float(np.mean(mask_pixels[:, 0]))
    mean_g = float(np.mean(mask_pixels[:, 1]))
    mean_b = float(np.mean(mask_pixels[:, 2]))

    # Water Heuristic: Relative Blue/Green channel dominance over Red
    if (mean_b > mean_r + 3.0 and mean_g > mean_r) or (mean_b > mean_r and mean_g > mean_r + 3.0):
        return "water", 1.0

    exg = (2.0 * mean_g) - mean_r - mean_b
    mean_brightness = (mean_r + mean_g + mean_b) / 3.0

    # Road Heuristic (FIXED): Neutral asphalt/dirt corridors — elongated OR near-square compact
    # Relaxed from >3.2 to >2.5; also catch near-square road patches (0.5-2.0 AR) that are gray
    is_neutral_gray = abs(mean_r - mean_g) < 15.0 and abs(mean_g - mean_b) < 15.0 and 35.0 <= mean_brightness <= 190.0
    is_elongated = aspect_ratio > 2.5 or aspect_ratio < 0.4
    if is_neutral_gray and (is_elongated or (rectangularity > 0.55 and exg < 5.0 and area < 20000)):
        return "road", 0.88

    # Tree Crown Heuristic (FIXED — runs BEFORE farm to prevent canopy absorption):
    # Small-to-medium compact green blobs (individual crowns or crown clusters).
    # Key differentiator from farm: much smaller area (< 25000 m² proxy pixels) and higher ExG.
    is_strongly_green = exg > 18.0 or (mean_g > mean_r + 8.0 and mean_g > mean_b + 8.0)
    is_compact_canopy = area < 30000 and 0.25 <= rectangularity <= 1.0
    if is_strongly_green and is_compact_canopy:
        return "tree", 0.90

    # Farm / Agriculture Heuristic: Broad green fields (larger areas, lower ExG threshold)
    if exg > 10.0 or (mean_g > mean_r + 4.0 and mean_g > mean_b + 4.0):
        return "farm", 1.0

    # Structural / Building Heuristic: Aspect ratio & high rectangularity
    if 0.35 <= aspect_ratio <= 2.85 and rectangularity > 0.45 and mean_brightness > 45:
        return "building", 1.0

    # Fallback: explicit 'unclassified' with 0.5 confidence penalty multiplier
    return "unclassified", 0.5




def _deduplicate_features(raw_features: list[dict], iou_threshold: float = 0.4) -> list[dict]:
    """
    Deduplicate overlapping candidate features generated across adjacent tile margins.
    Uses Non-Maximum Suppression (NMS) based on spatial Intersection-over-Union (IoU).
    Higher confidence features are retained; redundant duplicates in overlap zones are dropped.
    """
    if not raw_features:
        return []

    # Sort candidates by confidence descending
    sorted_candidates = sorted(raw_features, key=lambda f: f["properties"]["confidence"], reverse=True)
    accepted_features = []
    accepted_polys = []

    for candidate in sorted_candidates:
        cand_geom = shapely.geometry.shape(candidate["geometry"])
        cand_type = candidate["properties"]["feature_type"]

        is_duplicate = False
        for accepted_poly, accepted_type in accepted_polys:
            if not cand_geom.bounds:
                continue

            if cand_geom.intersects(accepted_poly):
                try:
                    inter_area = cand_geom.intersection(accepted_poly).area
                    if inter_area > 0:
                        union_area = cand_geom.area + accepted_poly.area - inter_area
                        iou = inter_area / union_area if union_area > 0 else 0.0
                        ioa = inter_area / min(cand_geom.area, accepted_poly.area)

                        if iou > iou_threshold or ioa > 0.6:
                            is_duplicate = True
                            break
                except Exception:
                    pass

        if not is_duplicate:
            accepted_features.append(candidate)
            accepted_polys.append((cand_geom, cand_type))

    return accepted_features


def run_extraction(
    bounds: list[float],
    image_path: str | None = None,
    progress_callback: Any | None = None,
) -> dict[str, Any]:

    """
    Run MobileSAM feature extraction on an orthophoto raster using native-resolution tiled inference.

    bounds = [minx, miny, maxx, maxy] in EPSG:4326 (lon/lat).
    image_path = Optional explicit path to the GeoTIFF raster file.

    If image_path is not provided, searches the backend uploads/ directory for the latest raster file.
    If no raster file exists, raises FileNotFoundError (causing API callers to return HTTP 400).
    """
    target_path = image_path
    if not target_path or not os.path.exists(target_path):
        if os.path.exists(UPLOADS_DIR):
            files = [
                os.path.join(UPLOADS_DIR, f)
                for f in os.listdir(UPLOADS_DIR)
                if f.lower().endswith((".tif", ".tiff", ".jpg", ".png", ".jpeg"))
            ]
            if files:
                target_path = max(files, key=os.path.getmtime)

    if not target_path or not os.path.exists(target_path):
        raise FileNotFoundError(
            "No valid raster image found for feature extraction. Please upload an orthophoto image first."
        )

    mask_generator = get_mask_generator()
    raw_candidates = []

    # 1. Open raster image with rasterio & calculate native-resolution tiling grid
    with rasterio.open(target_path) as src:
        orig_transform = src.transform
        raster_crs = src.crs or "EPSG:4326"
        orig_w, orig_h = src.width, src.height

        stride = TILE_SIZE - OVERLAP

        col_offsets = list(range(0, orig_w, stride))
        row_offsets = list(range(0, orig_h, stride))

        total_tiles = len(col_offsets) * len(row_offsets)
        print(f"Executing tiled inference ({len(col_offsets)}x{len(row_offsets)} grid = {total_tiles} total tiles)...")

        tile_idx = 0
        for r_idx, r_off in enumerate(row_offsets):
            for c_idx, c_off in enumerate(col_offsets):
                tile_idx += 1
                w_win = min(TILE_SIZE, orig_w - c_off)
                h_win = min(TILE_SIZE, orig_h - r_off)

                win = Window(col_off=c_off, row_off=r_off, width=w_win, height=h_win)
                base_win_transform = window_transform(win, orig_transform)

                print(f"Processing tile {tile_idx}/{total_tiles} (row {r_idx+1}/{len(row_offsets)}, col {c_idx+1}/{len(col_offsets)})...", flush=True)

                # Resample tile if larger than MAX_TILE_INFERENCE_DIM for memory safety
                if max(w_win, h_win) > MAX_TILE_INFERENCE_DIM:
                    scale = MAX_TILE_INFERENCE_DIM / float(max(w_win, h_win))
                    new_w = int(w_win * scale)
                    new_h = int(h_win * scale)

                    data = src.read(
                        window=win,
                        out_shape=(src.count, new_h, new_w),
                        resampling=Resampling.bilinear,
                    )

                    scale_x = w_win / float(new_w)
                    scale_y = h_win / float(new_h)
                    tile_transform = base_win_transform * Affine.scale(scale_x, scale_y)
                else:
                    data = src.read(window=win)
                    tile_transform = base_win_transform

                if data.size == 0 or np.all(data == 0):
                    continue

                count = data.shape[0]
                if count >= 3:
                    tile_rgb = np.stack([data[0], data[1], data[2]], axis=-1)
                elif count == 1:
                    gray = data[0]
                    tile_rgb = np.stack([gray, gray, gray], axis=-1)
                else:
                    tile_rgb = np.moveaxis(data[:3], 0, -1)

                if tile_rgb.dtype != np.uint8:
                    tile_rgb = ((tile_rgb - tile_rgb.min()) / (tile_rgb.max() - tile_rgb.min() + 1e-5) * 255).astype(np.uint8)

                # Skip uniform background tiles
                if np.std(tile_rgb) < 3.0:
                    continue

                # 2. Run DeepForest Neural Tree Crown Detector (if available)
                df_trees = run_deepforest_trees(tile_rgb, tile_transform)
                for df_feat in df_trees:
                    geom = df_feat["geometry"]
                    if str(raster_crs).upper() != "EPSG:4326":
                        geom = transform_geom(raster_crs, "EPSG:4326", geom)
                    df_feat["geometry"] = geom
                    raw_candidates.append(df_feat)

                # 3. Run MobileSAM Automatic Mask Generator on tile
                tile_masks = mask_generator.generate(tile_rgb)


                for mask_info in tile_masks:
                    mask_bool = mask_info["segmentation"]
                    mask_uint8 = mask_bool.astype(np.uint8)

                    raw_confidence = float(mask_info.get("predicted_iou", mask_info.get("stability_score", 0.85)))

                    shape_gen = shapes(mask_uint8, mask=mask_bool, transform=tile_transform)

                    for geom_dict, val in shape_gen:
                        if val == 0:
                            continue

                        if str(raster_crs).upper() != "EPSG:4326":
                            geom_dict = transform_geom(raster_crs, "EPSG:4326", geom_dict)

                        poly = shape(geom_dict)
                        if not poly.is_valid:
                            poly = poly.buffer(0)

                        if poly.is_empty or poly.area < 1e-9:
                            continue

                        # TASK 1 & 2: Classify feature & apply 0.5 confidence penalty for unclassified
                        feature_type, conf_multiplier = classify_mask_heuristic(
                            mask_bool=mask_bool,
                            bbox=mask_info.get("bbox", [0, 0, 0, 0]),
                            area=int(mask_info.get("area", 0)),
                            image_rgb=tile_rgb,
                        )

                        confidence = round(float(np.clip(raw_confidence * conf_multiplier, 0.0, 1.0)), 2)

                        feature = {
                            "type": "Feature",
                            "geometry": shapely.geometry.mapping(poly),
                            "properties": {
                                "feature_type": feature_type,
                                "confidence": confidence,
                                "classification_method": "heuristic",
                            },
                        }
                        raw_candidates.append(feature)

                if progress_callback is not None:
                    try:
                        progress_callback(tile_idx, total_tiles, len(raw_candidates))
                    except Exception:
                        pass

    # 3. TASK 3: Spatial Deduplication across tile overlaps
    deduped_features = _deduplicate_features(raw_candidates, iou_threshold=0.4)

    raw_collection = {"type": "FeatureCollection", "features": deduped_features}
    validated_collection = validate_geojson(raw_collection)
    validated_collection["metadata"] = {
        "width": orig_w,
        "height": orig_h,
        "total_tiles": total_tiles,
        "feature_count": len(validated_collection["features"]),
    }

    return validated_collection


def validate_geojson(geojson_dict: dict[str, Any]) -> dict[str, Any]:
    """
    TASK 4 — Validate GeoJSON FeatureCollection:
      1. Ensure root object is a valid FeatureCollection.
      2. Verify geometry validity (repair with buffer(0) if invalid).
      3. Verify coordinates are in WGS84 EPSG:4326 bounds [-180, 180], [-90, 90].
      4. Ensure no empty or invalid geometries remain.
      5. Ensure every feature contains normalized properties:
         - classification (alias of feature_type)
         - confidence (real SAM predicted IoU quality score)
         - classification_method ("heuristic")
         - area_m2 (calculated geodesic area in square meters)
    """
    if not isinstance(geojson_dict, dict) or geojson_dict.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON output must be a FeatureCollection")

    features = geojson_dict.get("features", [])
    geod = pyproj.Geod(ellps="WGS84")
    validated_features = []

    for f in features:
        if not isinstance(f, dict) or f.get("type") != "Feature":
            continue
        geom_dict = f.get("geometry")
        if not geom_dict:
            continue

        try:
            poly = shape(geom_dict)
        except Exception:
            continue

        if not poly.is_valid:
            poly = poly.buffer(0)

        if poly.is_empty or poly.area < 1e-9:
            continue

        # Coordinate bound check (WGS84 lon/lat)
        minx, miny, maxx, maxy = poly.bounds
        if not (-180.0 <= minx <= 180.0 and -180.0 <= maxx <= 180.0 and -90.0 <= miny <= 90.0 and -90.0 <= maxy <= 90.0):
            continue

        # Calculate geodesic area in square meters
        try:
            area_m2, _ = geod.geometry_area_perimeter(poly)
            area_m2 = round(abs(area_m2), 2)
        except Exception:
            area_m2 = round(poly.area * 1e10, 2)

        props = dict(f.get("properties") or {})
        ftype = props.get("feature_type", props.get("classification", "unclassified"))
        conf = props.get("confidence", 0.5)

        props["classification"] = ftype
        props["feature_type"] = ftype
        props["confidence"] = round(float(conf), 2)
        props["classification_method"] = props.get("classification_method", "heuristic")
        props["area_m2"] = area_m2

        validated_features.append({
            "type": "Feature",
            "geometry": shapely.geometry.mapping(poly),
            "properties": props
        })

    return {
        "type": "FeatureCollection",
        "features": validated_features
    }

