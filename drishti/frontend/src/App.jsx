import { useState, useMemo } from "react";
import UploadPanel from "./components/UploadPanel.jsx";
import MapView from "./components/MapView.jsx";
import AttributeTable from "./components/AttributeTable.jsx";

export default function App() {
  const [job, setJob] = useState(null);
  const [geojson, setGeojson] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [mapKey, setMapKey] = useState(0);
  const [minConfidence, setMinConfidence] = useState(0);

  const [activeLayers, setActiveLayers] = useState({
    farm: true, building: true, water: true,
    unclassified: true, tree: true, road: true,
  });

  // Item 5: filter features by confidence AND active layer — shared by Map & AttributeTable
  const filteredGeojson = useMemo(() => {
    if (!geojson) return null;
    const filtered = (geojson.features || []).filter((f) => {
      const props = f.properties || {};
      const ftype = props.classification || props.feature_type || "unclassified";
      const conf = props.confidence ?? 0.85;
      return conf >= minConfidence && activeLayers[ftype] !== false;
    });
    return { ...geojson, features: filtered };
  }, [geojson, minConfidence, activeLayers]);

  // Item 6: local reassignment updates geojson state immediately
  function handleReassignClass(featureId, newClass) {
    setGeojson((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        features: prev.features.map((f) => {
          const props = f.properties || {};
          if ((props.id || f.id) === featureId) {
            return {
              ...f,
              properties: { ...props, classification: newClass, feature_type: newClass },
            };
          }
          return f;
        }),
      };
    });
  }

  function handleUploaded(data) {
    setJob(data);
    setGeojson(null);
    setJobStatus(null);
    setMapKey((k) => k + 1);
  }

  function handleOpenInMap() { setMapKey((k) => k + 1); }
  function handleToggleLayer(layerKey) {
    setActiveLayers((prev) => ({ ...prev, [layerKey]: !prev[layerKey] }));
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-ink">
      <div className="flex flex-1 overflow-hidden">
        <UploadPanel
          job={job}
          geojson={geojson}
          jobStatus={jobStatus}
          activeLayers={activeLayers}
          minConfidence={minConfidence}
          onUploaded={handleUploaded}
          onExtracted={(data) => setGeojson(data)}
          onStatusUpdate={(st) => setJobStatus(st)}
          onOpenInMap={handleOpenInMap}
          onToggleLayer={handleToggleLayer}
          onConfidenceChange={setMinConfidence}
        />
        <div className="flex-1 relative">
          <MapView
            key={mapKey}
            bounds={job?.bounds}
            geojson={filteredGeojson}
            activeLayers={activeLayers}
            jobId={job?.job_id || "demo"}
            onReassignClass={handleReassignClass}
          />

          {/* Processing badge */}
          {jobStatus?.status === "processing" && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-[1000] bg-ink/90 backdrop-blur border border-white/10 rounded-full px-4 py-2 flex items-center gap-2.5 shadow-xl">
              <svg className="w-4 h-4 animate-spin text-accent" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              <span className="text-xs font-medium text-slate-300">
                MobileSAM running — tile{" "}
                <span className="text-accent font-bold">{jobStatus.current_tile}</span>
                {jobStatus.total_tiles > 0 && (
                  <> of <span className="text-accent font-bold">{jobStatus.total_tiles}</span></>
                )}
                {jobStatus.features_found > 0 && (
                  <> · <span className="text-white font-semibold">{jobStatus.features_found}</span> features</>
                )}
              </span>
            </div>
          )}

          {/* Completion badge */}
          {jobStatus?.status === "completed" && geojson && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-[1000] bg-emerald-500/20 backdrop-blur border border-emerald-500/30 rounded-full px-4 py-2 flex items-center gap-2 shadow-xl">
              <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/>
              </svg>
              <span className="text-xs font-semibold text-emerald-300">
                {filteredGeojson?.features?.length ?? 0} features visible · click any polygon for details
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Item 4: Attribute Table — slide-up bottom panel, shown after extraction */}
      {filteredGeojson && filteredGeojson.features?.length > 0 && (
        <AttributeTable
          features={filteredGeojson.features}
          onReassignClass={handleReassignClass}
        />
      )}
    </div>
  );
}
