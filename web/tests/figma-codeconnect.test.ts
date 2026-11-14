import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const dir = join(__dirname, "../src/figma");

describe("Figma Code Connect (E-5)", () => {
  const files = readdirSync(dir).filter((f) => f.endsWith(".figma.ts"));
  it("maps the main components", () => {
    const names = files.map((f) => f.replace(".figma.ts", ""));
    for (const n of ["Button", "StatusPill", "SourceChip", "NoteBullet", "BoardSnapshot", "SuggestionCard", "ChatMessage", "Sidebar"]) expect(names).toContain(n);
  });
  for (const f of files) {
    it(`${f} points at a figma node and an existing component source`, () => {
      const src = readFileSync(join(dir, f), "utf8");
      expect(src).toMatch(/url=https:\/\/www\.figma\.com\/design\/[A-Za-z0-9]+\/.+node-id=\d+-\d+/);
      const m = src.match(/source=(\S+)/);
      expect(m, "source= header").toBeTruthy();
      expect(existsSync(join(__dirname, "../..", m![1]!))).toBe(true);
      const imp = src.match(/import \{ (\w+) \} from "@\/components\/(\w+)"/);
      expect(imp, "component import").toBeTruthy();
      expect(existsSync(join(__dirname, "../src/components", `${imp![2]}.tsx`))).toBe(true);
    });
  }
});
