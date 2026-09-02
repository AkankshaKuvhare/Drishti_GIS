import { useState } from "react";
import UploadPanel from "./components/UploadPanel.jsx";
import MapView from "./components/MapView.jsx";

export default function App() {
  const [job, setJob] = useState(null);       // { job_id, filename, bounds, crs }
  const [geojson, setGeojson] = useState(null);
  const [jobStatus, setJobStatus] = useState(null); // live status from /status/{job_id}
  const [mapKey, setMapKey] = useState(0);

  function handleUploaded(data) {
    setJob(data);
    setGeojson(null);
    setJobStatus(null);
    setMapKey((k) => k + 1);
  }

  function handleOpenInMap() {
    setMapKey((k) => k + 1);
  }

  return (
    <div className="h-screen w-screen flex bg-ink">
      <UploadPanel
        job={job}
        geojson={geojson}
        jobStatus={jobStatus}
        onUploaded={handleUploaded}
        onExtracted={(data) => setGeojson(data)}
        onStatusUpdate={(st) => setJobStatus(st)}
        onOpenInMap={handleOpenInMap}
      />
      <div className="flex-1 relative">
        <MapView key={mapKey} bounds={job?.bounds} geojson={geojson} />
        
        {/* Floating feature count badge when extraction is running */}
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

        {/* Floating completion badge */}
        {jobStatus?.status === "completed" && geojson && (
          <div className="absolute top-4 left-1/2 -translate-x-1/2 z-[1000] bg-emerald-500/20 backdrop-blur border border-emerald-500/30 rounded-full px-4 py-2 flex items-center gap-2 shadow-xl">
            <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/>
            </svg>
            <span className="text-xs font-semibold text-emerald-300">
              {jobStatus.features_found} features extracted · click any polygon for details
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
