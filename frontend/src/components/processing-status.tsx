import {
  Loader2,
  CheckCircle2,
  Lock,
  AlertTriangle,
  Upload,
} from "lucide-react";
import type { ProcessingState } from "@/app/page";

interface ProcessingStatusProps {
  state: ProcessingState;
  error?: string;
}

const STATUS_MAP: Record<
  Exclude<ProcessingState, "idle">,
  { icon: React.ReactNode; label: string; color: string; desc: string }
> = {
  uploading: {
    icon: <Upload className="w-4 h-4 animate-bounce" />,
    label: "Uploading",
    color: "text-blue-400",
    desc: "Sending file to SecureGate engine...",
  },
  processing: {
    icon: <Loader2 className="w-4 h-4 animate-spin" />,
    label: "Processing",
    color: "text-amber-400",
    desc: "Running Presidio + OpenBioNER ensemble detection & redaction...",
  },
  success: {
    icon: <CheckCircle2 className="w-4 h-4" />,
    label: "Complete – UNLOCKED",
    color: "text-emerald-400",
    desc: "All PHI redacted. Confidence above safety threshold. Ready for download.",
  },
  locked: {
    icon: <Lock className="w-4 h-4" />,
    label: "Complete – LOCKED",
    color: "text-red-400",
    desc: "Confidence below safety threshold (0.98). Download disabled. Manual review required.",
  },
  error: {
    icon: <AlertTriangle className="w-4 h-4" />,
    label: "Error",
    color: "text-red-400",
    desc: "An error occurred during processing.",
  },
};

export function ProcessingStatus({ state, error }: ProcessingStatusProps) {
  if (state === "idle") return null;
  const s = STATUS_MAP[state];

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-3">
        <div className={s.color}>{s.icon}</div>
        <div>
          <p className={`text-sm font-semibold ${s.color}`}>{s.label}</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            {state === "error" && error ? error : s.desc}
          </p>
        </div>
      </div>

      {/* Progress bar for processing states */}
      {(state === "uploading" || state === "processing") && (
        <div className="mt-4 h-1.5 rounded-full bg-secondary overflow-hidden">
          <div
            className={`h-full rounded-full ${
              state === "uploading" ? "bg-blue-500" : "bg-amber-500"
            } animate-pulse`}
            style={{
              width: state === "uploading" ? "30%" : "70%",
              transition: "width 0.5s ease",
            }}
          />
        </div>
      )}
    </div>
  );
}
