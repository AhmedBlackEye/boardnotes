import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mermaidRender = vi.fn(async (_id: string, source: string) => ({ svg: `<svg data-src="${source.length}"><text>flow</text></svg>` }));
vi.mock("mermaid", () => ({ default: { initialize: vi.fn(), render: mermaidRender } }));

import { ChartSvg, isDrawable } from "@/components/diagrams/ChartSvg";
import { DiagramFigure } from "@/components/diagrams/DiagramFigure";
import { isSafeMermaid } from "@/components/diagrams/MermaidDiagram";
import { clipLine, layoutChart, ticks } from "@/components/diagrams/chartGeometry";
import { figuresByBullet } from "@/components/notes/helpers";
import type { ChartSpec } from "@/contracts/ChartSpec";
import type { DiagramFigure as Figure } from "@/contracts/DiagramFigure";
import { DEMO, DETAILS } from "@/mocks/data";

const ROW: ChartSpec = {
  title: "Row picture",
  x_label: "x",
  y_label: "y",
  x_range: [-2, 3],
  y_range: [-1, 3],
  show_axes: true,
  elements: [
    { type: "line", points: [[-1, 0], [1, 1]], label: "x - 2y = -1" },
    { type: "line", points: [[0, 3], [1.5, 0]], label: "2x + y = 3" },
    { type: "point", points: [[1, 1]], label: "(1, 1)" },
  ],
};

const chartFigure: Figure = { kind: "chart", chart: ROW, mermaid: null, caption: "Two lines meet at (1, 1).", redrawn_by_ai: true };

describe("chart geometry", () => {
  it("uses round tick values and clips lines to the plot", () => {
    expect(ticks(-2, 3)).toEqual([-2, -1, 0, 1, 2, 3]);
    expect(clipLine([0, 0], [1, 1], { left: 0, top: 0, right: 10, bottom: 5 })).toEqual([
      [0, 0],
      [5, 5],
    ]);
    expect(clipLine([0, 20], [1, 20], { left: 0, top: 0, right: 10, bottom: 5 })).toBeNull();
  });
  it("lays out every element and keeps lines inside the plot", () => {
    const layout = layoutChart(ROW);
    expect(layout.shapes.map((s) => s.kind)).toEqual(["line", "line", "dot"]);
    for (const s of layout.shapes) {
      if (s.kind !== "line") continue;
      for (const x of [s.x1, s.x2]) expect(x).toBeGreaterThanOrEqual(layout.plot.left - 1e-6);
      for (const y of [s.y1, s.y2]) expect(y).toBeLessThanOrEqual(layout.plot.bottom + 1e-6);
    }
    expect(layout.labels.map((l) => l.text)).toEqual(["x - 2y = -1", "2x + y = 3", "(1, 1)"]);
  });
  it("rejects specs it cannot lay out", () => {
    expect(isDrawable(ROW)).toBe(true);
    expect(isDrawable({ ...ROW, x_range: [3, -2] })).toBe(false);
    expect(isDrawable({ ...ROW, y_range: [0, Number.NaN] })).toBe(false);
    expect(isDrawable(null)).toBe(false);
  });
});

