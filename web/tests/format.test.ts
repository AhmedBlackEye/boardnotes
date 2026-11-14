import { describe, expect, it } from "vitest";
import { formatAgo, formatClock, formatDuration, formatRange, formatRelativeDay, formatTime, lectureCode, plural } from "@/lib/format";

describe("times are seconds (float), formatted as mm:ss only for display", () => {
  it("formats floats by flooring", () => {
    expect(formatTime(0)).toBe("0:00");
    expect(formatTime(18.5)).toBe("0:18");
    expect(formatTime(59.999)).toBe("0:59");
    expect(formatTime(125.4)).toBe("2:05");
    expect(formatTime(3600)).toBe("1:00:00");
    expect(formatTime(6740)).toBe("1:52:20");
  });
  it("clamps negatives", () => {
    expect(formatTime(-5)).toBe("0:00");
  });
  it("formatClock pads minutes", () => {
    expect(formatClock(65)).toBe("01:05");
    expect(formatClock(3725)).toBe("1:02:05");
  });
  it("formatRange", () => {
    expect(formatRange(0, 760)).toBe("0:00 – 12:40");
  });
  it("formatDuration", () => {
    expect(formatDuration(null)).toBe("–");
    expect(formatDuration(6740)).toBe("1 h 52 min");
    expect(formatDuration(2700)).toBe("45 min");
  });
  it("relative days", () => {
    const now = new Date(2026, 10, 14, 12);
    expect(formatRelativeDay(new Date(2026, 10, 14, 1).toISOString(), now)).toBe("today");
    expect(formatRelativeDay(new Date(2026, 10, 13, 23).toISOString(), now)).toBe("yesterday");
    expect(formatRelativeDay(new Date(2026, 10, 11).toISOString(), now)).toBe("3 days ago");
  });
  it("formatAgo", () => {
    const now = new Date("2026-11-14T12:00:00Z");
    expect(formatAgo("2026-11-14T11:59:30Z", now)).toBe("just now");
    expect(formatAgo("2026-11-14T11:55:00Z", now)).toBe("5 min ago");
    expect(formatAgo("2026-11-14T10:00:00Z", now)).toBe("2 h ago");
    expect(formatAgo("2026-11-14T12:00:30Z", now)).toBe("just now");
  });
  it("plural and lectureCode", () => {
    expect(plural(1, "fix", "fixes")).toBe("1 fix");
    expect(plural(2, "fix", "fixes")).toBe("2 fixes");
    expect(lectureCode("L21 · Eigenvalues")).toBe("L21");
    expect(lectureCode("NoSeparator")).toBe("NoSeparator");
  });
});
