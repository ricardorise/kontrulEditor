import { describe, expect, it } from "vitest";
import { keptFraction, nextKept, outputToSource, removedRanges, snap, sourceToOutput, fmtTime } from "./timelineMath";
import type { TimelineDoc } from "./types";

const clip = (id: string, a: number, b: number, start: number) => ({
  id, asset_id: "A", track_id: "main", source_in_ms: a, source_out_ms: b, timeline_start_ms: start, duration_ms: b - a, mode: "main" as const, audio_policy: "original",
});
// 0–10s mantido, 10–20s cortado, 20–60s mantido
const doc: TimelineDoc = { schema: 1, tracks: [], duration_ms: 50000, clips: [clip("1", 0, 10000, 0), clip("2", 20000, 60000, 10000)] };

describe("timelineMath", () => {
  it("mapeia origem↔saída", () => {
    expect(sourceToOutput(doc, "A", 25000)).toBe(15000);
    expect(sourceToOutput(doc, "A", 15000)).toBeNull();
    expect(outputToSource(doc, 15000)).toEqual({ assetId: "A", ms: 25000 });
    expect(outputToSource(doc, 50000)).toBeNull();
  });
  it("lista os trechos removidos, inclusive nas bordas", () => {
    expect(removedRanges(doc, "A", 60000)).toEqual([[10000, 20000]]);
    expect(removedRanges(doc, "A", 70000)).toEqual([[10000, 20000], [60000, 70000]]);
  });
  it("fração mantida de um intervalo", () => {
    expect(keptFraction(doc, "A", 12000, 18000)).toBe(0);
    expect(keptFraction(doc, "A", 5000, 15000)).toBe(0.5);
    expect(keptFraction(doc, "A", 30000, 40000)).toBe(1);
  });
  it("pula cortes na reprodução do editado", () => {
    expect(nextKept(doc, "A", 5000)).toEqual({ inKept: true, jumpTo: null });
    expect(nextKept(doc, "A", 12000)).toEqual({ inKept: false, jumpTo: 20000 });
    expect(nextKept(doc, "A", 60000)).toEqual({ inKept: false, jumpTo: null });
  });
  it("snap respeita o limiar", () => {
    expect(snap(1040, [1000, 2000], 50)).toBe(1000);
    expect(snap(1100, [1000, 2000], 50)).toBe(1100);
  });
  it("formata tempo", () => {
    expect(fmtTime(65400)).toBe("01:05.4");
    expect(fmtTime(0)).toBe("00:00.0");
    expect(fmtTime(9799, 0)).toBe("00:10");
  });
});
