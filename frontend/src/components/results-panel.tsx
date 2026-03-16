import {
  Download,
  Lock,
  ShieldCheck,
  Eye,
  EyeOff,
  FileText,
  Clock,
  ScanSearch,
  UserCheck,
  Cpu,
  FileJson,
  Brain,
} from "lucide-react";
import type { DeidentifyResponse } from "@/app/page";

interface ResultsPanelProps {
  result: DeidentifyResponse;
  onDownload: () => void;
  onDownloadMetadata?: () => void;
  onReviewUnlock?: () => void;
}

export function ResultsPanel({
  result,
  onDownload,
  onDownloadMetadata,
  onReviewUnlock,
}: ResultsPanelProps) {
  const isUnlocked = result.status === "UNLOCKED";

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* Header bar */}
      <div
        className={`px-6 py-4 flex items-center justify-between flex-wrap gap-3 ${
          isUnlocked
            ? "bg-emerald-500/10 border-b border-emerald-500/20"
            : "bg-red-500/10 border-b border-red-500/20"
        }`}
      >
        <div className="flex items-center gap-3">
          {isUnlocked ? (
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
          ) : (
            <Lock className="w-5 h-5 text-red-400" />
          )}
          <div>
            <h3 className="text-sm font-semibold">
              {isUnlocked ? "De-Identification Complete" : "Review Required"}
            </h3>
            <p className="text-xs text-muted-foreground">{result.message}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* PHI JSON download – always available */}
          {onDownloadMetadata && (
            <button
              onClick={onDownloadMetadata}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all border border-border text-muted-foreground hover:text-foreground hover:border-primary/40"
              title="Download PHI metadata JSON"
            >
              <FileJson className="w-4 h-4" />
              PHI JSON
            </button>
          )}
          {/* Review & Unlock button – only shown when LOCKED */}
          {!isUnlocked && onReviewUnlock && (
            <button
              onClick={onReviewUnlock}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all bg-amber-600 text-white hover:bg-amber-500 shadow-lg shadow-amber-600/20"
            >
              <UserCheck className="w-4 h-4" />
              Review &amp; Unlock
            </button>
          )}
          <button
            onClick={onDownload}
            disabled={!isUnlocked}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all
              ${
                isUnlocked
                  ? "bg-emerald-600 text-white hover:bg-emerald-500 shadow-lg shadow-emerald-600/20"
                  : "bg-secondary text-muted-foreground cursor-not-allowed"
              }
            `}
          >
            {isUnlocked ? (
              <Download className="w-4 h-4" />
            ) : (
              <Lock className="w-4 h-4" />
            )}
            {isUnlocked ? "Download Redacted PDF" : "Download Locked"}
          </button>
        </div>
      </div>

      {/* Stats grid */}
      <div className="p-6 grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          icon={<Eye className="w-4 h-4 text-blue-400" />}
          label="Entities Detected"
          value={result.total_entities_detected}
        />
        <StatCard
          icon={<EyeOff className="w-4 h-4 text-red-400" />}
          label="Entities Masked"
          value={result.total_entities_masked}
        />
        <StatCard
          icon={<ShieldCheck className="w-4 h-4 text-emerald-400" />}
          label="Entities Kept"
          value={result.total_entities_kept}
        />
        <StatCard
          icon={<FileText className="w-4 h-4 text-purple-400" />}
          label="Pages Processed"
          value={result.pages_processed}
        />
      </div>

      {/* Bottom metadata */}
      <div className="px-6 pb-5 flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" />
          {result.processing_time_ms.toFixed(0)}ms
        </span>
        <span>
          Confidence:{" "}
          <span
            className={
              isUnlocked ? "text-emerald-400 font-semibold" : "text-red-400 font-semibold"
            }
          >
            {(result.ensemble_mean_confidence * 100).toFixed(2)}%
          </span>
        </span>
        {result.ocr_used && (
          <span className="flex items-center gap-1.5">
            <ScanSearch className="w-3.5 h-3.5" />
            OCR Applied
          </span>
        )}
        {result.gpu_accelerated && (
          <span className="flex items-center gap-1.5 text-green-400">
            <Cpu className="w-3.5 h-3.5" />
            GPU Accelerated
          </span>
        )}
        {result.engine_used && (
          <span
            className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold ${
              result.engine_used === "custom_biobert"
                ? "bg-violet-500/20 text-violet-300"
                : "bg-blue-500/20 text-blue-300"
            }`}
          >
            {result.engine_used === "custom_biobert" ? (
              <Brain className="w-3 h-3" />
            ) : (
              <Cpu className="w-3 h-3" />
            )}
            {result.engine_used === "custom_biobert"
              ? "Cognitva-Custom"
              : "Standard"}
          </span>
        )}
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="bg-secondary/30 rounded-lg p-4">
      <div className="flex items-center gap-2 mb-2">{icon}</div>
      <p className="text-2xl font-bold">{value}</p>
      <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
    </div>
  );
}
