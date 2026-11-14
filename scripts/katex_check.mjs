// Validate LaTeX expressions with KaTeX (the same renderer the web app uses).
// stdin:  JSON array of strings
// stdout: JSON array of {"ok": true} or {"ok": false, "error": "..."} in the same order
// Exits non-zero if KaTeX can't be loaded or the input isn't a JSON array of strings.
import { createRequire } from "node:module";

const require = createRequire(new URL("../web/package.json", import.meta.url));
const katex = require("katex");

let input = "";
for await (const chunk of process.stdin) input += chunk;
const exprs = JSON.parse(input);
if (!Array.isArray(exprs) || !exprs.every((e) => typeof e === "string")) {
  console.error("expected a JSON array of strings");
  process.exit(2);
}

const results = exprs.map((expr) => {
  try {
    katex.renderToString(expr, { throwOnError: true, displayMode: true, strict: "ignore", trust: false });
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err instanceof Error ? err.message : err) };
  }
});
process.stdout.write(JSON.stringify(results));
