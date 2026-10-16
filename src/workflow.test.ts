import { describe, expect, it } from "vitest";
import {
  canConnect,
  compileWorkflow,
  createDefault,
  makeNode,
  parseWorkflow,
  upstreamSource,
} from "./workflow";
import {
  keepSupported,
  liveModels,
  priceLabel,
  setLiveModels,
  type ModelContract,
} from "./modelCatalog";
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
  it("결과 내보내기 takes one image or video and finds its 원본 영상", () => {
    const w = createDefault();
    // Already fed by motion; text nodes never feed it.
    expect(canConnect(w.nodes, w.edges, "reference", "output")).toBe(false);
    expect(
      canConnect(
        w.nodes,
        w.edges.filter((e) => e.target !== "output"),
        "director",
        "output",
      ),
    ).toBe(false);
    expect(upstreamSource(w.nodes, w.edges, "output")).toBe("source");
    expect(
      upstreamSource(
        w.nodes,
        w.edges.filter((e) => e.source !== "source"),
        "output",
      ),
    ).toBeUndefined();
    w.edges.push({ id: "extra", source: "reference", target: "output" });
    expect(compileWorkflow(w).errors).toContain(
      "결과 내보내기: 결과 내보내기에는 이미지나 영상 하나만 연결하세요.",
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
    expect(() => parseWorkflow(JSON.stringify(w))).toThrow("노드 설정");
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
  it("opens projects saved with removed providers using OpenRouter defaults", () => {
    const w = createDefault();
    const motion = w.nodes.find((n) => n.id === "motion")!;
    Object.assign(motion.data as Record<string, unknown>, {
      provider: "fal",
      model: "fal-ai/wan/v2.2-14b/animate/move",
      providerInput: { resolution: "720p" },
      endpoint: "https://models.example.com/v1",
    });
    const opened = parseWorkflow(JSON.stringify(w)).nodes.find(
      (n) => n.id === "motion",
    )!.data;
    expect(opened.provider).toBe("openrouter");
    expect(opened.model).toBe("minimax/hailuo-3");
    expect(opened.providerInput).toBeUndefined();
    expect(opened.endpoint).toBeUndefined();
    expect(opened.prompt).toBe(motion.data.prompt);
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
describe("live OpenRouter catalog", () => {
  const video: ModelContract = {
    provider: "openrouter",
    id: "x-ai/grok-imagine-video-1.5-lite",
    label: "Grok Imagine Video 1.5 Lite",
    kinds: ["motion", "edit"],
    prompt: true,
    vision: true,
    generationVerified: false,
    parameters: [],
    inputs: ["text", "image"],
    outputs: ["video"],
    pricing: { cents_per_video_output_second_480p: "2" },
  };
  it("lets live contracts replace the old OpenRouter video warning", () => {
    setLiveModels([video]);
    const w = createDefault();
    const motion = w.nodes.find((n) => n.data.kind === "motion")!;
    motion.data.provider = "openrouter";
    motion.data.model = video.id;
    expect(compileWorkflow(w).warnings.join()).not.toContain(motion.data.label);
    w.nodes.find((n) => n.data.kind === "analysis")!.data.provider =
      "openrouter";
    w.nodes.find((n) => n.data.kind === "analysis")!.data.model = video.id;
    expect(compileWorkflow(w).warnings.join()).toContain(
      "장면 분석 노드를 지원하지 않습니다",
    );
    expect(liveModels("motion").map((m) => m.id)).toEqual([video.id]);
    expect(liveModels("prompt")).toEqual([]);
    expect(priceLabel(video)).toBe("2¢/초~");
    expect(
      priceLabel({ ...video, pricing: { duration_seconds: "0.13" } }),
    ).toBe("$0.13/초~");
    setLiveModels([]);
  });
  it("drops options the newly selected model rejects", () => {
    const h3: ModelContract = {
      ...video,
      id: "minimax/hailuo-3",
      parameters: [
        { key: "resolution", label: "해상도", type: "enum", options: ["2K"] },
        { key: "duration", label: "길이(초)", type: "enum", options: [5, 6] },
        {
          key: "image_mode",
          label: "참조 이미지 사용",
          type: "enum",
          options: ["first_frame", "first_last", "reference"],
        },
        { key: "generate_audio", label: "오디오 생성", type: "boolean" },
      ],
    };
    // The FLUX.3 options left on a node that was switched to MiniMax H3.
    const flux = {
      image_mode: "first_frame",
      resolution: "720p",
      duration: 5,
      aspect_ratio: "16:9",
      generate_audio: false,
    };
    expect(keepSupported(flux, h3)).toEqual({
      image_mode: "first_frame",
      duration: 5,
      generate_audio: false,
    });
    expect(keepSupported({ duration: "5" }, h3)).toEqual({});
    expect(keepSupported(flux, { ...h3, inputs: undefined })).toBe(flux);
    expect(keepSupported(flux, undefined)).toBe(flux);
  });
});
