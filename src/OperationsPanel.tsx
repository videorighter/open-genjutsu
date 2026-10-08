import { useCallback, useEffect, useState } from "react";
import { api, type Generation } from "./api";

type Metrics = {
  jobs: Record<string, number>;
  oldest_queued_seconds: number;
  oldest_review_seconds: number;
  recent_completed_samples: number;
  recent_p95_seconds: number | null;
  media_bytes: number;
  disk_free_bytes: number;
  temporal_connected: boolean;
};

function ReviewCard({
  job,
  refresh,
}: {
  job: Generation;
  refresh: () => Promise<void>;
}) {
  const [nodeId, setNodeId] = useState("");
  const [providerId, setProviderId] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recoverable = job.steps.filter(
    (s) =>
      s.status === "UNKNOWN" && ["fal", "replicate"].includes(s.provider || ""),
  );
  const waiting = Date.now() - Date.parse(job.updated) < 300_000;
  async function submit(path: string, body: unknown) {
    setBusy(true);
    setError("");
    try {
      await api(`/admin/jobs/${job.id}/${path}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="job-card">
      <strong>{job.title}</strong>
      <p>
        <code>{job.id}</code>
      </p>
      <p>{job.error || "공급자 실행 결과를 확인하세요."}</p>
      {waiting && (
        <p>
          기존 실행이 종료됐는지 확인하고, 확인 대기 상태가 된 뒤 5분 이상
          기다려주세요.
        </p>
      )}
      {!!recoverable.length && !job.cancel_requested && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit("reconcile", {
              node_id: nodeId || recoverable[0].node_id,
              provider_id: providerId,
            });
          }}
        >
          <label>
            복구할 노드
            <select
              value={nodeId || recoverable[0].node_id}
              onChange={(e) => setNodeId(e.target.value)}
            >
              {recoverable.map((s) => (
                <option key={s.node_id} value={s.node_id}>
                  {s.node_id} · {s.provider}
                </option>
              ))}
            </select>
          </label>
          <label>
            공급자 접수 ID
            <input
              required
              pattern="[A-Za-z0-9_-]+"
              maxLength={200}
              value={providerId}
              onChange={(e) => setProviderId(e.target.value)}
            />
          </label>
          <button className="button secondary" disabled={waiting || busy}>
            기존 접수 이어서 확인
          </button>
        </form>
      )}
      <details>
        <summary>공급자 확인 후 작업 종료</summary>
        <p>
          종료 전에 공급자 대시보드에서 실행과 비용을 확인하세요. 이 조치는 외부
          작업을 취소하거나 환불하지 않습니다.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit("close-review", {
              confirm_external_resolved: confirmed,
              reason,
            });
          }}
        >
          <label>
            처리 사유
            <textarea
              required
              minLength={8}
              maxLength={1000}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <label className="model-checkbox">
            외부 실행 및 비용 처리를 확인했습니다
            <input
              type="checkbox"
              required
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
          </label>
          <button
            className="button secondary"
            disabled={waiting || busy || !confirmed}
          >
            확인 대기 종료
          </button>
        </form>
      </details>
      {error && (
        <p role="alert" className="service-error">
          {error}
        </p>
      )}
    </article>
  );
}

export default function OperationsPanel() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [jobs, setJobs] = useState<Generation[]>([]);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    const [m, j] = await Promise.all([
      api<Metrics>("/admin/operations"),
      api<Generation[]>("/admin/jobs/review"),
    ]);
    setMetrics(m);
    setJobs(j);
    setError("");
  }, []);
  useEffect(() => {
    let active = true;
    const poll = () =>
      refresh().catch((e) => {
        if (active) setError(e.message);
      });
    poll();
    const timer = setInterval(poll, 10_000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [refresh]);
  return (
    <div className="operations-panel">
      <button
        className="button secondary"
        onClick={() => refresh().catch((e) => setError(e.message))}
      >
        운영 현황 새로고침
      </button>
      {error && (
        <p role="alert" className="service-error">
          {error}
        </p>
      )}
      {metrics && (
        <>
          <dl className="operations-metrics">
            <div>
              <dt>대기 / 실행 / 확인 대기</dt>
              <dd>
                {metrics.jobs.QUEUED || 0} / {metrics.jobs.RUNNING || 0} /{" "}
                {metrics.jobs.NEEDS_REVIEW || 0}
              </dd>
            </div>
            <div>
              <dt>가장 오래된 대기</dt>
              <dd>{Math.round(metrics.oldest_queued_seconds)}초</dd>
            </div>
            <div>
              <dt>가장 오래된 확인 대기</dt>
              <dd>{Math.round(metrics.oldest_review_seconds)}초</dd>
            </div>
            <div>
              <dt>최근 완료 작업 P95</dt>
              <dd>
                {metrics.recent_p95_seconds === null
                  ? "완료 표본 없음"
                  : `${Math.round(metrics.recent_p95_seconds)}초 (${metrics.recent_completed_samples}건)`}
              </dd>
            </div>
            <div>
              <dt>미디어 / 남은 디스크</dt>
              <dd>
                {(metrics.media_bytes / 2 ** 30).toFixed(2)} /{" "}
                {(metrics.disk_free_bytes / 2 ** 30).toFixed(2)} GiB
              </dd>
            </div>
            <div>
              <dt>Temporal 연결</dt>
              <dd>{metrics.temporal_connected ? "연결됨" : "미연결"}</dd>
            </div>
          </dl>
          <p>
            연결 상태와 함께 Worker 로그·실제 처리 결과를 확인하세요. 최근 완료
            시간은 대기 시간을 포함하며 API 비용은 공급자에서 확인합니다.
          </p>
        </>
      )}
      <h3>공급자 확인이 필요한 작업</h3>
      {!jobs.length && <p>확인 대기 작업이 없습니다.</p>}
      {jobs.map((job) => (
        <ReviewCard key={job.id} job={job} refresh={refresh} />
      ))}
    </div>
  );
}
