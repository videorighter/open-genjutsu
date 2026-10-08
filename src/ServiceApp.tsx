import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  assetUrl,
  type User,
  type SavedWorkflow,
  type Generation,
} from "./api";
import Editor from "./App";
import { createServiceDefault, type Workflow, type Provider } from "./workflow";
import "./service.css";

const states: Record<string, string> = {
  QUEUED: "대기 중",
  RUNNING: "생성 중",
  SUCCEEDED: "완료",
  FAILED: "실패",
  CANCELLED: "취소됨",
  NEEDS_REVIEW: "공급자 확인 대기",
};
export default function ServiceApp() {
  const [user, setUser] = useState<User | null>(null),
    [boot, setBoot] = useState(true),
    [error, setError] = useState("");
  const [record, setRecord] = useState<SavedWorkflow | null>(null),
    [workflows, setWorkflows] = useState<SavedWorkflow[]>([]),
    [jobs, setJobs] = useState<Generation[]>([]);
  const [panel, setPanel] = useState<
      "keys" | "jobs" | "users" | "media" | null
    >(null),
    [providers, setProviders] = useState<string[]>([]),
    [busy, setBusy] = useState(false);
  const draftRef = useRef<Workflow | null>(null);
  const onChange = useCallback((graph: Workflow) => {
    draftRef.current = graph;
  }, []);
  const recordRef = useRef<SavedWorkflow | null>(null),
    saveQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [keyProvider, setKeyProvider] = useState<Provider>("openrouter"),
    [key, setKey] = useState("");
  const [keyEndpoint, setKeyEndpoint] = useState("");
  const [newEmail, setNewEmail] = useState(""),
    [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [assets, setAssets] = useState<
    { id: string; filename: string; mime: string; size: number }[]
  >([]);
  const updateRecord = (w: SavedWorkflow) => {
    recordRef.current = w;
    draftRef.current = w.graph;
    setRecord(w);
  };
  const load = async () => {
    const list = await api<SavedWorkflow[]>("/workflows");
    setWorkflows(list);
    const w =
      list[0] ||
      (await api<SavedWorkflow>("/workflows", {
        method: "POST",
        body: JSON.stringify({ revision: 0, graph: createServiceDefault() }),
      }));
    updateRecord(w);
  };
  useEffect(() => {
    let alive = true;
    api<{ user: User | null }>("/auth/session")
      .then(async (x) => {
        if (!alive) return;
        setUser(x.user);
        if (x.user) await load();
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setBoot(false));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!user) return;
    let alive = true;
    const refresh = () =>
      api<Generation[]>("/jobs")
        .then((x) => alive && setJobs(x))
        .catch((e) => {
          if (alive) setError(e.message);
        });
    refresh();
    const timer = setInterval(refresh, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [user]);
  useEffect(() => {
    if (!panel) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>(".service-dialog");
    const focusables = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input, select, textarea, summary, a[href]",
        ) || [],
      );
    focusables()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPanel(null);
        setKey("");
      }
      if (event.key === "Tab") {
        const items = focusables(),
          first = items[0],
          last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, [panel]);
  const save = useCallback((graph: Workflow) => {
    const targetId = recordRef.current?.id;
    const request = saveQueue.current
      .catch(() => {})
      .then(async () => {
        const current = recordRef.current;
        if (!current) throw new Error("워크플로를 먼저 불러오세요.");
        if (current.id !== targetId) return current;
        if (JSON.stringify(current.graph) === JSON.stringify(graph))
          return current;
        const saved = await api<SavedWorkflow>(`/workflows/${current.id}`, {
          method: "PUT",
          body: JSON.stringify({ revision: current.revision, graph }),
        });
        recordRef.current = saved;
        setRecord(saved);
        setWorkflows((xs) => xs.map((x) => (x.id === saved.id ? saved : x)));
        return saved;
      });
    saveQueue.current = request;
    return request;
  }, []);
  const upload = useCallback(async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api<{ id: string; filename: string; mime: string }>("/assets", {
      method: "POST",
      body: form,
    });
  }, []);
  async function login(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const u = await api<User>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setPassword("");
      setUser(u);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function perform(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openPanel(value: "keys" | "jobs" | "users" | "media") {
    setPanel(value);
    setError("");
    if (value === "media")
      try {
        setAssets(await api<typeof assets>("/assets"));
      } catch (e) {
        setError((e as Error).message);
      }
    if (value === "keys")
      try {
        setProviders(
          (await api<{ providers: string[] }>("/credentials")).providers,
        );
      } catch (e) {
        setError((e as Error).message);
      }
  }
  if (boot)
    return (
      <div className="auth-page">
        <p role="status">스튜디오에 연결 중…</p>
      </div>
    );
  if (!user)
    return (
      <div className="auth-page">
        <form className="auth-card" onSubmit={login}>
          <span className="service-eyebrow">OPEN GENJUTSU</span>
          <h1>당신의 영상 작업실.</h1>
          <p>모델을 조합하고, 움직임을 새롭게 만드세요.</p>
          <label>
            이메일
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            비밀번호
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && (
            <p className="service-error" role="alert">
              {error}
            </p>
          )}
          <button className="button primary" disabled={busy}>
            {busy ? "로그인 중…" : "로그인"}
          </button>
          <small>계정은 서비스 관리자가 발급합니다.</small>
        </form>
      </div>
    );
  if (!record)
    return (
      <div className="auth-page">
        <p role="alert">{error || "워크플로를 불러오는 중…"}</p>
        <button className="button secondary" onClick={() => perform(load)}>
          다시 불러오기
        </button>
      </div>
    );
  return (
    <div className="service-shell">
      <header className="service-bar" inert={!!panel}>
        <div className="service-workflows">
          <select
            aria-label="저장된 워크플로"
            value={record.id}
            disabled={busy}
            onChange={(e) =>
              perform(async () => {
                await save(draftRef.current || recordRef.current!.graph);
                const list = await api<SavedWorkflow[]>("/workflows");
                const next = list.find((w) => w.id === e.target.value);
                if (next) {
                  setWorkflows(list);
                  updateRecord(next);
                }
              })
            }
          >
            {[record, ...workflows.filter((w) => w.id !== record.id)].map(
              (w) => (
                <option key={w.id} value={w.id}>
                  {w.title}
                </option>
              ),
            )}
          </select>
          <button
            onClick={() =>
              perform(async () => {
                await save(draftRef.current || recordRef.current!.graph);
                const w = await api<SavedWorkflow>("/workflows", {
                  method: "POST",
                  body: JSON.stringify({
                    revision: 0,
                    graph: createServiceDefault(),
                  }),
                });
                setWorkflows((xs) => [w, ...xs]);
                updateRecord(w);
              })
            }
            disabled={busy}
          >
            새 프로젝트
          </button>
          <button
            disabled={busy}
            aria-label="프로젝트 삭제"
            onClick={() => {
              if (
                window.confirm(
                  "현재 프로젝트를 삭제할까요? 작업 기록이 있으면 먼저 삭제해야 합니다.",
                )
              )
                perform(async () => {
                  await save(draftRef.current || recordRef.current!.graph);
                  await api(`/workflows/${recordRef.current!.id}`, {
                    method: "DELETE",
                  });
                  await load();
                });
            }}
          >
            삭제
          </button>
        </div>
        <nav aria-label="서비스 메뉴">
          <button onClick={() => openPanel("jobs")}>
            작업 내역{" "}
            {jobs.filter((j) => ["QUEUED", "RUNNING"].includes(j.status))
              .length || ""}
          </button>
          <button onClick={() => openPanel("keys")}>API 키</button>
          <button onClick={() => openPanel("media")}>미디어</button>
          {user.admin && (
            <button onClick={() => openPanel("users")}>사용자</button>
          )}
          <button
            aria-label="로그아웃"
            onClick={() =>
              perform(async () => {
                await save(draftRef.current || recordRef.current!.graph);
                await api("/auth/logout", { method: "POST" });
                setUser(null);
                setRecord(null);
                recordRef.current = null;
                setJobs([]);
                setPanel(null);
              })
            }
          >
            로그아웃
          </button>
        </nav>
      </header>
      {error && (
        <div className="service-banner" role="alert">
          {error}
          <button onClick={() => setError("")} aria-label="서비스 오류 닫기">
            ×
          </button>
        </div>
      )}
      <div inert={!!panel}>
        <Editor
          key={record.id}
          service={{
            graph: record.graph,
            paused: !!panel,
            onChange,
            save,
            upload,
            onSubmitted: (job) => {
              setJobs((xs) => [job, ...xs.filter((x) => x.id !== job.id)]);
              setPanel("jobs");
            },
            onError: setError,
          }}
        />
      </div>
      {panel && (
        <div
          className="service-overlay"
          onClick={() => {
            setPanel(null);
            setKey("");
          }}
        >
          <section
            className="service-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="service-panel-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="service-close"
              aria-label="서비스 창 닫기"
              onClick={() => {
                setPanel(null);
                setKey("");
              }}
            >
              ×
            </button>
            <h2 id="service-panel-title">
              {panel === "keys"
                ? "API 연결"
                : panel === "jobs"
                  ? "작업 내역"
                  : panel === "media"
                    ? "미디어 보관함"
                    : "사용자 계정"}
            </h2>
            {panel === "keys" && (
              <>
                <p>
                  키는 서버에서 암호화해 보관합니다. 저장된 키는 다시 표시하지
                  않습니다.
                </p>
                <ul className="key-list">
                  {["openrouter", "fal", "replicate", "custom", "gpu"].map(
                    (p) => (
                      <li key={p}>
                        <span>
                          {p} · {providers.includes(p) ? "연결됨" : "미연결"}
                        </span>
                        {providers.includes(p) && (
                          <button
                            disabled={busy}
                            onClick={() =>
                              perform(async () => {
                                await api(`/credentials/${p}`, {
                                  method: "DELETE",
                                });
                                setProviders((xs) => xs.filter((x) => x !== p));
                              })
                            }
                          >
                            연결 해제
                          </button>
                        )}
                      </li>
                    ),
                  )}
                </ul>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    perform(async () => {
                      await api(`/credentials/${keyProvider}`, {
                        method: "PUT",
                        body: JSON.stringify({ key, endpoint: keyEndpoint }),
                      });
                      setProviders((xs) => [...new Set([...xs, keyProvider])]);
                      setKey("");
                      setMessage("API 키를 저장했습니다.");
                    });
                  }}
                >
                  <label>
                    API 공급자
                    <select
                      value={keyProvider}
                      onChange={(e) =>
                        setKeyProvider(e.target.value as Provider)
                      }
                    >
                      {["openrouter", "fal", "replicate", "custom", "gpu"].map(
                        (p) => (
                          <option key={p}>{p}</option>
                        ),
                      )}
                    </select>
                  </label>
                  {["custom", "gpu"].includes(keyProvider) && (
                    <label>
                      키를 사용할 API 주소
                      <input
                        type="url"
                        required
                        value={keyEndpoint}
                        onChange={(e) => setKeyEndpoint(e.target.value)}
                        placeholder="https://models.example.com/v1"
                      />
                      <small>운영자가 허용한 주소에만 이 키를 보냅니다.</small>
                    </label>
                  )}
                  <label>
                    API 키
                    <input
                      type="password"
                      value={key}
                      autoComplete="off"
                      required
                      minLength={8}
                      onChange={(e) => setKey(e.target.value)}
                    />
                  </label>
                  <button className="button primary" disabled={busy}>
                    키 저장
                  </button>
                </form>
              </>
            )}
            {panel === "jobs" && (
              <div className="job-list">
                {!jobs.length && <p>아직 실행한 작업이 없습니다.</p>}
                {jobs.map((job) => (
                  <article className="job-card" key={job.id}>
                    <div className="job-heading">
                      <strong>{job.title}</strong>
                      <span className={`job-state ${job.status.toLowerCase()}`}>
                        {states[job.status] || job.status}
                      </span>
                    </div>
                    <small>
                      {new Date(job.created).toLocaleString("ko-KR")}
                    </small>
                    {job.error && <p className="service-error">{job.error}</p>}
                    <ul>
                      {job.steps.map((s) => (
                        <li key={s.node_id}>
                          <span>
                            {s.node_id} · {s.status}
                          </span>
                          {s.output?.text && (
                            <details>
                              <summary>텍스트 결과</summary>
                              <p>{s.output.text}</p>
                            </details>
                          )}
                          {s.output?.asset_id && s.status === "COMPLETE" && (
                            <a href={assetUrl(s.output.asset_id, true)}>
                              파일 다운로드
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                    {["SUCCEEDED", "FAILED", "CANCELLED"].includes(
                      job.status,
                    ) && (
                      <button
                        className="button secondary"
                        disabled={busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              "작업 기록을 삭제할까요? 결과 파일은 미디어 보관함에 남습니다.",
                            )
                          )
                            perform(async () => {
                              await api(`/jobs/${job.id}`, {
                                method: "DELETE",
                              });
                              setJobs((xs) =>
                                xs.filter((x) => x.id !== job.id),
                              );
                            });
                        }}
                      >
                        기록 삭제
                      </button>
                    )}
                    {["QUEUED", "RUNNING"].includes(job.status) && (
                      <button
                        className="button secondary"
                        disabled={busy || job.cancel_requested}
                        onClick={() =>
                          perform(async () => {
                            const next = await api<Generation>(
                              `/jobs/${job.id}/cancel`,
                              { method: "POST" },
                            );
                            setJobs((xs) =>
                              xs.map((x) => (x.id === next.id ? next : x)),
                            );
                          })
                        }
                      >
                        {job.cancel_requested
                          ? "취소 확인 중…"
                          : "작업 취소 요청"}
                      </button>
                    )}
                  </article>
                ))}
              </div>
            )}
            {panel === "media" && (
              <>
                <p>
                  사용 중인 파일은 프로젝트와 작업 기록에서 연결을 해제한 후
                  삭제할 수 있습니다.
                </p>
                <ul className="key-list">
                  {assets.map((a) => (
                    <li key={a.id}>
                      <a href={assetUrl(a.id, true)}>
                        {a.filename} · {(a.size / 1024 / 1024).toFixed(1)} MB
                      </a>
                      <button
                        disabled={busy}
                        onClick={() => {
                          if (window.confirm("이 미디어를 영구 삭제할까요?"))
                            perform(async () => {
                              await api(`/assets/${a.id}`, {
                                method: "DELETE",
                              });
                              setAssets((xs) =>
                                xs.filter((x) => x.id !== a.id),
                              );
                            });
                        }}
                      >
                        삭제
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {panel === "users" && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  perform(async () => {
                    await api("/admin/users", {
                      method: "POST",
                      body: JSON.stringify({
                        email: newEmail,
                        password: newPassword,
                      }),
                    });
                    setNewPassword("");
                    setNewEmail("");
                    setMessage("사용자 계정을 만들었습니다.");
                  });
                }}
              >
                <p>
                  사용자는 자신의 프로젝트, 키, 미디어와 작업만 볼 수 있습니다.
                </p>
                <label>
                  새 사용자 이메일
                  <input
                    type="email"
                    required
                    value={newEmail}
                    onChange={(e) => setNewEmail(e.target.value)}
                  />
                </label>
                <label>
                  초기 비밀번호
                  <input
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                  />
                </label>
                <button className="button primary" disabled={busy}>
                  계정 만들기
                </button>
              </form>
            )}
            {error && (
              <p role="alert" className="service-error">
                {error}
              </p>
            )}
            {message && <p role="status">{message}</p>}
          </section>
        </div>
      )}
    </div>
  );
}
