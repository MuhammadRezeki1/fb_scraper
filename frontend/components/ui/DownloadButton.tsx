"use client";

import { useState } from "react";
import { Download, FileJson, FileSpreadsheet } from "lucide-react";

type DownloadFormat = "json" | "csv";

interface DownloadButtonProps {
  /** Data to be downloaded */
  data: unknown;
  /** Suggested filename (without extension) */
  filename: string;
  /** Optional label override */
  label?: string;
  /** Optional extra class names */
  className?: string;
}

function convertToCsv(data: unknown): string {
  if (data === null || data === undefined) return "";
  
  // Normalize to array
  let rows: Record<string, unknown>[] = [];
  
  if (Array.isArray(data)) {
    rows = data.map(item => {
      if (typeof item === "object" && item !== null) {
        return item as Record<string, unknown>;
      }
      return { value: item };
    });
  } else if (typeof data === "object") {
    // Single object — wrap in array
    rows = [data as Record<string, unknown>];
  } else {
    return String(data);
  }

  if (rows.length === 0) return "";

  // Collect all unique keys, preserving order
  const keys = new Set<string>();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      keys.add(key);
    }
  }
  const headers = Array.from(keys);
  
  // Escape CSV value
  const esc = (val: unknown): string => {
    if (val === null || val === undefined) return "";
    const str = String(val);
    // If contains comma, quote, or newline, wrap in quotes
    if (str.includes(",") || str.includes('"') || str.includes("\n") || str.includes("\r")) {
      return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
  };

  const lines: string[] = [];
  lines.push(headers.map(h => esc(h)).join(","));
  
  for (const row of rows) {
    const line = headers.map(h => esc(row[h])).join(",");
    lines.push(line);
  }

  return lines.join("\n");
}

function download(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function DownloadButton({ data, filename, label, className = "" }: DownloadButtonProps) {
  const [open, setOpen] = useState(false);

  if (!data) return null;

  const handleDownload = (format: DownloadFormat) => {
    try {
      if (format === "json") {
        const jsonStr = JSON.stringify(data, null, 2);
        download(`${filename}.json`, jsonStr, "application/json");
      } else {
        const csvStr = convertToCsv(data);
        if (!csvStr) {
          console.warn("No CSV data generated");
          return;
        }
        download(`${filename}.csv`, csvStr, "text/csv;charset=utf-8");
      }
    } catch (err) {
      console.error("Download failed:", err);
    }
    setOpen(false);
  };

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen(!open)}
        className={`btn-glass flex items-center gap-2 px-4 py-2 text-sm ${className}`}
        title={label || "Download"}
      >
        <Download size={14} />
        {label || "Download"}
      </button>

      {open && (
        <>
          {/* Backdrop to close on click outside */}
          <div
            className="fixed inset-0 z-10"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 top-full mt-1 z-20 min-w-[140px] rounded-xl overflow-hidden shadow-lg"
            style={{ background: "white", border: "1px solid rgba(0,0,0,0.08)", backdropFilter: "blur(12px)" }}>
            <button
              onClick={() => handleDownload("json")}
              className="w-full flex items-center gap-3 px-4 py-3 text-sm text-left transition-colors"
              style={{ color: "#4a5070" }}
              onMouseEnter={e => e.currentTarget.style.background = "rgba(107,94,199,0.06)"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <FileJson size={15} style={{ color: "#9e6c0a" }} />
              <span>Download JSON</span>
            </button>
            <button
              onClick={() => handleDownload("csv")}
              className="w-full flex items-center gap-3 px-4 py-3 text-sm text-left transition-colors"
              style={{ color: "#4a5070" }}
              onMouseEnter={e => e.currentTarget.style.background = "rgba(107,94,199,0.06)"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <FileSpreadsheet size={15} style={{ color: "#1d7a47" }} />
              <span>Download CSV</span>
            </button>
          </div>
        </>
      )}
    </div>
  );
}