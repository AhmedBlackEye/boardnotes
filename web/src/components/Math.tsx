import katex from "katex";

/** Renders LaTeX with KaTeX. Bad input is shown as red source text instead of throwing. */
export function Math({ latex, display = false, className }: { latex: string; display?: boolean; className?: string }) {
  const html = katex.renderToString(latex, {
    throwOnError: false,
    displayMode: display,
    output: "html",
    // Formulas come from board readings and student fixes: no \href or \url, and bounded size and macro expansion.
    trust: false,
    strict: "ignore",
    maxSize: 20,
    maxExpand: 1000,
  });
  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />;
}
