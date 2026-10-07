import type { Workflow } from "./workflow";
export type User = { id: string; email: string; admin: boolean };
export type SavedWorkflow = {
  id: string;
  title: string;
  revision: number;
  graph: Workflow;
  updated: string;
};
export type Generation = {
  id: string;
  workflow_id: string;
  title: string;
  status: string;
  error: string | null;
  cancel_requested: boolean;
  created: string;
  steps: {
    node_id: string;
    status: string;
    error: string | null;
    provider_id: string | null;
    output: { asset_id?: string; text?: string } | null;
  }[];
};
export type Preflight = {
  errors: string[];
  warnings: string[];
  paid_steps: number;
  max_active_jobs: number;
};
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
function csrf() {
  return (
    document.cookie
      .split("; ")
      .find((x) => x.startsWith("genjutsu_csrf="))
      ?.split("=")
      .slice(1)
      .join("=") || ""
  );
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && options.body)
    headers.set("Content-Type", "application/json");
  if (options.method && options.method !== "GET")
    headers.set("X-CSRF-Token", csrf());
  const response = await fetch("/api" + path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string"
        ? detail
        : Array.isArray(detail?.errors)
          ? detail.errors.join("\n")
          : "요청을 완료하지 못했습니다.",
    );
  }
  return response.json();
}
export function assetUrl(id: string, download = false) {
  return `/api/assets/${encodeURIComponent(id)}/content${download ? "?download=true" : ""}`;
}
