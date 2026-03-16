"use client";

import { useState, useEffect } from "react";
import { Header } from "@/components/header";
import { UploadZone } from "@/components/upload-zone";
import { ProcessingStatus } from "@/components/processing-status";
import { ResultsPanel } from "@/components/results-panel";
import { AuditTrail } from "@/components/audit-trail";
import { DashboardHistory } from "@/components/dashboard-history";
import { ThresholdToggle } from "@/components/threshold-toggle";
import { EngineSelector } from "@/components/engine-selector";
import { ComparisonCard } from "@/components/comparison-card";

export type ProcessingState =
  | "idle"
  | "uploading"
  | "processing"
  | "success"
  | "locked"
  | "error";

export interface DeidentifyResponse {
  audit_id: string;
  document_name: string;
  status: "UNLOCKED" | "LOCKED";
  ensemble_mean_confidence: number;
  total_entities_detected: number;
  total_entities_masked: number;
  total_entities_kept: number;
  pages_processed: number;
  ocr_used: boolean;
  processing_time_ms: number;
  gpu_accelerated: boolean;
  engine_used: "standard" | "custom_biobert";
  message: string;
}

export interface AuditDetail {
  audit_id: string;
  document_name: string;
  timestamp: string;
  total_entities_detected: number;
  total_entities_masked: number;
  total_entities_kept: number;
  ensemble_mean_confidence: number;
  safety_status: string;
  processing_time_ms: number;
  pages_processed: number;
  ocr_used: boolean;
  detections: {
    entity_type: string;
    text_snippet: string;
    start: number;
    end: number;
    score: number;
    detected_by: string;
    action: string;
  }[];
}

export default function Home() {
  const [state, setState] = useState<ProcessingState>("idle");
  const [result, setResult] = useState<DeidentifyResponse | null>(null);
  const [audit, setAudit] = useState<AuditDetail | null>(null);
  const [error, setError] = useState<string>("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [threshold, setThreshold] = useState(0.98);
  const [engine, setEngine] = useState<"standard" | "custom_biobert">("standard");
  const [customModelAvailable, setCustomModelAvailable] = useState(false);

  // A/B comparison state – store results from both engines
  const [comparisonResults, setComparisonResults] = useState<{
    standard?: DeidentifyResponse;
    custom_biobert?: DeidentifyResponse;
  }>({});

  // Load current threshold + model status on mount
  useEffect(() => {
    fetch("/api/settings/threshold")
      .then((r) => r.json())
      .then((d) => setThreshold(d.threshold))
      .catch(() => {});
    fetch("/api/model/status")
      .then((r) => r.json())
      .then((d) => setCustomModelAvailable(d.custom_engine?.available ?? false))
      .catch(() => {});
  }, []);

  const handleThresholdChange = async (val: number) => {
    try {
      const res = await fetch("/api/settings/threshold", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold: val }),
      });
      if (res.ok) {
        const data = await res.json();
        setThreshold(data.threshold);
      }
    } catch {}
  };

  const handleUpload = async (file: File) => {
    setState("uploading");
    setResult(null);
    setAudit(null);
    setError("");

    const formData = new FormData();
    formData.append("file", file);

    try {
      setState("processing");
      const res = await fetch(`/api/deidentify?engine=${engine}`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        // Handle both JSON and plain-text error responses
        const text = await res.text();
        let detail = "Processing failed";
        try {
          const errJson = JSON.parse(text);
          detail = errJson.detail || detail;
        } catch {
          detail = text || `Server error (${res.status})`;
        }
        throw new Error(detail);
      }

      const data: DeidentifyResponse = await res.json();
      setResult(data);
      setComparisonResults((prev) => ({ ...prev, [engine]: data }));

      // Fetch full audit trail
      const auditRes = await fetch(`/api/audit/${data.audit_id}`);
      if (auditRes.ok) {
        const auditData: AuditDetail = await auditRes.json();
        setAudit(auditData);
      }

      setState(data.status === "UNLOCKED" ? "success" : "locked");
      setRefreshKey((k) => k + 1);
    } catch (e: any) {
      setError(e.message || "An unexpected error occurred");
      setState("error");
    }
  };

  const handleDownload = async () => {
    if (!result) return;
    const res = await fetch(`/api/download/${result.audit_id}`);
    if (!res.ok) {
      const text = await res.text();
      let detail = "Download failed";
      try { detail = JSON.parse(text).detail || detail; } catch {}
      alert(detail);
      return;
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `redacted_${result.document_name}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  const handleDownloadMetadata = async () => {
    if (!result) return;
    const res = await fetch(`/api/phi-metadata/${result.audit_id}/download`);
    if (!res.ok) {
      alert("Failed to download PHI metadata");
      return;
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `phi_metadata_${result.document_name.replace(".pdf", "")}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  };

  const handleReviewUnlock = async () => {
    if (!result) return;
    try {
      const res = await fetch(`/api/review/${result.audit_id}`, {
        method: "POST",
      });
      if (res.ok) {
        const data = await res.json();
        // Update result status to UNLOCKED
        setResult((prev) =>
          prev ? { ...prev, status: "UNLOCKED", message: data.message } : prev
        );
        // Refresh audit trail
        const auditRes = await fetch(`/api/audit/${result.audit_id}`);
        if (auditRes.ok) {
          const auditData: AuditDetail = await auditRes.json();
          setAudit(auditData);
        }
        setState("success");
        setRefreshKey((k) => k + 1);
      }
    } catch (e: any) {
      alert(e.message || "Review failed");
    }
  };

  const handleReset = () => {
    setState("idle");
    setResult(null);
    setAudit(null);
    setError("");
  };

  return (
    <>
      <Header />
      <main className="flex-1 container mx-auto px-4 py-8 max-w-7xl">
        {/* Admin Threshold Toggle */}
        <div className="mb-6 flex flex-col sm:flex-row gap-4">
          <ThresholdToggle value={threshold} onChange={handleThresholdChange} />
          <EngineSelector
            selected={engine}
            onSelect={setEngine}
            customAvailable={customModelAvailable}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Left Column – Upload & Status */}
          <div className="lg:col-span-1 space-y-6">
            <UploadZone
              state={state}
              onUpload={handleUpload}
              onReset={handleReset}
            />
            {state !== "idle" && (
              <ProcessingStatus state={state} error={error} />
            )}
          </div>

          {/* Right Column – Results & Audit */}
          <div className="lg:col-span-2 space-y-6">
            {result && (
              <ResultsPanel
                result={result}
                onDownload={handleDownload}
                onDownloadMetadata={handleDownloadMetadata}
                onReviewUnlock={handleReviewUnlock}
              />
            )}
            {comparisonResults.standard && comparisonResults.custom_biobert && (
              <ComparisonCard
                standard={comparisonResults.standard}
                custom={comparisonResults.custom_biobert}
              />
            )}
            {audit && <AuditTrail audit={audit} />}
          </div>
        </div>

        {/* Dashboard History */}
        <div className="mt-12">
          <DashboardHistory refreshKey={refreshKey} />
        </div>
      </main>
    </>
  );
}
