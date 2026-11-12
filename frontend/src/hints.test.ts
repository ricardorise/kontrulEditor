import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { GUIDE_ORDER, HINTS, WORKFLOW } from "./hintsContent";

const files = (dir: string): string[] => readdirSync(dir, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? files(join(dir, e.name)) : e.name.endsWith(".tsx") ? [join(dir, e.name)] : []));
const used = new Set<string>();
for (const f of files("src")) for (const m of readFileSync(f, "utf8").matchAll(/<Hint id="([a-z_]+)"/g)) used.add(m[1]);

describe("balões de dica", () => {
  it("todo <Hint id> usado na tela tem conteúdo", () => {
    const missing = [...used].filter((id) => !HINTS[id]);
    expect(missing).toEqual([]);
  });
  it("o Guia cobre todas as dicas e só referencia dicas existentes", () => {
    expect(GUIDE_ORDER.filter((id) => !HINTS[id])).toEqual([]);
    expect(Object.keys(HINTS).filter((id) => !GUIDE_ORDER.includes(id))).toEqual([]);
    expect(new Set(GUIDE_ORDER).size).toBe(GUIDE_ORDER.length);
  });
  it("toda dica aparece em algum ponto da tela (sem conteúdo órfão)", () => {
    expect(Object.keys(HINTS).filter((id) => !used.has(id))).toEqual([]);
  });
  it("o fluxo básico tem os 7 passos", () => expect(WORKFLOW).toHaveLength(7));
});
