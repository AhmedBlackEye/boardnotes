import { Math as Tex } from "@/components/Math";

/**
 * Renders a tutor answer: paragraphs, with inline maths written as $...$ rendered by KaTeX.
 * Text is rendered as React text (never HTML), so model output can't inject markup.
 * A paragraph starting with "Beyond this lecture:" is shown as a labelled aside.
 */
export function RichAnswer({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return (
    <div className="flex flex-col gap-2">
      {paragraphs.map((p, i) => {
        const beyond = p.startsWith("Beyond this lecture:");
        const body = beyond ? p.slice("Beyond this lecture:".length).trim() : p;
        return (
          <p key={i} className={beyond ? "rounded-md bg-subtle px-2 py-1.5 text-secondary" : undefined}>
            {beyond && <span className="mr-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-tertiary">Beyond this lecture</span>}
            {inline(body)}
          </p>
        );
      })}
    </div>
  );
}

/** Split on $...$ (not $$) and render the maths parts with KaTeX; keep single line breaks. */
export function inline(text: string) {
  const parts = text.split(/(\$[^$\n]+\$)/g);
  return parts.map((part, i) => {
    if (part.length > 2 && part.startsWith("$") && part.endsWith("$")) return <Tex key={i} latex={part.slice(1, -1)} />;
    const lines = part.split("\n");
    return lines.map((line, j) => (
      <span key={`${i}-${j}`}>
        {j > 0 && <br />}
        {line}
      </span>
    ));
  });
}
