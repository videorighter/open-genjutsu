import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Handle,
  Position,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  useReactFlow,
  type NodeProps,
  type Connection,
  type NodeChange,
  type EdgeChange,
  type Edge,
} from "@xyflow/react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Copy,
  FileJson,
  Film,
  FolderOpen,
  GitBranch,
  Grip,
  Image,
  Layers,
  LayoutGrid,
  Maximize,
  MoreHorizontal,
  PanelLeftClose,
  PanelRightClose,
  Play,
  Plus,
  Redo2,
  ScanEye,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
  Video,
  WandSparkles,
  Workflow as WorkflowIcon,
  X,
  Zap,
} from "lucide-react";
import {
  KINDS,
  MODELS,
  PROVIDERS,
  STORAGE_KEY,
  canConnect,
  compileWorkflow,
  createDefault,
  makeNode,
  modelLabel,
  parseWorkflow,
  type NodeKind,
  type Provider,
  type StudioNode,
  type Workflow,
} from "./workflow";
const KIND_ICONS = {
  video: Video,
  reference: Image,
  analysis: ScanEye,
  prompt: WandSparkles,
  motion: Sparkles,
  edit: SlidersHorizontal,
  output: Film,
};
function Landscape({ portrait = false }: { portrait?: boolean }) {
  return (
    <div className={`media-art ${portrait ? "portrait" : ""}`}>
      <div className="art-sun" />
      <div className="art-mountain back" />
      <div className="art-mountain front" />
      <div className="art-person">
        <span />
      </div>
      <div className="art-grain" />
    </div>
  );
}
function StudioNodeCard({ data, selected }: NodeProps<StudioNode>) {
  const Icon = KIND_ICONS[data.kind];
  const asset = ["video", "reference"].includes(data.kind);
  return (
    <div
      className={`studio-node ${selected ? "selected" : ""} ${KINDS[data.kind].color}`}
    >
      {!asset && <Handle type="target" position={Position.Left} />}
      <div className="node-top">
        <span className="node-kind-icon">
          <Icon size={15} />
        </span>
        <span className="node-type">{KINDS[data.kind].english}</span>
        <span className="node-ellipsis">
          <MoreHorizontal size={17} />
        </span>
      </div>
      <h3>{data.label}</h3>
      {asset ? (
        <div className="node-media">
          <Landscape portrait={data.kind === "reference"} />
          <span className="media-label">
            {data.assetName ||
              (data.kind === "video" ? "VIDEO / 미연결" : "REFERENCE / 미연결")}
          </span>
          <span className="media-badge">
            {data.kind === "video" ? (
              <Play size={10} fill="currentColor" />
            ) : (
              <Image size={11} />
            )}
          </span>
        </div>
      ) : (
        <>
          <div className="node-model">
            <span className="provider-dot" />
            {modelLabel(data.provider, data.model)}
            <ChevronDown size={12} />
          </div>
          {data.prompt && <p className="node-prompt">{data.prompt}</p>}
          {data.kind === "motion" && (
            <div className="motion-detail">
              <span>영상 + 참조 이미지</span>
              <span className="tiny-tag">{data.resolution}</span>
            </div>
          )}
          {data.kind === "output" && (
            <div className="output-chips">
              <span>MP4</span>
              <span>원본 오디오</span>
            </div>
          )}
        </>
      )}
      <div className="node-footer">
        <span>
          <span className="status-dot" /> {PROVIDERS[data.provider]}
        </span>
        <span>
          {asset ? "INPUT" : data.kind === "output" ? "OUTPUT" : "MODEL"}
        </span>
      </div>
      {data.kind !== "output" && (
        <Handle type="source" position={Position.Right} />
      )}
    </div>
  );
}
const nodeTypes = { studio: StudioNodeCard };
function serialize(
  title: string,
  nodes: StudioNode[],
  edges: Edge[],
): Workflow {
  return {
    version: 1,
    title: title.trim() || "Untitled workflow",
    nodes: nodes.map((n) => ({
      id: n.id,
      type: "studio",
      position: n.position,
      data: {
        ...n.data,
        label: n.data.label.trim() || KINDS[n.data.kind].name,
      },
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "smoothstep",
    })),
  };
}
function initialWorkflow() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return parseWorkflow(saved);
  } catch {
    /* Recover an invalid/unavailable browser store with a usable canvas. */
  }
  return createDefault();
}
function Studio() {
  const [initial] = useState(initialWorkflow);
  const [nodes, setNodes] = useState<StudioNode[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [title, setTitle] = useState(initial.title);
  const [selectedId, setSelectedId] = useState<string | null>(
    initial.nodes.some((n) => n.id === "director")
      ? "director"
      : (initial.nodes[0]?.id ?? null),
  );
  const [search, setSearch] = useState("");
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth > 760);
  const [inspectorOpen, setInspectorOpen] = useState(
    () => window.innerWidth > 760,
  );
  const [tab, setTab] = useState<"settings" | "prompt">("settings");
  const [saved, setSaved] = useState<"saving" | "saved" | "error">("saved");
  const [toast, setToast] = useState("");
  const [modal, setModal] = useState<"plan" | "help" | "new" | null>(null);
  const [assetUrls, setAssetUrls] = useState<Record<string, string>>({});
  const history = useRef<Workflow[]>([]),
    future = useRef<Workflow[]>([]);
  const [historyCount, setHistoryCount] = useState(0),
    [futureCount, setFutureCount] = useState(0);
  const importRef = useRef<HTMLInputElement>(null),
    assetRef = useRef<HTMLInputElement>(null);
  const assetUrlsRef = useRef<Record<string, string>>({});
  const canvasRef = useRef<HTMLDivElement>(null);
  const { fitView, screenToFlowPosition } = useReactFlow<StudioNode>();
  const selected = nodes.find((n) => n.id === selectedId);
  const current = () => serialize(title, nodes, edges);
  const latestWorkflow = useRef(serialize(title, nodes, edges));
  const persistWorkflow = useCallback(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(latestWorkflow.current));
      setSaved("saved");
    } catch {
      setSaved("error");
      setToast(
        "브라우저 저장에 실패했습니다. JSON을 내보내 변경 사항을 보관하세요.",
      );
    }
  }, []);
  const compiled = useMemo(
    () => compileWorkflow(serialize(title, nodes, edges)),
    [title, nodes, edges],
  );
  const notify = useCallback((message: string) => setToast(message), []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!modal) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>("[role=dialog]");
    const focusables = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input, select, textarea, summary, [tabindex="0"]',
        ) ?? [],
      );
    focusables()[0]?.focus();
    function keydown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setModal(null);
        return;
      }
      if (e.key === "Tab") {
        const items = focusables();
        const first = items[0],
          last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, [modal]);
  useEffect(() => {
    latestWorkflow.current = serialize(title, nodes, edges);
    setSaved("saving");
    const timer = setTimeout(persistWorkflow, 550);
    return () => clearTimeout(timer);
  }, [title, nodes, edges, persistWorkflow]);
  useEffect(() => {
    // Flush pending edits before navigation or when mobile browsers suspend a tab.
    const onVisibility = () => {
      if (document.visibilityState === "hidden") persistWorkflow();
    };
    window.addEventListener("pagehide", persistWorkflow);
    window.addEventListener("beforeunload", persistWorkflow);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("pagehide", persistWorkflow);
      window.removeEventListener("beforeunload", persistWorkflow);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [persistWorkflow]);
  useEffect(
    () => () => {
      Object.values(assetUrlsRef.current).forEach(URL.revokeObjectURL);
    },
    [],
  );
  function remember() {
    history.current = [...history.current.slice(-49), current()];
    future.current = [];
    setHistoryCount(history.current.length);
    setFutureCount(0);
  }
  function restore(w: Workflow) {
    setNodes(w.nodes);
    setEdges(w.edges);
    setTitle(w.title);
    setSelectedId(w.nodes[0]?.id ?? null);
  }
  function undo() {
    const w = history.current.pop();
    if (!w) return;
    future.current.push(current());
    restore(w);
    setHistoryCount(history.current.length);
    setFutureCount(future.current.length);
  }
  function redo() {
    const w = future.current.pop();
    if (!w) return;
    history.current.push(current());
    restore(w);
    setHistoryCount(history.current.length);
    setFutureCount(future.current.length);
  }
  function patchNode(patch: Partial<StudioNode["data"]>) {
    if (!selected) return;
    remember();
    setNodes((ns) =>
      ns.map((n) =>
        n.id === selected.id ? { ...n, data: { ...n.data, ...patch } } : n,
      ),
    );
  }
  function addNode(kind: NodeKind, position?: { x: number; y: number }) {
    if (nodes.length >= 100) {
      notify("노드는 최대 100개까지 추가할 수 있습니다.");
      return;
    }
    remember();
    const id = crypto.randomUUID();
    const bounds = canvasRef.current?.getBoundingClientRect();
    const pos =
      position ??
      screenToFlowPosition({
        x: (bounds?.left ?? 250) + (bounds?.width ?? 800) * 0.45,
        y: (bounds?.top ?? 170) + (bounds?.height ?? 500) * 0.45,
      });
    const node = makeNode(kind, id, {
      x: pos.x + Math.random() * 35,
      y: pos.y + Math.random() * 35,
    });
    setNodes((ns) => [...ns, node]);
    setSelectedId(id);
    setInspectorOpen(true);
    if (window.innerWidth <= 760) setLeftOpen(false);
    notify(`${KINDS[kind].name} 노드를 추가했습니다.`);
  }
  function duplicateNode() {
    if (!selected) return;
    if (nodes.length >= 100) {
      notify("노드는 최대 100개까지 추가할 수 있습니다.");
      return;
    }
    remember();
    const copy: StudioNode = {
      ...selected,
      id: crypto.randomUUID(),
      position: { x: selected.position.x + 45, y: selected.position.y + 65 },
      data: {
        ...selected.data,
        label: `${selected.data.label.slice(0, 116)} 복사`,
      },
      selected: false,
    };
    setNodes((ns) => [...ns, copy]);
    setSelectedId(copy.id);
  }
  function removeNode() {
    if (!selected) return;
    remember();
    setNodes((ns) => ns.filter((n) => n.id !== selected.id));
    setEdges((es) =>
      es.filter((e) => e.source !== selected.id && e.target !== selected.id),
    );
    setSelectedId(null);
    notify("노드를 삭제했습니다.");
  }
  function download(value: unknown, name: string) {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function clearAssetUrls() {
    Object.values(assetUrlsRef.current).forEach(URL.revokeObjectURL);
    assetUrlsRef.current = {};
    setAssetUrls({});
  }
  async function importFile(file?: File) {
    if (!file) return;
    try {
      if (file.size > 2_000_000)
        throw new Error("JSON 파일은 2MB 이하만 가져올 수 있습니다.");
      const w = parseWorkflow(await file.text());
      remember();
      clearAssetUrls();
      restore(w);
      setTimeout(() => fitView({ padding: 0.15, duration: 400 }), 50);
      notify("워크플로를 가져왔습니다.");
    } catch (e) {
      notify(e instanceof Error ? e.message : "파일을 가져오지 못했습니다.");
    }
    if (importRef.current) importRef.current.value = "";
  }
  async function copyPrompt() {
    if (!selected) return;
    try {
      await navigator.clipboard.writeText(selected.data.prompt);
      notify("프롬프트를 복사했습니다.");
    } catch {
      notify(
        "클립보드 접근이 허용되지 않았습니다. 텍스트를 직접 선택해 복사하세요.",
      );
    }
  }
  function attachAsset(file?: File) {
    if (!file || !selected) return;
    const required = selected.data.kind === "video" ? "video/" : "image/";
    if (!file.type.startsWith(required)) {
      notify(
        required === "video/"
          ? "영상 파일을 선택하세요."
          : "이미지 파일을 선택하세요.",
      );
      return;
    }
    const previous = assetUrlsRef.current[selected.id];
    if (previous) URL.revokeObjectURL(previous);
    const url = URL.createObjectURL(file);
    assetUrlsRef.current = { ...assetUrlsRef.current, [selected.id]: url };
    setAssetUrls({ ...assetUrlsRef.current });
    patchNode({ assetName: file.name, assetType: file.type });
    notify("미디어를 현재 세션에 연결했습니다.");
    if (assetRef.current) assetRef.current.value = "";
  }
  const onNodesChange = useCallback((changes: NodeChange<StudioNode>[]) => {
    setNodes((ns) => applyNodeChanges(changes, ns));
    const removed = changes.filter((c) => c.type === "remove").map((c) => c.id);
    if (removed.length) {
      setEdges((es) =>
        es.filter(
          (e) => !removed.includes(e.source) && !removed.includes(e.target),
        ),
      );
      setSelectedId((id) => (id && removed.includes(id) ? null : id));
    }
  }, []);
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges((es) => applyEdgeChanges(changes, es)),
    [],
  );
  function connect(connection: Connection) {
    if (!canConnect(nodes, edges, connection.source, connection.target)) {
      notify("중복·순환 연결 또는 입력/출력 방향을 확인하세요.");
      return;
    }
    remember();
    setEdges((es) => addEdge({ ...connection, type: "smoothstep" }, es));
  }
  function reset() {
    remember();
    clearAssetUrls();
    restore(createDefault());
    setModal(null);
    setTimeout(() => fitView({ padding: 0.15, duration: 500 }), 50);
    notify("새 기본 워크플로를 만들었습니다. 이전 구성은 되돌릴 수 있습니다.");
  }
  const filtered = (Object.keys(KINDS) as NodeKind[]).filter((k) =>
    `${KINDS[k].name} ${KINDS[k].english}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const isAsset =
    selected && ["video", "reference"].includes(selected.data.kind);
  const unsupportedPrompt =
    selected?.data.provider === "fal" &&
    selected.data.model.includes("/animate/");
  return (
    <div className="app-shell">
      <aside className="rail" inert={!!modal}>
        <a className="brand-mark" href="#" aria-label="Open Genjutsu 홈">
          <svg viewBox="0 0 40 40">
            <path
              d="M26 12H15l-4 8 4 8h11l4-8H20v4h4l-2 2h-5l-3-6 3-6h9z"
              fill="currentColor"
            />
          </svg>
        </a>
        <div className="rail-top">
          <button
            className="rail-button active"
            title="워크플로 스튜디오"
            aria-label="워크플로 스튜디오"
          >
            <WorkflowIcon size={21} />
          </button>
          <button
            className="rail-button"
            title="JSON 워크플로 가져오기"
            aria-label="JSON 워크플로 가져오기"
            onClick={() => importRef.current?.click()}
          >
            <FolderOpen size={21} />
          </button>
          <button
            className="rail-button"
            title="사용 가이드"
            aria-label="사용 가이드"
            onClick={() => setModal("help")}
          >
            <Layers size={21} />
          </button>
        </div>
        <div className="rail-bottom">
          <button
            className="rail-button"
            aria-label="도움말"
            onClick={() => setModal("help")}
          >
            <CircleHelp size={20} />
          </button>
          <span className="avatar">OG</span>
        </div>
      </aside>
      <div className="workspace" inert={!!modal}>
        <header className="topbar">
          <div className="product-name">
            Open Genjutsu <span className="beta">STUDIO</span>
          </div>
          <div className="header-right">
            <span className="local-status">
              <span /> Local workspace
            </span>
            <button
              className="icon-button"
              aria-label="도움말 열기"
              onClick={() => setModal("help")}
            >
              <CircleHelp size={17} />
            </button>
            <span className="header-avatar">Y</span>
          </div>
        </header>
        <div className="workflow-bar">
          <div className="workflow-title">
            <div className="breadcrumb">
              Workspace <ChevronRight size={12} /> Workflows{" "}
              <ChevronRight size={12} />
            </div>
            <div className="title-row">
              <input
                aria-label="워크플로 이름"
                value={title}
                maxLength={120}
                onChange={(e) => setTitle(e.target.value)}
                onBlur={() => {
                  if (!title.trim()) setTitle("Untitled workflow");
                }}
              />
              <span className="version-tag">v1</span>
              <span
                className={`save-status ${saved === "error" ? "error" : ""}`}
              >
                {saved === "saving" ? (
                  <span className="saving-dot" />
                ) : (
                  <CheckCheck size={13} />
                )}{" "}
                {saved === "saved"
                  ? "자동 저장됨"
                  : saved === "saving"
                    ? "저장 중…"
                    : "저장 실패 · JSON 내보내기"}
              </span>
            </div>
          </div>
          <div className="workflow-actions">
            <button
              className="button secondary import-button"
              onClick={() => importRef.current?.click()}
            >
              <Upload size={14} /> 가져오기
            </button>
            <button
              className="button secondary"
              onClick={() => {
                download(current(), "genjutsu-workflow.json");
                notify("워크플로 JSON을 내보냈습니다.");
              }}
            >
              <ArrowDownToLine size={14} /> 내보내기
            </button>
            <button className="button primary" onClick={() => setModal("plan")}>
              <Play size={14} fill="currentColor" /> 실행 계획{" "}
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
        <div className="editor-layout">
          {leftOpen && (
            <aside className="library">
              <div className="panel-heading">
                <span>노드 라이브러리</span>
                <button
                  className="icon-button"
                  onClick={() => setLeftOpen(false)}
                  aria-label="노드 라이브러리 접기"
                >
                  <PanelLeftClose size={16} />
                </button>
              </div>
              <div className="library-search">
                <Search size={14} />
                <input
                  placeholder="노드 검색"
                  aria-label="노드 검색"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <span>⌕</span>
              </div>
              <div className="library-scroll">
                <div className="section-label">
                  BUILD YOUR FLOW <span>{filtered.length}</span>
                </div>
                {filtered.map((kind) => {
                  const Icon = KIND_ICONS[kind];
                  return (
                    <button
                      key={kind}
                      className="library-item"
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData(
                          "application/genjutsu-node",
                          kind,
                        );
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onClick={() => addNode(kind)}
                    >
                      <span className={`library-icon ${KINDS[kind].color}`}>
                        <Icon size={17} />
                      </span>
                      <span>
                        <strong>{KINDS[kind].name}</strong>
                        <small>{KINDS[kind].description}</small>
                      </span>
                      <Plus className="library-plus" size={14} />
                    </button>
                  );
                })}
                {!filtered.length && (
                  <p className="search-empty">검색 결과가 없습니다.</p>
                )}
                <div className="library-divider" />
                <div className="section-label">YOUR WORKSPACE</div>
                <button
                  className="workspace-item"
                  onClick={() => setModal("new")}
                >
                  <Plus size={15} />
                  <span>새 워크플로</span>
                </button>
                <button
                  className="workspace-item"
                  onClick={() => importRef.current?.click()}
                >
                  <FileJson size={15} />
                  <span>JSON에서 가져오기</span>
                  <ArrowUpRight size={13} />
                </button>
              </div>
              <div className="library-note">
                <span className="note-symbol">
                  <GitBranch size={20} />
                </span>
                <strong>당신의 모델, 당신의 흐름.</strong>
                <p>
                  각 단계의 모델과 프롬프트를
                  <br />
                  자유롭게 조합해 보세요.
                </p>
                <button onClick={() => setModal("help")}>
                  스튜디오 사용 가이드 <ArrowUpRight size={13} />
                </button>
              </div>
              <div className="library-footer">
                <span className="status-dot" /> Browser storage{" "}
                <span>v0.1</span>
              </div>
            </aside>
          )}
          <main className="canvas-panel">
            <div className="canvas-toolbar">
              <div className="canvas-tabs">
                <button
                  className="canvas-tab active"
                  onClick={() => setModal(null)}
                >
                  <WorkflowIcon size={14} /> 워크플로{" "}
                  <span>{nodes.length}</span>
                </button>
                <button className="canvas-tab" onClick={() => setModal("plan")}>
                  <FileJson size={14} /> 실행 계획
                </button>
              </div>
              <div className="canvas-tools">
                {!leftOpen && (
                  <button
                    className="icon-button"
                    aria-label="노드 라이브러리 열기"
                    onClick={() => setLeftOpen(true)}
                  >
                    <LayoutGrid size={16} />
                  </button>
                )}
                <button
                  className="icon-button"
                  disabled={!historyCount}
                  aria-label="되돌리기"
                  onClick={undo}
                >
                  <Undo2 size={16} />
                </button>
                <button
                  className="icon-button"
                  disabled={!futureCount}
                  aria-label="다시 실행"
                  onClick={redo}
                >
                  <Redo2 size={16} />
                </button>
                <span className="tool-divider" />
                <button
                  className="icon-button"
                  aria-label="전체 노드 보기"
                  onClick={() => fitView({ padding: 0.18, duration: 400 })}
                >
                  <Maximize size={16} />
                </button>
                {!inspectorOpen && (
                  <button
                    className="icon-button"
                    aria-label="노드 설정 열기"
                    onClick={() => setInspectorOpen(true)}
                  >
                    <Settings2 size={16} />
                  </button>
                )}
              </div>
            </div>
            <div
              className="canvas-surface"
              ref={canvasRef}
              onDrop={(e) => {
                e.preventDefault();
                const kind = e.dataTransfer.getData(
                  "application/genjutsu-node",
                );
                if (Object.hasOwn(KINDS, kind))
                  addNode(
                    kind as NodeKind,
                    screenToFlowPosition({ x: e.clientX, y: e.clientY }),
                  );
              }}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
              }}
            >
              <div className="canvas-caption">
                <span className="caption-kicker">THE CREATIVE PIPELINE</span>
                <h2>
                  One motion.
                  <br />
                  <span>Infinite possibilities.</span>
                </h2>
                <p>연결하고, 바꾸고, 나만의 장면으로.</p>
              </div>
              <ReactFlow<StudioNode>
                nodes={nodes.map((n) => ({
                  ...n,
                  selected: n.id === selectedId,
                }))}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                nodeTypes={nodeTypes}
                onConnect={connect}
                isValidConnection={(c) =>
                  canConnect(nodes, edges, c.source, c.target)
                }
                onNodeClick={(_, n) => {
                  setSelectedId(n.id);
                  setInspectorOpen(true);
                }}
                onPaneClick={() => setSelectedId(null)}
                onNodeDragStart={remember}
                onBeforeDelete={async () => {
                  remember();
                  return true;
                }}
                fitView
                fitViewOptions={{ padding: 0.17 }}
                minZoom={0.25}
                maxZoom={1.75}
                defaultEdgeOptions={{
                  type: "smoothstep",
                  style: { stroke: "#57615a", strokeWidth: 1.6 },
                }}
                deleteKeyCode={modal ? null : ["Backspace", "Delete"]}
                colorMode="dark"
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={22}
                  size={1}
                  color="#303534"
                />
                <Controls showInteractive={false} position="bottom-left" />
                <MiniMap
                  position="bottom-right"
                  nodeColor={(n) =>
                    n.id === selectedId ? "#c8ef9b" : "#3c4943"
                  }
                  nodeStrokeWidth={0}
                  maskColor="rgba(12,16,14,.7)"
                  pannable
                  zoomable
                />
              </ReactFlow>
              {!nodes.length && (
                <div className="empty-canvas">
                  <Sparkles size={26} />
                  <h3>첫 노드부터 시작해 보세요.</h3>
                  <p>라이브러리의 노드를 클릭하거나 캔버스로 드래그하세요.</p>
                  <button
                    className="button primary"
                    onClick={() => addNode("video")}
                  >
                    <Plus size={14} /> 원본 영상 추가
                  </button>
                </div>
              )}
              <div className="canvas-hint">
                <Grip size={13} />
                <span>노드를 드래그해 배치 · 포트를 연결해 흐름 만들기</span>
              </div>
            </div>
            <div className="canvas-statusbar">
              <span>
                <span className="status-dot" /> {nodes.length} nodes{" "}
                <span className="status-separator">/</span> {edges.length}{" "}
                connections
              </span>
              <span>
                <ShieldCheck size={12} /> 실행 전 구성 검증{" "}
                <span className="status-separator">·</span>{" "}
                <button onClick={() => setModal("help")}>도움말</button>
              </span>
            </div>
          </main>
          {inspectorOpen && (
            <aside className="inspector">
              <div className="panel-heading">
                <span>노드 설정</span>
                <button
                  className="icon-button"
                  aria-label="노드 설정 접기"
                  onClick={() => setInspectorOpen(false)}
                >
                  <PanelRightClose size={16} />
                </button>
              </div>
              {selected ? (
                <>
                  <div className="inspector-node">
                    <span
                      className={`inspector-icon ${KINDS[selected.data.kind].color}`}
                    >
                      {(() => {
                        const Icon = KIND_ICONS[selected.data.kind];
                        return <Icon size={21} />;
                      })()}
                    </span>
                    <div>
                      <span className="inspector-kicker">
                        {KINDS[selected.data.kind].english.toUpperCase()}
                      </span>
                      <h2>{selected.data.label}</h2>
                    </div>
                    <span className="selected-badge">선택됨</span>
                  </div>
                  <div className="inspector-tabs">
                    <button
                      className={tab === "settings" ? "active" : ""}
                      onClick={() => setTab("settings")}
                    >
                      설정
                    </button>
                    <button
                      className={tab === "prompt" ? "active" : ""}
                      onClick={() => setTab("prompt")}
                    >
                      프롬프트 <span>{selected.data.prompt ? "1" : "0"}</span>
                    </button>
                  </div>
                  <div className="inspector-scroll">
                    {tab === "settings" && (
                      <>
                        <label className="field">
                          <span>노드 이름</span>
                          <input
                            aria-label="노드 이름"
                            value={selected.data.label}
                            maxLength={120}
                            onChange={(e) =>
                              patchNode({ label: e.target.value })
                            }
                          />
                        </label>
                        <div className="field">
                          <span className="field-label">
                            API 공급자{" "}
                            <span className="field-optional">PROVIDER</span>
                          </span>
                          <div className="select-wrap">
                            <Zap size={14} />
                            <select
                              aria-label="API 공급자"
                              value={selected.data.provider}
                              onChange={(e) => {
                                const provider = e.target.value as Provider;
                                patchNode({
                                  provider,
                                  model: MODELS[provider][0]?.id ?? "",
                                });
                              }}
                            >
                              {Object.entries(PROVIDERS).map(([id, name]) => (
                                <option key={id} value={id}>
                                  {name}
                                </option>
                              ))}
                            </select>
                            <ChevronDown size={13} />
                          </div>
                        </div>
                        {selected.data.provider === "custom" && (
                          <label className="field">
                            <span>API base URL</span>
                            <input
                              aria-label="API base URL"
                              value={selected.data.endpoint || ""}
                              placeholder="https://api.example.com/v1"
                              maxLength={500}
                              onChange={(e) =>
                                patchNode({ endpoint: e.target.value })
                              }
                            />
                            <small className="field-help">
                              연결 주소만 저장합니다. API 키는 서버에서
                              관리합니다.
                            </small>
                          </label>
                        )}
                        <div className="field">
                          <span className="field-label">
                            모델{" "}
                            <span className="field-optional">CUSTOMIZABLE</span>
                          </span>
                          <select
                            className="model-select"
                            aria-label="추천 모델"
                            value={
                              MODELS[selected.data.provider].some(
                                (m) => m.id === selected.data.model,
                              )
                                ? selected.data.model
                                : ""
                            }
                            onChange={(e) => {
                              if (e.target.value)
                                patchNode({ model: e.target.value });
                            }}
                          >
                            <option value="">사용자 지정 모델</option>
                            {MODELS[selected.data.provider].map((m) => (
                              <option key={m.id} value={m.id}>
                                {m.label}
                              </option>
                            ))}
                          </select>
                          <input
                            className="model-id"
                            aria-label="모델 ID"
                            placeholder="모델 ID를 직접 입력하세요"
                            maxLength={300}
                            value={selected.data.model}
                            onChange={(e) =>
                              patchNode({ model: e.target.value })
                            }
                          />
                          <small className="field-help">
                            목록에 없는 모델도 ID로 지정할 수 있습니다.
                          </small>
                        </div>
                      </>
                    )}
                    <div className="prompt-field">
                      <div className="prompt-heading">
                        <label htmlFor="node-prompt">프롬프트</label>
                        <div>
                          <span className="field-optional">
                            {isAsset ? "OPTIONAL" : "YOUR DIRECTION"}
                          </span>
                          <button
                            className="icon-button"
                            aria-label="프롬프트 복사"
                            onClick={copyPrompt}
                          >
                            <Copy size={13} />
                          </button>
                        </div>
                      </div>
                      <div className="prompt-editor">
                        <div className="prompt-editor-top">
                          <span className="prompt-language">
                            <span /> PLAIN TEXT
                          </span>
                          <span>
                            {selected.data.prompt.length.toLocaleString()} / 20k
                          </span>
                        </div>
                        <textarea
                          id="node-prompt"
                          aria-label="노드 프롬프트"
                          spellCheck={false}
                          placeholder="이 노드에 전달할 지시를 작성하세요…"
                          value={selected.data.prompt}
                          maxLength={20000}
                          onChange={(e) =>
                            patchNode({ prompt: e.target.value })
                          }
                        />
                        <div className="prompt-editor-bottom">
                          <span>명확한 지시가 좋은 결과를 만듭니다.</span>
                          <WandSparkles size={13} />
                        </div>
                      </div>
                      {unsupportedPrompt ? (
                        <p className="compatibility-note">
                          Wan-Animate API는 프롬프트 입력을 지원하지 않습니다.
                          프롬프트 제어에는 VACE 또는 GPU 모델을 선택하세요.
                        </p>
                      ) : (
                        <p className="field-help">
                          선택한 모델의 입력 지원 여부는 실행 전에 확인해야
                          합니다.
                        </p>
                      )}
                    </div>
                    {isAsset && (
                      <div className="asset-field">
                        <span className="field-label">입력 미디어</span>
                        <button
                          className="upload-zone"
                          onClick={() => assetRef.current?.click()}
                        >
                          <Upload size={19} />
                          <strong>
                            {selected.data.assetName || "파일 선택"}
                          </strong>
                          <small>
                            {selected.data.kind === "video"
                              ? "영상 파일"
                              : "이미지 파일"}{" "}
                            · 현재 세션에서만 보관
                          </small>
                        </button>
                        {assetUrls[selected.id] &&
                          (selected.data.kind === "video" ? (
                            <video
                              className="asset-preview"
                              src={assetUrls[selected.id]}
                              controls
                            />
                          ) : (
                            <img
                              className="asset-preview"
                              src={assetUrls[selected.id]}
                              alt="참조 이미지 미리보기"
                            />
                          ))}
                        <p className="field-help">
                          파일은 서버로 업로드되지 않습니다. 새로고침 후 다시
                          연결하세요.
                        </p>
                      </div>
                    )}
                    {tab === "settings" && (
                      <>
                        <div className="inspector-divider" />
                        <div className="advanced-heading">
                          <span>
                            <Settings2 size={14} /> 생성 설정
                          </span>
                          <span>ADVANCED</span>
                        </div>
                        <label className="range-field">
                          <span>
                            Temperature{" "}
                            <strong>
                              {selected.data.temperature.toFixed(2)}
                            </strong>
                          </span>
                          <input
                            type="range"
                            min="0"
                            max="2"
                            step="0.05"
                            aria-label="Temperature"
                            value={selected.data.temperature}
                            onChange={(e) =>
                              patchNode({ temperature: Number(e.target.value) })
                            }
                          />
                          <small>
                            <span>정밀하게</span>
                            <span>자유롭게</span>
                          </small>
                        </label>
                        <div className="field-row">
                          <label className="field">
                            <span>Seed</span>
                            <input
                              aria-label="Seed"
                              value={selected.data.seed}
                              maxLength={20}
                              placeholder="Random"
                              onChange={(e) =>
                                patchNode({ seed: e.target.value })
                              }
                            />
                          </label>
                          <label className="field">
                            <span>해상도</span>
                            <select
                              aria-label="해상도"
                              value={selected.data.resolution}
                              onChange={(e) =>
                                patchNode({ resolution: e.target.value })
                              }
                            >
                              {["480p", "580p", "720p", "1080p"].map((r) => (
                                <option key={r}>{r}</option>
                              ))}
                            </select>
                          </label>
                        </div>
                        <p className="field-help">
                          모델이 지원하는 파라미터만 실행기에 전달해야 합니다.
                        </p>
                        <div className="node-connections">
                          <span className="field-label">
                            입력 연결{" "}
                            <span>
                              {
                                edges.filter((e) => e.target === selected.id)
                                  .length
                              }
                            </span>
                          </span>
                          {edges
                            .filter((e) => e.target === selected.id)
                            .map((e) => (
                              <div key={e.id}>
                                <GitBranch size={12} />
                                <span>
                                  {
                                    nodes.find((n) => n.id === e.source)?.data
                                      .label
                                  }
                                </span>
                                <button
                                  className="icon-button"
                                  aria-label={`${nodes.find((n) => n.id === e.source)?.data.label} 연결 삭제`}
                                  onClick={() => {
                                    remember();
                                    setEdges((es) =>
                                      es.filter((x) => x.id !== e.id),
                                    );
                                  }}
                                >
                                  <X size={12} />
                                </button>
                              </div>
                            ))}
                          {!edges.some((e) => e.target === selected.id) && (
                            <small>연결된 입력이 없습니다.</small>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                  <div className="inspector-footer">
                    <button
                      className="button secondary"
                      onClick={duplicateNode}
                    >
                      <Copy size={14} /> 복제
                    </button>
                    <button
                      className="delete-button"
                      aria-label="선택한 노드 삭제"
                      onClick={removeNode}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </>
              ) : (
                <div className="inspector-empty">
                  <div>
                    <Settings2 size={25} />
                  </div>
                  <h3>노드를 선택하세요</h3>
                  <p>
                    모델과 프롬프트를 바꾸려면
                    <br />
                    캔버스에서 노드를 클릭하세요.
                  </p>
                </div>
              )}
            </aside>
          )}
        </div>
        <footer className="bottom-bar">
          <span className="footer-brand">
            OPEN GENJUTSU <span>/</span> WORKFLOW STUDIO
          </span>
          <span>
            CREATE WITHOUT LIMITS <span className="footer-dot" />
          </span>
        </footer>
      </div>
      <input
        ref={importRef}
        type="file"
        accept="application/json,.json"
        hidden
        onChange={(e) => void importFile(e.target.files?.[0])}
      />
      <input
        ref={assetRef}
        type="file"
        accept={selected?.data.kind === "video" ? "video/*" : "image/*"}
        hidden
        onChange={(e) => attachAsset(e.target.files?.[0])}
      />
      {toast && (
        <div className="toast" role="status">
          <Check size={16} />
          <span>{toast}</span>
          <button aria-label="알림 닫기" onClick={() => setToast("")}>
            <X size={14} />
          </button>
        </div>
      )}
      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <section
            className={`modal ${modal === "plan" ? "plan-modal" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="modal-close icon-button"
              aria-label="대화상자 닫기"
              onClick={() => setModal(null)}
            >
              <X size={20} />
            </button>
            {modal === "plan" ? (
              <>
                <span className="modal-eyebrow">
                  <WorkflowIcon size={14} /> EXECUTION PREVIEW
                </span>
                <h2 id="modal-title">흐름을 실행 계획으로.</h2>
                <p className="modal-intro">
                  {title} · {compiled.ordered.length}개의 단계
                </p>
                <div className="preview-notice">
                  <ShieldCheck size={18} />
                  <div>
                    <strong>구성 미리보기입니다.</strong>
                    <p>
                      Temporal 및 영상 API는 아직 연결되지 않았습니다. 실제
                      생성이나 과금 없이 실행 순서와 설정을 확인합니다.
                    </p>
                  </div>
                </div>
                {compiled.errors.length > 0 ? (
                  <div className="plan-errors">
                    {compiled.errors.map((e) => (
                      <p key={e}>{e}</p>
                    ))}
                  </div>
                ) : (
                  <div className="plan-valid">
                    <Check size={15} /> 연결 구조가 유효합니다.
                  </div>
                )}
                <div className="plan-steps">
                  {compiled.ordered.map((n, i) => (
                    <div className="plan-step" key={n.id}>
                      <span>{String(i + 1).padStart(2, "0")}</span>
                      <div>
                        <strong>{n.data.label}</strong>
                        <small>
                          {PROVIDERS[n.data.provider]} ·{" "}
                          {modelLabel(n.data.provider, n.data.model)}
                        </small>
                      </div>
                      <ArrowRight size={15} />
                    </div>
                  ))}
                </div>
                {compiled.warnings.length > 0 && (
                  <details className="plan-warnings">
                    <summary>
                      확인할 사항 {compiled.warnings.length}개{" "}
                      <ChevronDown size={14} />
                    </summary>
                    {compiled.warnings.map((w, i) => (
                      <p key={i}>{w}</p>
                    ))}
                  </details>
                )}
                <div className="modal-actions">
                  <button
                    className="button secondary"
                    onClick={() => setModal(null)}
                  >
                    편집 계속하기
                  </button>
                  <button
                    className="button primary"
                    disabled={compiled.errors.length > 0}
                    onClick={() => {
                      download(compiled.plan, "genjutsu-execution-plan.json");
                      notify("실행 계획 JSON을 내보냈습니다.");
                    }}
                  >
                    <ArrowDownToLine size={14} /> 실행 계획 내보내기
                  </button>
                </div>
              </>
            ) : modal === "new" ? (
              <>
                <span className="modal-eyebrow">A FRESH START</span>
                <h2 id="modal-title">새 흐름을 만들어 볼까요?</h2>
                <p className="modal-intro">
                  현재 구성을 기본 워크플로로 교체합니다. 보관하려면 먼저
                  JSON으로 내보내세요. 변경 후 되돌리기도 가능합니다.
                </p>
                <div className="modal-actions">
                  <button
                    className="button secondary"
                    onClick={() => setModal(null)}
                  >
                    취소
                  </button>
                  <button className="button primary" onClick={reset}>
                    <Plus size={14} /> 새 워크플로
                  </button>
                </div>
              </>
            ) : (
              <>
                <span className="modal-eyebrow">WELCOME TO YOUR STUDIO</span>
                <h2 id="modal-title">아이디어를 연결하세요.</h2>
                <p className="modal-intro">
                  각 노드는 영상 제작의 한 단계입니다.
                </p>
                <div className="help-steps">
                  <div>
                    <span>01</span>
                    <div>
                      <strong>노드를 놓고 연결하기</strong>
                      <p>
                        왼쪽 노드를 클릭하거나 드래그하세요. 오른쪽 포트에서
                        다음 노드의 왼쪽 포트로 연결합니다. 순환 연결은 허용되지
                        않습니다.
                      </p>
                    </div>
                  </div>
                  <div>
                    <span>02</span>
                    <div>
                      <strong>모델과 프롬프트 바꾸기</strong>
                      <p>
                        노드를 선택한 뒤 공급자·모델 ID·프롬프트를 수정하세요.
                        Custom API에서는 원하는 모델 ID를 직접 지정할 수
                        있습니다.
                      </p>
                    </div>
                  </div>
                  <div>
                    <span>03</span>
                    <div>
                      <strong>저장하고 계획 확인하기</strong>
                      <p>
                        브라우저에 자동 저장됩니다. JSON으로 내보내 다른
                        브라우저에서 가져오세요. 실행 계획에서 연결과 호환성
                        주의 사항을 확인합니다.
                      </p>
                    </div>
                  </div>
                </div>
                <div className="help-footer">
                  <span>
                    미디어는 현재 세션에만 보관됩니다. API 키는 이 UI에서
                    입력받지 않습니다.
                  </span>
                </div>
                <button
                  className="button primary help-start"
                  onClick={() => setModal(null)}
                >
                  만들기 시작 <ArrowRight size={14} />
                </button>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
export default function App() {
  return (
    <ReactFlowProvider>
      <Studio />
    </ReactFlowProvider>
  );
}