describe("ChartSvg", () => {
  it("renders model text as text, never as markup", () => {
    const evil = { ...ROW, title: "<script>alert(1)</script>", elements: [{ type: "label" as const, points: [[0, 0]], label: "<img src=x onerror=alert(1)>" }] };
    const { container } = render(<ChartSvg spec={evil} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});

describe("DiagramFigure", () => {
  it("labels a redrawn chart and toggles the original crop", () => {
    render(<DiagramFigure figure={chartFigure} boardText="two crossing lines" />);
    expect(screen.getByTestId("chart-svg")).toBeTruthy();
    expect(screen.getByText("Redrawn by AI")).toBeTruthy();
    expect(screen.queryByText("two crossing lines")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "View original" }));
    expect(screen.getByText("two crossing lines")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Hide original" }));
    expect(screen.queryByText("two crossing lines")).toBeNull();
  });
  it("shows only the board crop for crop figures", () => {
    const crop: Figure = { kind: "crop", chart: null, mermaid: null, caption: "A sketch.", redrawn_by_ai: false };
    render(<DiagramFigure figure={crop} boardText="a sketch" snapshotUrl="/snapshots/l/b.jpg" />);
    expect(screen.getByRole("img", { name: "On the board" })).toBeTruthy();
    expect(screen.queryByText("Redrawn by AI")).toBeNull();
    expect(screen.getByTestId("diagram-figure").dataset.kind).toBe("crop");
  });
  it("falls back to the crop when the chart is not drawable", () => {
    render(<DiagramFigure figure={{ ...chartFigure, chart: { ...ROW, x_range: [1, 1] } }} boardText="lines" />);
    expect(screen.queryByTestId("chart-svg")).toBeNull();
    expect(screen.getByText("lines")).toBeTruthy();
  });
  it("renders a safe flowchart with Mermaid", async () => {
    const flow: Figure = { kind: "mermaid", chart: null, mermaid: 'flowchart LR\n  A["a"] --> B["b"]', caption: "Steps.", redrawn_by_ai: true };
    render(<DiagramFigure figure={flow} boardText="steps" />);
    expect(await screen.findByTestId("mermaid-svg")).toBeTruthy();
    expect(screen.getByText("Redrawn by AI")).toBeTruthy();
  });
  it("never hands unsafe Mermaid to the renderer; shows the crop instead", async () => {
    mermaidRender.mockClear();
    const bad: Figure = { kind: "mermaid", chart: null, mermaid: 'flowchart LR\n  A --> B\n  click A "javascript:alert(1)"', caption: "c", redrawn_by_ai: true };
    render(<DiagramFigure figure={bad} boardText="original board" />);
    await act(async () => {});
    expect(mermaidRender).not.toHaveBeenCalled();
    expect(screen.getByText("original board")).toBeTruthy();
    expect(screen.queryByText("Redrawn by AI")).toBeNull();
  });
  it("falls back to the crop when Mermaid fails", async () => {
    mermaidRender.mockRejectedValueOnce(new Error("parse error"));
    const flow: Figure = { kind: "mermaid", chart: null, mermaid: "flowchart LR\n  A -->", caption: "c", redrawn_by_ai: true };
    render(<DiagramFigure figure={flow} boardText="board text" />);
    expect(await screen.findByText("board text")).toBeTruthy();
  });
});

describe("mermaid safety check", () => {
  it.each([
    ['flowchart TD\n  A --> B', true],
    ["graph LR\nA-->B", true],
    ["sequenceDiagram\n A->>B: hi", false],
    ['%%{init: {"securityLevel": "loose"}}%%\nflowchart TD\n A --> B', false],
    ['flowchart TD\n A["<b>x</b>"] --> B', false],
    ["flowchart TD\n A --> B\n click A href", false],
  ])("%s -> %s", (source, ok) => {
    expect(isSafeMermaid(source)).toBe(ok);
  });
});

describe("mock data diagrams", () => {
  it("the demo lecture shows the row picture under the bullet that cites it", () => {
    const figures = figuresByBullet(DEMO);
    const [block] = figures.get("bl_d_2a") ?? [];
    expect(block?.figure?.kind).toBe("chart");
    expect(block?.figure?.chart && isDrawable(block.figure.chart)).toBe(true);
  });
  it("every mock figure is drawable or safe", () => {
    for (const d of Object.values(DETAILS)) {
      for (const b of d.board_blocks) {
        if (b.figure?.kind === "chart") expect(isDrawable(b.figure.chart)).toBe(true);
        if (b.figure?.kind === "mermaid") expect(isSafeMermaid(b.figure.mermaid ?? "")).toBe(true);
      }
    }
  });
});
