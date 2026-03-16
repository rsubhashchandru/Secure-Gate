"use client";

import { Cpu, Brain } from "lucide-react";

interface EngineSelectorProps {
  selected: "standard" | "custom_biobert";
  onSelect: (engine: "standard" | "custom_biobert") => void;
  customAvailable: boolean;
}

const engines = [
  {
    key: "standard" as const,
    label: "Standard",
    sub: "Presidio Ensemble",
    icon: Cpu,
  },
  {
    key: "custom_biobert" as const,
    label: "Cognitva-Custom",
    sub: "Fine-tuned BioBERT",
    icon: Brain,
  },
];

export function EngineSelector({
  selected,
  onSelect,
  customAvailable,
}: EngineSelectorProps) {
  return (
    <div className="flex items-center gap-2 p-1 bg-zinc-900/60 rounded-lg border border-zinc-800">
      {engines.map((e) => {
        const active = selected === e.key;
        const disabled = e.key === "custom_biobert" && !customAvailable;
        const Icon = e.icon;
        return (
          <button
            key={e.key}
            disabled={disabled}
            onClick={() => onSelect(e.key)}
            className={`
              relative flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium
              transition-all duration-200 select-none
              ${
                active
                  ? "bg-emerald-600/90 text-white shadow-md"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60"
              }
              ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}
            `}
            title={
              disabled
                ? "Custom model not trained yet – run train_biobert.py first"
                : e.sub
            }
          >
            <Icon className="w-4 h-4" />
            <span className="hidden sm:inline">{e.label}</span>
            {e.key === "custom_biobert" && !customAvailable && (
              <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
            )}
          </button>
        );
      })}
    </div>
  );
}
