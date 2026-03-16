"use client";

import { DeidentifyResponse } from "@/app/page";
import { ArrowRight, BarChart3, Shield, Clock } from "lucide-react";

interface ComparisonCardProps {
  standard: DeidentifyResponse;
  custom: DeidentifyResponse;
}

function MetricRow({
  label,
  icon: Icon,
  stdVal,
  custVal,
  format = "number",
}: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  stdVal: number;
  custVal: number;
  format?: "number" | "percent" | "ms";
}) {
  const diff = custVal - stdVal;
  const better = format === "ms" ? diff < 0 : diff > 0;
  const worse = format === "ms" ? diff > 0 : diff < 0;

  const fmt = (v: number) => {
    if (format === "percent") return `${(v * 100).toFixed(1)}%`;
    if (format === "ms") return `${v.toFixed(0)}ms`;
    return v.toString();
  };

  const fmtDiff = (d: number) => {
    const sign = d > 0 ? "+" : "";
    if (format === "percent") return `${sign}${(d * 100).toFixed(1)}pp`;
    if (format === "ms") return `${sign}${d.toFixed(0)}ms`;
    return `${sign}${d}`;
  };

  return (
    <div className="grid grid-cols-4 gap-2 items-center py-2 border-b border-zinc-800/60 last:border-0">
      <div className="flex items-center gap-2 text-zinc-400 text-sm">
        <Icon className="w-3.5 h-3.5 shrink-0" />
        <span className="truncate">{label}</span>
      </div>
      <div className="text-center text-sm font-mono text-zinc-300">
        {fmt(stdVal)}
      </div>
      <div className="text-center text-sm font-mono text-zinc-300">
        {fmt(custVal)}
      </div>
      <div
        className={`text-center text-xs font-mono ${
          better
            ? "text-emerald-400"
            : worse
            ? "text-red-400"
            : "text-zinc-500"
        }`}
      >
        {diff === 0 ? "—" : fmtDiff(diff)}
      </div>
    </div>
  );
}

export function ComparisonCard({ standard, custom }: ComparisonCardProps) {
  return (
    <div className="bg-zinc-900/70 border border-zinc-800 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-violet-400" />
        <h3 className="text-base font-semibold text-white">
          A/B Engine Comparison
        </h3>
      </div>

      {/* Header */}
      <div className="grid grid-cols-4 gap-2 mb-1 text-xs text-zinc-500 uppercase tracking-wider">
        <span>Metric</span>
        <span className="text-center">Standard</span>
        <span className="text-center">Custom</span>
        <span className="text-center">Delta</span>
      </div>

      <MetricRow
        label="Confidence"
        icon={Shield}
        stdVal={standard.ensemble_mean_confidence}
        custVal={custom.ensemble_mean_confidence}
        format="percent"
      />
      <MetricRow
        label="Entities Found"
        icon={BarChart3}
        stdVal={standard.total_entities_detected}
        custVal={custom.total_entities_detected}
      />
      <MetricRow
        label="Entities Masked"
        icon={Shield}
        stdVal={standard.total_entities_masked}
        custVal={custom.total_entities_masked}
      />
      <MetricRow
        label="Entities Kept"
        icon={ArrowRight}
        stdVal={standard.total_entities_kept}
        custVal={custom.total_entities_kept}
      />
      <MetricRow
        label="Processing"
        icon={Clock}
        stdVal={standard.processing_time_ms}
        custVal={custom.processing_time_ms}
        format="ms"
      />

      <p className="mt-3 text-[11px] text-zinc-600 text-center">
        Upload the same document with each engine to populate both columns
      </p>
    </div>
  );
}
