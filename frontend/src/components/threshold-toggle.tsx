"use client";

import { useState } from "react";
import { Settings2, AlertTriangle } from "lucide-react";

interface ThresholdToggleProps {
  value: number;
  onChange: (val: number) => void;
}

const PRESETS = [
  { label: "Production", value: 0.98, desc: "Strict – 98% confidence required" },
  { label: "Review", value: 0.90, desc: "High – 90% confidence required" },
  { label: "Testing", value: 0.85, desc: "Medium – 85% for development" },
  { label: "Permissive", value: 0.70, desc: "Low – 70% for rapid testing" },
];

export function ThresholdToggle({ value, onChange }: ThresholdToggleProps) {
  const [open, setOpen] = useState(false);
  const isNonProduction = value < 0.98;

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-6 py-3 flex items-center justify-between hover:bg-secondary/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <Settings2 className="w-4 h-4 text-muted-foreground" />
          <div className="text-left">
            <h3 className="text-xs font-semibold flex items-center gap-2">
              Safety Threshold
              {isNonProduction && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px] font-semibold">
                  <AlertTriangle className="w-3 h-3" />
                  NON-PRODUCTION
                </span>
              )}
            </h3>
            <p className="text-[11px] text-muted-foreground">
              Current: {(value * 100).toFixed(0)}% confidence gate
            </p>
          </div>
        </div>
        <span className="text-xs text-muted-foreground">
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="border-t border-border px-6 py-4 space-y-3">
          {/* Preset buttons */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                onClick={() => onChange(p.value)}
                className={`
                  rounded-lg border p-3 text-left transition-all text-xs
                  ${
                    Math.abs(value - p.value) < 0.001
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
                  }
                `}
              >
                <div className="font-semibold">{p.label}</div>
                <div className="text-[10px] mt-0.5 opacity-80">{p.desc}</div>
              </button>
            ))}
          </div>

          {/* Slider */}
          <div className="flex items-center gap-4">
            <input
              type="range"
              min="0.50"
              max="1.00"
              step="0.01"
              value={value}
              onChange={(e) => onChange(parseFloat(e.target.value))}
              className="flex-1 accent-primary h-1.5"
            />
            <span className="text-sm font-mono font-semibold text-foreground min-w-[4rem] text-right">
              {(value * 100).toFixed(0)}%
            </span>
          </div>

          {isNonProduction && (
            <p className="text-[10px] text-amber-400/80 flex items-center gap-1.5">
              <AlertTriangle className="w-3 h-3 flex-shrink-0" />
              Lowering the threshold may allow insufficiently de-identified documents through.
              Do not use in production.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
