import { useState } from "react";

interface UrlInputBarProps {
  onSubmit: (urls: string[]) => void;
  onScan?: (urls: string[]) => void;
  loading?: boolean;
  submitLabel?: string;
  multiLine?: boolean;
}

/** Single or multi URL input (up to 15 URLs, one per line). */
export default function UrlInputBar({
  onSubmit,
  loading,
  submitLabel = "Run Validation",
  multiLine = true,
}: UrlInputBarProps) {
  const [value, setValue] = useState("");

  const parse = (raw: string): string[] => {
    return raw
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 15);
  };

  const handleSubmit = () => {
    const urls = parse(value);
    if (urls.length === 0) return;
    onSubmit(urls);
  };

  return (
    <div className="url-bar">
      {multiLine ? (
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={"Paste up to 15 URLs, one per line.\nhttps://www.deccanherald.com/..."}
          rows={2}
          style={{
            flex: 1,
            resize: "vertical",
            minHeight: 58,
            padding: "10px 12px",
            borderRadius: "var(--radius)",
            border: "1px solid var(--border)",
            background: "var(--bg-elevated)",
            color: "var(--text)",
            fontSize: 13,
            fontFamily: "var(--mono)",
          }}
        />
      ) : (
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="https://www.deccanherald.com/..."
        />
      )}
      <button className="btn btn-primary" onClick={handleSubmit} disabled={loading}>
        {loading ? "Scanning…" : submitLabel}
      </button>
    </div>
  );
}
