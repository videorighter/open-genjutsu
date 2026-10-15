import type { Edge, Node } from "@xyflow/react";
import { defaultModels, modelCatalog, modelContract } from "./modelCatalog";
export type NodeKind =
  | "video"
  | "reference"
  | "analysis"
  | "prompt"
  | "image"
  | "motion"
  | "edit"
  | "output";
export type Provider = "openrouter" | "local";
// Saved projects from before the OpenRouter-only release open with its defaults.
const REMOVED_PROVIDERS = ["fal", "replicate", "gpu", "custom"];
export type NodeData = Record<string, unknown> & {
  kind: NodeKind;
  label: string;
  provider: Provider;
  model: string;
  prompt: string;
  temperature: number;
  seed: string;
  resolution: string;
  assetName?: string;
  assetType?: string;
  assetId?: string;
  providerInput?: Record<string, unknown>;
};
export type StudioNode = Node<NodeData, "studio">;
export type Workflow = {
  version: 1;
  title: string;
  nodes: StudioNode[];
  edges: Edge[];
};
export const STORAGE_KEY = "open-genjutsu.workflow.v1";
export const KINDS: Record<
  NodeKind,
  { name: string; english: string; description: string; color: string }
> = {
  video: {
    name: "원본 영상",
    english: "Source video",
    description: "움직임과 장면의 시작점",
    color: "amber",
  },
  reference: {
    name: "참조 이미지",
    english: "Reference image",
    description: "캐릭터 · 의상 · 스타일",
    color: "amber",
  },
  analysis: {
    name: "장면 분석",
    english: "Scene analysis",
    description: "영상의 구조와 동작 이해",
    color: "blue",
  },
  prompt: {
    name: "프롬프트 작성",
    english: "Prompt writer",
    description: "아이디어를 생성 지시로",
    color: "violet",
  },
  image: {
    name: "이미지 생성",
    english: "Image generation",
    description: "새 캐릭터 · 장면 참조 만들기",
    color: "amber",
  },
  motion: {
    name: "모션 전이",
    english: "Motion transfer",
    description: "같은 움직임, 새로운 캐릭터",
    color: "green",
  },
  edit: {
    name: "영역 편집",
    english: "Video edit",
    description: "선택한 부분만 다시 만들기",
    color: "pink",
  },
  output: {
    name: "결과 내보내기",
    english: "Final output",
    description: "원본 오디오 결합 · MP4 인코딩",
    color: "gray",
  },
};
export const PROVIDERS: Record<Provider, string> = {
  openrouter: "OpenRouter",
  local: "Local",
};
export const MODELS = Object.fromEntries(
  Object.keys(PROVIDERS).map((provider) => [
    provider,
    modelCatalog
      .filter((m) => m.provider === provider)
      .map(({ id, label, kinds }) => ({ id, label, kinds })),
  ]),
) as Record<Provider, { id: string; label: string; kinds: NodeKind[] }[]>;
export function modelLabel(provider: Provider, model: string) {
  return (
    MODELS[provider].find((m) => m.id === model)?.label ??
    model.split("/").at(-1) ??
    "모델 선택"
  );
}
export function makeNode(
  kind: NodeKind,
  id: string,
  position = { x: 0, y: 0 },
): StudioNode {
  const defaults: Record<NodeKind, [Provider, string, string]> = {
    video: ["local", "media-input", ""],
    reference: ["local", "media-input", ""],
    analysis: [
      "openrouter",
      defaultModels.analysis,
      "Describe the camera movement, subject actions, lighting, and scene composition. Identify elements that should remain unchanged.",
    ],
    prompt: [
      "openrouter",
      defaultModels.prompt,
      "Reimagine the character as a cinematic wanderer. Preserve the original motion, camera angle, and timing. Use the reference image for identity and wardrobe.\n\nNatural movement. Consistent identity. Soft, cinematic light.",
    ],
    image: [
      "openrouter",
      defaultModels.image,
      "A full-body character reference on a plain background. Consistent identity, clear silhouette, soft studio light.",
    ],
    motion: [
      "openrouter",
      defaultModels.motion,
      "Make the character from the reference image perform the exact motion, expressions, camera movement, and timing of the reference video. Keep the character's identity and outfit consistent.",
    ],
    edit: [
      "openrouter",
      defaultModels.edit,
      "Edit the reference video as described while preserving its motion, camera, timing, and every element that is not mentioned.",
    ],
    output: [
      "local",
      "ffmpeg",
      "Keep the original audio. Match the source timing and export as an MP4 video.",
    ],
  };
  const [provider, model, prompt] = defaults[kind];
  return {
    id,
    type: "studio",
    position,
    data: {
      kind,
      label: KINDS[kind].name,
      provider,
      model,
      prompt,
      temperature: 0.7,
      seed: "42",
      resolution: "720p",
      // Video models read the reference image as identity, not as the first frame.
      ...(kind === "motion"
        ? { providerInput: { image_mode: "reference" } }
        : {}),
    },
  };
}
export function createDefault(): Workflow {
  const nodes = [
    makeNode("video", "source", { x: 0, y: 30 }),
    makeNode("reference", "reference", { x: 0, y: 330 }),
    makeNode("analysis", "analysis", { x: 300, y: 30 }),
    makeNode("prompt", "director", { x: 300, y: 330 }),
    makeNode("motion", "motion", { x: 620, y: 160 }),
    makeNode("output", "output", { x: 920, y: 160 }),
  ];
  const pairs = [
    ["source", "analysis"],
    ["analysis", "director"],
    ["director", "motion"],
    ["reference", "motion"],
    ["source", "motion"],
    ["motion", "output"],
  ];
  return {
    version: 1,
    title: "새 Genjutsu 프로젝트",
    nodes,
    edges: pairs.map(([source, target], i) => ({
      id: `edge-${i}`,
      source,
      target,
      type: "smoothstep",
    })),
  };
}
export function canConnect(
  nodes: StudioNode[],
  edges: Edge[],
  source: string,
  target: string,
): boolean {
  if (
    source === target ||
    !nodes.some((n) => n.id === source) ||
    !nodes.some((n) => n.id === target) ||
    edges.some((e) => e.source === source && e.target === target)
  )
    return false;
  if (
    nodes.find((n) => n.id === source)?.data.kind === "output" ||
    ["video", "reference"].includes(
      nodes.find((n) => n.id === target)!.data.kind,
    )
  )
    return false;
  const visited = new Set<string>();
  function reaches(id: string): boolean {
    if (id === source) return true;
    if (visited.has(id)) return false;
    visited.add(id);
    return edges.filter((e) => e.source === id).some((e) => reaches(e.target));
  }
  return !reaches(target);
}
export function parseWorkflow(text: string): Workflow {
  const raw = JSON.parse(text);
  if (
    !raw ||
    raw.version !== 1 ||
    typeof raw.title !== "string" ||
    !raw.title.trim() ||
    raw.title.length > 120 ||
    !Array.isArray(raw.nodes) ||
    !Array.isArray(raw.edges)
  )
    throw new Error("지원하는 프로젝트 JSON 형식이 아닙니다.");
  if (raw.nodes.length > 100 || raw.edges.length > 300)
    throw new Error(
      "노드는 최대 100개, 연결은 최대 300개까지 가져올 수 있습니다.",
    );
  const ids = new Set<string>();
  const nodes: StudioNode[] = raw.nodes.map((n: StudioNode) => {
    const d = n?.data;
    if (
      !n ||
      typeof n.id !== "string" ||
      !n.id ||
      n.id.length > 100 ||
      ids.has(n.id) ||
      !d ||
      !Object.hasOwn(KINDS, d.kind) ||
      !(
        Object.hasOwn(PROVIDERS, d.provider) ||
        REMOVED_PROVIDERS.includes(d.provider)
      ) ||
      typeof d.label !== "string" ||
      !d.label.trim() ||
      d.label.length > 120 ||
      typeof d.model !== "string" ||
      d.model.length > 300 ||
      typeof d.prompt !== "string" ||
      d.prompt.length > 20000 ||
      !Number.isFinite(n.position?.x) ||
      !Number.isFinite(n.position?.y)
    )
      throw new Error("노드 ID, 위치 또는 설정이 올바르지 않습니다.");
    if (
      typeof d.temperature !== "number" ||
      !Number.isFinite(d.temperature) ||
      d.temperature < 0 ||
      d.temperature > 2 ||
      typeof d.seed !== "string" ||
      d.seed.length > 20 ||
      !["480p", "580p", "720p", "1080p"].includes(d.resolution)
    )
      throw new Error("노드 설정이 올바르지 않습니다.");
    ids.add(n.id);
    const removed = REMOVED_PROVIDERS.includes(d.provider);
    return {
      id: n.id,
      type: "studio",
      position: { x: n.position.x, y: n.position.y },
      data: {
        kind: d.kind,
        label: d.label,
        provider: removed ? "openrouter" : d.provider,
        model: removed
          ? (defaultModels[d.kind as keyof typeof defaultModels] ?? "")
          : d.model,
        prompt: d.prompt,
        temperature: d.temperature,
        seed: d.seed,
        resolution: d.resolution,
        ...(typeof d.assetId === "string" && d.assetId.length <= 36
          ? { assetId: d.assetId }
          : {}),
        ...(!removed &&
        d.providerInput &&
        typeof d.providerInput === "object" &&
        !Array.isArray(d.providerInput) &&
        JSON.stringify(d.providerInput).length <= 10000
          ? { providerInput: d.providerInput }
          : {}),
        ...(typeof d.assetName === "string"
          ? {
              assetName: d.assetName.slice(0, 300),
              assetType:
                typeof d.assetType === "string"
                  ? d.assetType.slice(0, 100)
                  : "",
            }
          : {}),
      },
    };
  });
  const edges: Edge[] = [];
  const edgeIds = new Set<string>();
  for (const e of raw.edges) {
    if (
      typeof e?.id !== "string" ||
      !e.id ||
      edgeIds.has(e.id) ||
      typeof e.source !== "string" ||
      typeof e.target !== "string" ||
      !canConnect(nodes, edges, e.source, e.target)
    )
      throw new Error("연결에 중복, 순환 또는 잘못된 대상이 있습니다.");
    edgeIds.add(e.id);
    edges.push({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "smoothstep",
    });
  }
  return { version: 1, title: raw.title.trim(), nodes, edges };
}
export function compileWorkflow(workflow: Workflow) {
  const remaining = new Map(
    workflow.nodes.map((n) => [
      n.id,
      workflow.edges.filter((e) => e.target === n.id).length,
    ]),
  );
  const ready = workflow.nodes.filter((n) => remaining.get(n.id) === 0);
  const ordered: StudioNode[] = [];
  while (ready.length) {
    const n = ready.shift()!;
    ordered.push(n);
    for (const e of workflow.edges.filter((e) => e.source === n.id)) {
      const count = remaining.get(e.target)! - 1;
      remaining.set(e.target, count);
      if (count === 0) {
        const next = workflow.nodes.find((n) => n.id === e.target);
        if (next) ready.push(next);
      }
    }
  }
  const errors: string[] = [],
    warnings: string[] = [];
  if (!workflow.nodes.length) errors.push("노드를 하나 이상 추가하세요.");
  if (ordered.length !== workflow.nodes.length)
    errors.push("순환 연결을 제거하세요.");
  if (!workflow.nodes.some((n) => n.data.kind === "output"))
    errors.push("결과 내보내기 노드를 추가하세요.");
  for (const n of workflow.nodes) {
    if (!n.data.model.trim())
      errors.push(`${n.data.label}: 모델 ID를 입력하세요.`);
    if (
      !["video", "reference"].includes(n.data.kind) &&
      !workflow.edges.some((e) => e.target === n.id)
    )
      warnings.push(`${n.data.label}: 입력 노드가 연결되지 않았습니다.`);
    if (["video", "reference"].includes(n.data.kind) && !n.data.assetId)
      warnings.push(`${n.data.label}: 실행 시 미디어를 서버에 올려야 합니다.`);
    const contract = modelContract(n.data.provider, n.data.model);
    if (!contract)
      warnings.push(
        `${n.data.label}: 사용자 지정 모델의 태스크 지원 여부를 확인하세요.`,
      );
    else if (!contract.kinds.includes(n.data.kind))
      warnings.push(
        `${n.data.label}: 이 모델은 ${KINDS[n.data.kind].name} 노드를 지원하지 않습니다.`,
      );
  }
  return {
    ordered,
    errors,
    warnings,
    plan: {
      schema_version: 1,
      workflow_name: workflow.title,
      steps: ordered.map((n) => ({
        node_id: n.id,
        task: n.data.kind,
        provider: n.data.provider,
        model: n.data.model,
        prompt: n.data.prompt,
        parameters: {
          temperature: n.data.temperature,
          seed: n.data.seed || null,
          resolution: n.data.resolution,
        },
        input_nodes: workflow.edges
          .filter((e) => e.target === n.id)
          .map((e) => e.source),
      })),
    },
  };
}

// The motion step already carries its own prompt, so the default service graph
// skips language-model stages that would add cost before the first result.
export function createServiceDefault(
  template: "motion" | "local" = "motion",
): Workflow {
  const original = createDefault();
  if (template === "local") {
    const source = original.nodes.find((n) => n.data.kind === "video")!;
    const output = original.nodes.find((n) => n.data.kind === "output")!;
    source.position = { x: 0, y: 100 };
    output.position = { x: 420, y: 100 };
    return {
      version: 1,
      title: "새 로컬 영상 테스트 프로젝트",
      nodes: [source, output],
      edges: [
        {
          id: "source-output",
          source: source.id,
          target: output.id,
          type: "smoothstep",
        },
      ],
    };
  }
  const nodes = original.nodes.filter(
    (n) => !["analysis", "prompt"].includes(n.data.kind),
  );
  const edges = original.edges.filter(
    (e) =>
      nodes.some((n) => n.id === e.source) &&
      nodes.some((n) => n.id === e.target),
  );
  return {
    ...original,
    title: "새 Genjutsu 프로젝트",
    nodes,
    edges,
  };
}
