import { describe, expect, it } from "vitest";
import {
  canConnect,
  compileWorkflow,
  createDefault,
  makeNode,
  parseWorkflow,
} from "./workflow";
describe("workflow integrity", () => {
  it("round-trips custom model IDs, prompts and positions without UI state", () => {
    const workflow = createDefault();
    workflow.nodes[3].data.model = "my-provider/cinematic-model";
    workflow.nodes[3].data.prompt =
      "캐릭터를 바꾸고 원래 움직임은 유지합니다.\nSecond line.";
    workflow.nodes[3].selected = true;
    const imported = parseWorkflow(JSON.stringify(workflow));
    expect(imported.nodes[3].data).toEqual(workflow.nodes[3].data);
    expect(imported.nodes[3].position).toEqual(workflow.nodes[3].position);
    expect(imported.nodes[3].selected).toBeUndefined();
  });
  it("rejects cycles, duplicates, self-links and invalid input/output directions", () => {
    const w = createDefault();
    expect(canConnect(w.nodes, w.edges, "motion", "analysis")).toBe(false);
    expect(canConnect(w.nodes, w.edges, "source", "source")).toBe(false);
    expect(canConnect(w.nodes, w.edges, "source", "analysis")).toBe(false);
    expect(canConnect(w.nodes, w.edges, "output", "motion")).toBe(false);
    expect(canConnect(w.nodes, w.edges, "motion", "reference")).toBe(false);
    const edit = makeNode("edit", "edit");
    expect(canConnect([...w.nodes, edit], w.edges, "motion", "edit")).toBe(
      true,
    );
  });
  it("rejects imported cycles and dangling endpoints", () => {
    const w = createDefault();
    w.edges.push({ id: "bad", source: "motion", target: "analysis" });
    expect(() => parseWorkflow(JSON.stringify(w))).toThrow("연결");
    w.edges[w.edges.length - 1] = {
      id: "bad",
      source: "missing",
      target: "motion",
    };
    expect(() => parseWorkflow(JSON.stringify(w))).toThrow("연결");
  });
  it("rejects malformed parameters and duplicate node IDs", () => {
    const w = createDefault();
    w.nodes[0].data.temperature = Infinity;
    expect(() => parseWorkflow(JSON.stringify(w))).toThrow("생성 설정");
    w.nodes[0].data.temperature = 0.7;
    w.nodes.push(w.nodes[0]);
    expect(() => parseWorkflow(JSON.stringify(w))).toThrow("노드");
    expect(() => parseWorkflow('{"version":2}')).toThrow("형식");
  });
  it("orders every dependency before its consumer and preserves per-node prompts", () => {
    const w = createDefault();
    const c = compileWorkflow(w);
    expect(c.errors).toEqual([]);
    const ids = c.ordered.map((n) => n.id);
    for (const e of w.edges)
      expect(ids.indexOf(e.source)).toBeLessThan(ids.indexOf(e.target));
    expect(c.plan.steps.find((s) => s.node_id === "director")?.prompt).toBe(
      w.nodes[3].data.prompt,
    );
  });
  it("reports unsupported Wan prompts without silently discarding them", () => {
    const w = createDefault();
    w.nodes.find((n) => n.id === "motion")!.data.prompt = "Change outfit";
    const c = compileWorkflow(w);
    expect(c.warnings.some((w) => w.includes("프롬프트 입력을 지원하지"))).toBe(
      true,
    );
    expect(c.plan.steps.find((s) => s.node_id === "motion")?.prompt).toBe(
      "Change outfit",
    );
  });
  it("blocks an empty workflow, missing output, and blank model", () => {
    expect(
      compileWorkflow({ version: 1, title: "Empty", nodes: [], edges: [] })
        .errors.length,
    ).toBe(2);
    const w = createDefault();
    w.nodes[2].data.model = "";
    expect(compileWorkflow(w).errors.some((e) => e.includes("모델 ID"))).toBe(
      true,
    );
  });
});
