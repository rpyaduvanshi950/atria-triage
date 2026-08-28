/**
 * The only place that talks to the engine.
 *
 * Every clinical decision — band, outcome, whether a reason is required — is
 * made server-side and read from these responses. Nothing in the client
 * re-derives it: two sources of truth for a threshold is how they diverge.
 */
import type {
  AssessmentView, Forecast, History, Snapshot,
} from "@/types/atria";

const BASE =
  process.env.NEXT_PUBLIC_ATRIA_API ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.error ?? body.detail ?? detail;
    } catch {
      /* non-JSON error body; the status line will do */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  queue: () => request<Snapshot>("/v1/queue"),

  /** Blind ESI. The response deliberately carries no recommendation. */
  nurseAssess: (stayId: number, esi: number) =>
    request<AssessmentView>(
      `/v1/encounters/${stayId}/nurse-assessments?esi=${esi}`,
      { method: "POST" },
    ),

  /** 409 if the nurse has not committed yet. That guard lives on the server. */
  reveal: (stayId: number) =>
    request<AssessmentView>(`/v1/assessments/${stayId}/reveal`, { method: "POST" }),

  /** 422 when the outcome requires a reason and none was given. */
  finalize: (stayId: number, reasonCode = "") =>
    request<AssessmentView>(
      `/v1/assessments/${stayId}/finalize?reason_code=${encodeURIComponent(reasonCode)}`,
      { method: "POST" },
    ),

  worsening: (stayId: number) =>
    request<AssessmentView>(`/v1/encounters/${stayId}/worsening`, { method: "POST" }),

  forecast: (nurses: number, spaces: number) =>
    request<Forecast>(`/v1/operations/forecast?nurses=${nurses}&spaces=${spaces}`),

  history: (mode: "audit" | "general", limit = 80) =>
    request<History>(`/v1/history?mode=${mode}&limit=${limit}`),

  degraded: (on: boolean) =>
    request<{ degraded: boolean }>(`/api/degraded/${on ? 1 : 0}`, { method: "POST" }),

  wsUrl: () => `${BASE.replace(/^http/, "ws")}/ws`,
};
