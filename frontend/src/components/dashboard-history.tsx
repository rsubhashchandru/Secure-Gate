"use client";

import { useEffect, useState } from "react";
import { History, ShieldCheck, Lock } from "lucide-react";

interface AuditSummary {
  audit_id: string;
  document_name: string;
  status: string;
  ensemble_mean_confidence: number;
  total_entities_detected: number;
  total_entities_masked: number;
  processing_time_ms: number;
  timestamp: string;
}

export function DashboardHistory({ refreshKey }: { refreshKey: number }) {
  const [audits, setAudits] = useState<AuditSummary[]>([]);

  useEffect(() => {
    fetch("/api/audits")
      .then((r) => r.json())
      .then((data) => setAudits(data))
      .catch(() => {});
  }, [refreshKey]);

  if (audits.length === 0) return null;

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-6 py-4 border-b border-border flex items-center gap-3">
        <History className="w-5 h-5 text-primary" />
        <h3 className="text-sm font-semibold">Processing History</h3>
        <span className="text-xs text-muted-foreground ml-auto">
          {audits.length} document{audits.length !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground border-b border-border">
              <th className="px-6 py-2.5 font-medium">Document</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Confidence</th>
              <th className="px-4 py-2.5 font-medium">Entities</th>
              <th className="px-4 py-2.5 font-medium">Masked</th>
              <th className="px-4 py-2.5 font-medium">Time</th>
              <th className="px-4 py-2.5 font-medium">Processed</th>
            </tr>
          </thead>
          <tbody>
            {audits.map((a) => (
              <tr
                key={a.audit_id}
                className="border-b border-border/50 hover:bg-secondary/20 transition-colors"
              >
                <td className="px-6 py-2.5 font-medium max-w-[200px] truncate">
                  {a.document_name}
                </td>
                <td className="px-4 py-2.5">
                  {a.status === "UNLOCKED" ? (
                    <span className="inline-flex items-center gap-1 text-emerald-400">
                      <ShieldCheck className="w-3 h-3" />
                      UNLOCKED
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 text-red-400">
                      <Lock className="w-3 h-3" />
                      LOCKED
                    </span>
                  )}
                </td>
                <td className="px-4 py-2.5 font-mono">
                  <span
                    className={
                      a.ensemble_mean_confidence >= 0.98
                        ? "text-emerald-400"
                        : "text-red-400"
                    }
                  >
                    {(a.ensemble_mean_confidence * 100).toFixed(2)}%
                  </span>
                </td>
                <td className="px-4 py-2.5">{a.total_entities_detected}</td>
                <td className="px-4 py-2.5">{a.total_entities_masked}</td>
                <td className="px-4 py-2.5">{a.processing_time_ms.toFixed(0)}ms</td>
                <td className="px-4 py-2.5 text-muted-foreground">
                  {new Date(a.timestamp).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
