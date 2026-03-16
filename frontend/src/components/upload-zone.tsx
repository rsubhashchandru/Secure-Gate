"use client";

import { useCallback, useRef, useState } from "react";
import { Upload, FileText, X } from "lucide-react";
import type { ProcessingState } from "@/app/page";

interface UploadZoneProps {
  state: ProcessingState;
  onUpload: (file: File) => void;
  onReset: () => void;
}

export function UploadZone({ state, onUpload, onReset }: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const isProcessing = state === "uploading" || state === "processing";

  const handleFile = useCallback(
    (file: File) => {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        alert("Only PDF files are accepted.");
        return;
      }
      setSelectedFile(file);
      onUpload(file);
    },
    [onUpload]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragActive(false);
      if (e.dataTransfer.files?.[0]) {
        handleFile(e.dataTransfer.files[0]);
      }
    },
    [handleFile]
  );

  const handleReset = () => {
    setSelectedFile(null);
    onReset();
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Upload Document
        </h2>
        {selectedFile && !isProcessing && (
          <button
            onClick={handleReset}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {!selectedFile ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={`
            relative border-2 border-dashed rounded-lg p-10 text-center cursor-pointer
            transition-all duration-200
            ${
              dragActive
                ? "border-primary bg-primary/5 scale-[1.02]"
                : "border-border hover:border-primary/50 hover:bg-primary/5"
            }
          `}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            className="hidden"
          />
          <Upload
            className={`w-10 h-10 mx-auto mb-3 ${
              dragActive ? "text-primary" : "text-muted-foreground"
            }`}
          />
          <p className="text-sm text-foreground font-medium">
            Drop your PDF here or click to browse
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Supports native text & scanned (OCR) PDFs
          </p>
        </div>
      ) : (
        <div className="flex items-center gap-3 p-4 bg-secondary/30 rounded-lg">
          <FileText className="w-8 h-8 text-primary flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium truncate">{selectedFile.name}</p>
            <p className="text-xs text-muted-foreground">
              {(selectedFile.size / 1024).toFixed(1)} KB
            </p>
          </div>
          {isProcessing && (
            <div className="flex-shrink-0">
              <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
