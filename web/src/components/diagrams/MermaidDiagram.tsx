"use client";
import { useEffect, useId, useState } from "react";

/** Belt and braces: the server already rejects these; never hand Mermaid a directive, link or click handler. */
const FORBIDDEN = /%%\{|\b(click|href|script|init|javascript|callback|call)\b|<\s*[a-z/!?]|:::|@\{|`/i;
const HEADER = /^\s*(?:%%[^\n]*\n\s*)*(flowchart|graph)\b/;

export function isSafeMermaid(source: string): boolean {
  return source.length <= 3000 && HEADER.test(source) && !FORBIDDEN.test(source);
}

let configured = false;

async function loadMermaid() {
  const mermaid = (await import("mermaid")).default;
  if (!configured) {
    // strict: labels are sanitised, click handlers and links are disabled. The source is model output.
    mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: "neutral", flowchart: { htmlLabels: false } });
    configured = true;
  }
  return mermaid;
}

/** Renders a Mermaid flowchart. Calls onError (so the caller can show the board crop) if it can't be drawn. */
export function MermaidDiagram({ source, onError }: { source: string; onError: () => void }) {
  const id = `mermaid-${useId().replace(/[^A-Za-z0-9_-]/g, "")}`;
  const [svg, setSvg] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    if (!isSafeMermaid(source)) {
      onError();
      return;
    }
    loadMermaid()
      .then((m) => m.render(id, source))
      .then((out) => live && setSvg(out.svg))
      .catch(() => live && onError());
    return () => {
      live = false;
    };
  }, [id, source, onError]);

  if (!svg) return <div className="h-24 animate-pulse rounded-md bg-muted" aria-label="Drawing diagram" />;
  // Output of mermaid.render with securityLevel "strict" (sanitised by Mermaid's DOMPurify pass).
  return <div className="flex justify-center [&_svg]:h-auto [&_svg]:max-w-full" data-testid="mermaid-svg" dangerouslySetInnerHTML={{ __html: svg }} />;
}
