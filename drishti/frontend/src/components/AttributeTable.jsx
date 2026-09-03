import { useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const CATEGORIES = ["farm", "building", "water", "tree", "road", "unclassified"];

export default function AttributeTable({ features, onReassignClass }) {
  const [sortField, setSortField] = useState("confidence");
  const [sortDir, setSortDir] = useState("desc");
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedType, setSelectedType] = useState("all");

  if (!features || features.length === 0) return null;

  // Filter features
  const filtered = features.filter((f) => {
    const props = f.properties || {};
    const ftype = props.classification || props.feature_type || "unclassified";
    
    if (selectedType !== "all" && ftype !== selectedType) return false;
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      const matchId = (props.id || "").toLowerCase().includes(term);
      const matchType = ftype.toLowerCase().includes(term);
      if (!matchId && !matchType) return false;
    }
    return true;
  });

  // Sort features
  const sorted = [...filtered].sort((a, b) => {
    const pa = a.properties || {};
    const pb = b.properties || {};
    
    let va = pa[sortField] ?? 0;
    let vb = pb[sortField] ?? 0;
    
    if (typeof va === "string") {
      va = va.toLowerCase();
      vb = (vb || "").toString().toLowerCase();
    }

    if (va < vb) return sortDir === "asc" ? -1 : 1;
    if (va > vb) return sortDir === "asc" ? 1 : -1;
    return 0;
  });

  function handleSort(field) {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  async function handleClassChange(featureId, newClass) {
    if (onReassignClass) {
      onReassignClass(featureId, newClass);
    }
    try {
      await fetch(`${API_URL}/features/${featureId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feature_type: newClass }),
      });
    } catch (e) {
      console.error("Failed to patch feature class:", e);
    }
  }

  return (
    <div className="bg-slate-900/95 border-t border-white/10 p-3 max-h-64 flex flex-col text-xs text-slate-200">
      {/* Table Toolbar */}
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-white/10 gap-4">
        <div className="flex items-center gap-2">
          <span className="font-bold text-accent uppercase tracking-wider text-[11px]">
            GIS Attribute Table ({sorted.length} / {features.length} features)
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Type Filter */}
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
            className="bg-slate-800 border border-white/10 rounded px-2 py-1 text-slate-300 text-xs focus:ring-0 focus:outline-none"
          >
            <option value="all">All Classes</option>
            {CATEGORIES.map((cat) => (
              <option key={cat} value={cat}>
                {cat.toUpperCase()}
              </option>
            ))}
          </select>

          {/* Search Filter */}
          <input
            type="text"
            placeholder="Filter features..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="bg-slate-800 border border-white/10 rounded px-2.5 py-1 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-accent"
          />
        </div>
      </div>

      {/* Scrollable Table View */}
      <div className="overflow-auto flex-1 scrollbar-thin scrollbar-thumb-slate-700">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="text-[11px] font-semibold text-slate-400 border-b border-white/10 select-none bg-slate-800/50 sticky top-0">
              <th onClick={() => handleSort("id")} className="py-1.5 px-2 cursor-pointer hover:text-white">
                Feature ID {sortField === "id" && (sortDir === "asc" ? "▲" : "▼")}
              </th>
              <th onClick={() => handleSort("classification")} className="py-1.5 px-2 cursor-pointer hover:text-white">
                Classification {sortField === "classification" && (sortDir === "asc" ? "▲" : "▼")}
              </th>
              <th onClick={() => handleSort("confidence")} className="py-1.5 px-2 cursor-pointer hover:text-white">
                Confidence % {sortField === "confidence" && (sortDir === "asc" ? "▲" : "▼")}
              </th>
              <th onClick={() => handleSort("area_m2")} className="py-1.5 px-2 cursor-pointer hover:text-white">
                Area (m²) {sortField === "area_m2" && (sortDir === "asc" ? "▲" : "▼")}
              </th>
              <th className="py-1.5 px-2">Method</th>
              <th className="py-1.5 px-2 text-right">Reassign Class</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((f, idx) => {
              const props = f.properties || {};
              const featId = props.id || f.id || `feat-${idx}`;
              const ftype = props.classification || props.feature_type || "unclassified";
              const confPct = Math.round((props.confidence || 0.85) * 100);
              const area = props.area_m2 ? Math.round(props.area_m2).toLocaleString() : "N/A";
              const method = props.classification_method || "heuristic";

              return (
                <tr key={featId} className="border-b border-white/5 hover:bg-white/[0.04] transition-colors">
                  <td className="py-1.5 px-2 font-mono text-[10px] text-slate-400 truncate max-w-[120px]">
                    {featId.slice(0, 12)}…
                  </td>
                  <td className="py-1.5 px-2 font-medium capitalize">
                    <span
                      className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${
                        ftype === "farm"
                          ? "bg-emerald-500/20 text-emerald-300"
                          : ftype === "building"
                          ? "bg-sky-500/20 text-sky-300"
                          : ftype === "water"
                          ? "bg-blue-500/20 text-blue-300"
                          : ftype === "tree"
                          ? "bg-emerald-600/20 text-emerald-400"
                          : ftype === "road"
                          ? "bg-amber-500/20 text-amber-300"
                          : "bg-slate-500/20 text-slate-400"
                      }`}
                    >
                      {ftype}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 font-medium">
                    <span
                      className={
                        confPct >= 80 ? "text-emerald-400" : confPct >= 60 ? "text-amber-400" : "text-red-400"
                      }
                    >
                      {confPct}%
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-slate-300">{area}</td>
                  <td className="py-1.5 px-2 text-slate-400 text-[10px]">{method}</td>
                  <td className="py-1.5 px-2 text-right">
                    {/* Item 6: Class Reassignment Dropdown */}
                    <select
                      value={ftype}
                      onChange={(e) => handleClassChange(featId, e.target.value)}
                      className="bg-slate-800 border border-white/10 rounded px-1.5 py-0.5 text-[11px] text-slate-200 focus:outline-none focus:border-accent cursor-pointer"
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
