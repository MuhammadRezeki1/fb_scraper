/**
 * download.ts — Utility untuk download data sebagai JSON atau CSV
 */

/** Konversi array of object ke CSV string */
function toCSV(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";

  // Kumpulkan semua keys dari semua rows (union)
  const allKeys = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach(k => {
        // Skip nested objects/arrays yang terlalu dalam
        if (typeof row[k] !== "object" || row[k] === null) set.add(k);
        else if (Array.isArray(row[k])) set.add(k); // array tetap disertakan
      });
      return set;
    }, new Set<string>())
  );

  const escape = (val: unknown): string => {
    if (val === null || val === undefined) return "";
    if (typeof val === "object") {
      // Array of primitives: join dengan |
      if (Array.isArray(val)) return `"${val.map(v => String(v ?? "")).join(" | ").replace(/"/g, '""')}"`;
      // Object: JSON stringify
      return `"${JSON.stringify(val).replace(/"/g, '""')}"`;
    }
    const str = String(val);
    if (str.includes(",") || str.includes('"') || str.includes("\n") || str.includes("\r")) {
      return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
  };

  const header = allKeys.join(",");
  const dataRows = rows.map(row =>
    allKeys.map(k => escape(row[k])).join(",")
  );

  return [header, ...dataRows].join("\n");
}

/** Trigger browser download */
function triggerDownload(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);
}

/** Download data sebagai JSON */
export function downloadJSON(data: unknown, filename: string) {
  const content = JSON.stringify(data, null, 2);
  triggerDownload(content, `${filename}.json`, "application/json;charset=utf-8");
}

/** Download data sebagai CSV (flatten satu level) */
export function downloadCSV(data: unknown[], filename: string) {
  // Flatten top-level array
  const rows = data.map(item => {
    if (typeof item !== "object" || item === null) return { value: item };
    return item as Record<string, unknown>;
  });
  const content = "\uFEFF" + toCSV(rows); // BOM untuk Excel agar UTF-8 terbaca
  triggerDownload(content, `${filename}.csv`, "text/csv;charset=utf-8");
}
