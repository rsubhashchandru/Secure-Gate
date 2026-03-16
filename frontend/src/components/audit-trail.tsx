"use client";

import { useState } from "react";
import {
  FileSearch,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  ShieldCheck,
  Brain,
  CheckCircle2,
  XCircle,
  Columns2,
  List,
} from "lucide-react";
import type { AuditDetail } from "@/app/page";

interface AuditTrailProps {
  audit: AuditDetail;
}

const ACTION_COLORS: Record<string, string> = {
  MASKED: "bg-red-500/20 text-red-300 border-red-500/30",
  KEPT: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  AGE_AGGREGATED: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

const SOURCE_ICONS: Record<string, React.ReactNode> = {
  presidio: <ShieldAlert className="w-3 h-3" />,
  openbioner: <Brain className="w-3 h-3" />,
  ensemble: <ShieldCheck className="w-3 h-3" />,
  custom_biobert: <Brain className="w-3 h-3 text-violet-400" />,
};

type ViewMode = "table" | "sidebyside";

export function AuditTrail({ audit }: AuditTrailProps) {
  const [expanded, setExpanded] = useState(true);
  const [filterAction, setFilterAction] = useState<string>("ALL");
  const [viewMode, setViewMode] = useState<ViewMode>("table");
  // Track confirmed/rejected in side-by-side view (local state for visual feedback)
  const [decisions, setDecisions] = useState<Record<number, "confirmed" | "rejected">>({});

  const filteredDetections =
    filterAction === "ALL"
      ? audit.detections
      : audit.detections.filter((d) => d.action === filterAction);

  const maskedDetections = audit.detections.filter((d) => d.action === "MASKED");
  const keptDetections = audit.detections.filter((d) => d.action === "KEPT" || d.action === "AGE_AGGREGATED");

  const handleDecision = (index: number, decision: "confirmed" | "rejected") => {
    setDecisions((prev) => ({ ...prev, [index]: decision }));
  };

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-secondary/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <FileSearch className="w-5 h-5 text-primary" />
          <div className="text-left">
            <h3 className="text-sm font-semibold">
              Anonymization Audit Trail
            </h3>
            <p className="text-xs text-muted-foreground">
              {audit.total_entities_detected} entities &middot; audit{" "}
              {audit.audit_id}
            </p>
          </div>
        </div>
        {expanded ? (
          <ChevronDown className="w-4 h-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="w-4 h-4 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-border">
          {/* Filter bar + view toggle */}
          <div className="px-6 py-3 flex items-center justify-between flex-wrap gap-2 border-b border-border bg-secondary/10">
            <div className="flex items-center gap-2 flex-wrap">
              {["ALL", "MASKED", "KEPT", "AGE_AGGREGATED"].map((f) => (
                <button
                  key={f}
                  onClick={() => setFilterAction(f)}
                  className={`
                    text-xs px-3 py-1 rounded-full border transition-colors
                    ${
                      filterAction === f
                        ? "bg-primary/20 border-primary/40 text-primary"
                        : "border-border text-muted-foreground hover:text-foreground"
                    }
                  `}
                >
                  {f.replace("_", " ")}
                  {f !== "ALL" &&
                    ` (${audit.detections.filter((d) => d.action === f).length})`}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setViewMode("table")}
                className={`p-1.5 rounded transition-colors ${
                  viewMode === "table"
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                title="Table view"
              >
                <List className="w-4 h-4" />
              </button>
              <button
                onClick={() => setViewMode("sidebyside")}
                className={`p-1.5 rounded transition-colors ${
                  viewMode === "sidebyside"
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
                title="Side-by-side review"
              >
                <Columns2 className="w-4 h-4" />
              </button>
            </div>
          </div>

          {viewMode === "table" ? (
            /* ─── Table View ─── */
            <div className="max-h-96 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-card">
                  <tr className="text-left text-muted-foreground border-b border-border">
                    <th className="px-6 py-2.5 font-medium">Entity Type</th>
                    <th className="px-4 py-2.5 font-medium">Snippet</th>
                    <th className="px-4 py-2.5 font-medium">Score</th>
                    <th className="px-4 py-2.5 font-medium">Source</th>
                    <th className="px-4 py-2.5 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDetections.map((d, i) => (
                    <tr
                      key={i}
                      className="border-b border-border/50 hover:bg-secondary/20 transition-colors"
                    >
                      <td className="px-6 py-2.5 font-mono text-foreground">
                        {d.entity_type}
                      </td>
                      <td className="px-4 py-2.5 text-muted-foreground font-mono">
                        {d.text_snippet}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`font-mono ${
                            d.score >= 0.9
                              ? "text-emerald-400"
                              : d.score >= 0.7
                              ? "text-amber-400"
                              : "text-red-400"
                          }`}
                        >
                          {(d.score * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className="inline-flex items-center gap-1 text-muted-foreground">
                          {SOURCE_ICONS[d.detected_by] || null}
                          {d.detected_by}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`inline-block px-2 py-0.5 rounded border text-[10px] font-semibold uppercase ${
                            ACTION_COLORS[d.action] || ""
                          }`}
                        >
                          {d.action}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {filteredDetections.length === 0 && (
                    <tr>
                      <td
                        colSpan={5}
                        className="px-6 py-8 text-center text-muted-foreground"
                      >
                        No detections match the selected filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            /* ─── Side-by-Side Review View ─── */
            <div className="grid grid-cols-2 divide-x divide-border max-h-[500px] overflow-y-auto">
              {/* Left: MASKED entities */}
              <div>
                <div className="px-4 py-2.5 bg-red-500/10 text-xs font-semibold text-red-300 border-b border-border sticky top-0">
                  MASKED ({maskedDetections.length})
                </div>
                <div className="divide-y divide-border/50">
                  {maskedDetections.map((d, i) => {
                    const decision = decisions[i];
                    return (
                      <div
                        key={i}
                        className={`px-4 py-3 text-xs transition-colors ${
                          decision === "confirmed"
                            ? "bg-emerald-500/5"
                            : decision === "rejected"
                            ? "bg-red-500/5"
                            : "hover:bg-secondary/20"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono text-foreground font-medium">
                            {d.entity_type}
                          </span>
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => handleDecision(i, "confirmed")}
                              className={`p-1 rounded transition-colors ${
                                decision === "confirmed"
                                  ? "text-emerald-400 bg-emerald-500/20"
                                  : "text-muted-foreground hover:text-emerald-400"
                              }`}
                              title="Confirm masking"
                            >
                              <CheckCircle2 className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleDecision(i, "rejected")}
                              className={`p-1 rounded transition-colors ${
                                decision === "rejected"
                                  ? "text-red-400 bg-red-500/20"
                                  : "text-muted-foreground hover:text-red-400"
                              }`}
                              title="Reject masking"
                            >
                              <XCircle className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                        <p className="font-mono text-muted-foreground">{d.text_snippet}</p>
                        <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground">
                          <span>
                            Score:{" "}
                            <span
                              className={
                                d.score >= 0.9
                                  ? "text-emerald-400"
                                  : d.score >= 0.7
                                  ? "text-amber-400"
                                  : "text-red-400"
                              }
                            >
                              {(d.score * 100).toFixed(1)}%
                            </span>
                          </span>
                          <span className="inline-flex items-center gap-0.5">
                            {SOURCE_ICONS[d.detected_by] || null}
                            {d.detected_by}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                  {maskedDetections.length === 0 && (
                    <div className="px-4 py-8 text-center text-xs text-muted-foreground">
                      No masked entities.
                    </div>
                  )}
                </div>
              </div>

              {/* Right: KEPT entities */}
              <div>
                <div className="px-4 py-2.5 bg-emerald-500/10 text-xs font-semibold text-emerald-300 border-b border-border sticky top-0">
                  KEPT ({keptDetections.length})
                </div>
                <div className="divide-y divide-border/50">
                  {keptDetections.map((d, i) => (
                    <div
                      key={i}
                      className="px-4 py-3 text-xs hover:bg-secondary/20 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono text-foreground font-medium">
                          {d.entity_type}
                        </span>
                        <span
                          className={`inline-block px-2 py-0.5 rounded border text-[10px] font-semibold uppercase ${
                            ACTION_COLORS[d.action] || ""
                          }`}
                        >
                          {d.action}
                        </span>
                      </div>
                      <p className="font-mono text-muted-foreground">{d.text_snippet}</p>
                      <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground">
                        <span>
                          Score:{" "}
                          <span className="text-emerald-400">
                            {(d.score * 100).toFixed(1)}%
                          </span>
                        </span>
                        <span className="inline-flex items-center gap-0.5">
                          {SOURCE_ICONS[d.detected_by] || null}
                          {d.detected_by}
                        </span>
                      </div>
                    </div>
                  ))}
                  {keptDetections.length === 0 && (
                    <div className="px-4 py-8 text-center text-xs text-muted-foreground">
                      No kept entities.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
