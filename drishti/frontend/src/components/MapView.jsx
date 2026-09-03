import { useEffect, useRef } from "react";
import { MapContainer, TileLayer, GeoJSON, ImageOverlay, CircleMarker, Popup, useMap } from "react-leaflet";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const DEFAULT_CENTER = [51.364, 15.860]; // LandCover.ai demo tile (Poland)


const FEATURE_TYPE_COLOR = {
  farm:         { stroke: "#34d399", fill: "#34d399" }, // emerald
  building:     { stroke: "#38bdf8", fill: "#38bdf8" }, // sky
  water:        { stroke: "#60a5fa", fill: "#60a5fa" }, // blue
  unclassified: { stroke: "#94a3b8", fill: "#94a3b8" }, // slate
};

function confidenceOpacity(conf) {
  // High-conf features are more opaque (more visible), low-conf more ghostly
  return 0.15 + (conf ?? 0.5) * 0.45;
}

function styleFeature(feature) {
  const conf = feature.properties?.confidence ?? 0.5;
  const ftype = feature.properties?.feature_type ?? "unclassified";
  const palette = FEATURE_TYPE_COLOR[ftype] ?? FEATURE_TYPE_COLOR.unclassified;
  return {
    color: palette.stroke,
    weight: conf >= 0.8 ? 2 : 1.5,
    fillColor: palette.fill,
    fillOpacity: confidenceOpacity(conf),
    opacity: 0.85,
  };
}

function onEachFeature(feature, layer) {
  const { feature_type, classification, confidence, classification_method, area_m2 } = feature.properties || {};
  const label = classification || feature_type || "unclassified";
  const palette = FEATURE_TYPE_COLOR[label] ?? FEATURE_TYPE_COLOR.unclassified;
  const confPct = confidence != null ? Math.round(confidence * 100) : null;

  let areaStr = "N/A";
  if (area_m2 != null && area_m2 > 0) {
    areaStr = area_m2 >= 10000 ? `${(area_m2 / 10000).toFixed(2)} ha` : `${Math.round(area_m2).toLocaleString()} m²`;
  }

  layer.bindPopup(
    `<div style="font-family: 'Inter', system-ui, sans-serif; font-size: 12px; min-width: 170px;">
      <div style="display:flex; align-items:center; gap:6px; margin-bottom:8px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 6px;">
        <span style="
          width:10px; height:10px; border-radius:50%;
          background:${palette.fill}; display:inline-block; flex-shrink:0;
        "></span>
        <strong style="text-transform:capitalize; font-size:13px; color:#f1f5f9;">
          ${label}
        </strong>
      </div>
      <div style="display:grid; grid-template-columns: auto 1fr; gap:4px 12px; color:#94a3b8;">
        <span>Classification</span>
        <span style="color:#f1f5f9; font-weight:500; text-transform:capitalize;">${label}</span>
        <span>Confidence</span>
        <span style="color:${confPct >= 80 ? '#4ade80' : confPct >= 50 ? '#facc15' : '#f87171'}; font-weight:600;">
          ${confPct != null ? confPct + "%" : "n/a"}
        </span>
        <span>Method</span>
        <span style="color:#cbd5e1;">${classification_method ?? "heuristic"}</span>
        <span>Area</span>
        <span style="color:#cbd5e1; font-weight:500;">${areaStr}</span>
      </div>
    </div>`,
    { className: "drishti-popup" }
  );


  layer.on("mouseover", function () {
    layer.setStyle({ weight: 3, fillOpacity: Math.min(confidenceOpacity(confidence) + 0.2, 0.9) });
  });
  layer.on("mouseout", function () {
    layer.setStyle(styleFeature(feature));
  });
}

// Auto-fit map to bounds when they change
function BoundsFitter({ bounds }) {
  const map = useMap();
  const prevBounds = useRef(null);
  useEffect(() => {
    if (!bounds || bounds === prevBounds.current) return;
    prevBounds.current = bounds;
    const leafletBounds = [
      [bounds[1], bounds[0]],
      [bounds[3], bounds[2]],
    ];
    map.fitBounds(leafletBounds, { padding: [30, 30], maxZoom: 16 });
  }, [bounds, map]);
  return null;
}

export default function MapView({ bounds, geojson, activeLayers, jobId }) {
  const center = bounds
    ? [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    : DEFAULT_CENTER;


  const pointFeatures = (geojson?.features || []).filter((f) => {
    if (f.geometry.type !== "Point") return false;
    const ftype = f.properties?.classification || f.properties?.feature_type || "unclassified";
    return activeLayers ? activeLayers[ftype] !== false : true;
  });

  const shapeFeatures = {
    type: "FeatureCollection",
    features: (geojson?.features || []).filter((f) => {
      if (f.geometry.type === "Point") return false;
      const ftype = f.properties?.classification || f.properties?.feature_type || "unclassified";
      return activeLayers ? activeLayers[ftype] !== false : true;
    }),
  };

  const geojsonKey = `${geojson?.features.length || 0}_${JSON.stringify(activeLayers || {})}`;


  return (
    <>
      <style>{`
        .drishti-popup .leaflet-popup-content-wrapper {
          background: #1e293b;
          border: 1px solid rgba(255,255,255,0.1);
          border-radius: 10px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.5);
          padding: 0;
        }
        .drishti-popup .leaflet-popup-content {
          margin: 12px 14px;
        }
        .drishti-popup .leaflet-popup-tip {
          background: #1e293b;
        }
        .drishti-popup .leaflet-popup-close-button {
          color: #64748b;
        }
      `}</style>
      <MapContainer
        center={center}
        zoom={bounds ? 14 : 12}
        className="h-full w-full"
        zoomControl={true}
      >
        {/* Clean Satellite Base Map */}
        <TileLayer
          attribution='&copy; <a href="https://www.esri.com/">Esri World Imagery</a>'
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          maxZoom={19}
        />


        {/* Actual uploaded satellite orthophoto raster overlay layer */}
        {bounds && (
          <ImageOverlay
            url={`${API_URL}/raster/${jobId || "demo"}`}
            bounds={[
              [bounds[1], bounds[0]],
              [bounds[3], bounds[2]],
            ]}
            opacity={0.88}
          />
        )}

        <BoundsFitter bounds={bounds} />


        {geojson && (
          <GeoJSON
            key={geojsonKey}
            data={shapeFeatures}
            style={styleFeature}
            onEachFeature={onEachFeature}
          />
        )}

        {pointFeatures.map((f, i) => {
          const [lng, lat] = f.geometry.coordinates;
          const conf = f.properties.confidence ?? 0.5;
          const ftype = f.properties.feature_type ?? "unclassified";
          const palette = FEATURE_TYPE_COLOR[ftype] ?? FEATURE_TYPE_COLOR.unclassified;
          return (
            <CircleMarker
              key={i}
              center={[lat, lng]}
              radius={5}
              pathOptions={{
                color: palette.stroke,
                fillColor: palette.fill,
                fillOpacity: 0.7,
                weight: 1.5,
              }}
            >
              <Popup className="drishti-popup">
                <div style={{ fontFamily: "system-ui", fontSize: 12 }}>
                  <strong style={{ textTransform: "capitalize", color: "#f1f5f9" }}>
                    {ftype}
                  </strong>
                  <br />
                  <span style={{ color: "#94a3b8" }}>Confidence: </span>
                  <span style={{ fontWeight: 600, color: "#4ade80" }}>
                    {Math.round(conf * 100)}%
                  </span>
                </div>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </>
  );
}
