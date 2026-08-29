/**
 * The only place that talks to the engine.
 *
 * Every clinical decision — band, outcome, whether a reason is required — is
 * made server-side and read from these responses. Nothing in the client
 * re-derives it: two sources of truth for a threshold is how they diverge.
 */
import type {
  AssessmentView, Forecast, History, Logs, ShadowReport, Snapshot,
} from "@/types/atria";

const BASE =
  process.env.NEXT_PUBLIC_ATRIA_API ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

/**
 * The bearer token, held in memory and mirrored to sessionStorage.
 *
 * sessionStorage rather than localStorage: a token on a shared triage
 * workstation should not outlive the tab the nurse closes when they walk away.
 * It is not the only defence — the token expires server-side — but it is the
 * one that matters when someone else sits down at the same machine.
 */
const TOKEN_KEY = "atria.token";
let token: string | null = null;

export const session = {
  get token(): string | null {
    if (token !== null) return token;
    try {
      token = sessionStorage.getItem(TOKEN_KEY);
    } catch {
      /* private mode, or no storage at all — memory alone is fine */
    }
    return token;
  },
  set(value: string | null) {
    token = value;
    try {
      if (value) sessionStorage.setItem(TOKEN_KEY, value);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing to do; the in-memory copy still works for this tab */
    }
  },
};

export interface User {
  username: string;
  role: string;
  display: string;
  permissions: string[];
  auth_enabled?: boolean;
  demo_accounts?: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const bearer = session.token;
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (res.status === 401) {
    // The session is gone, not merely this request. Clearing it here means the
    // whole app falls back to the sign-in screen instead of every panel
    // rendering its own copy of the same error.
    session.set(null);
    throw new ApiError(401, "session expired — sign in again");
  }
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
  /** Exchange credentials for a bearer token. Form-encoded, per OAuth2. */
  signIn: async (username: string, password: string) => {
    const res = await fetch(`${BASE}/v1/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(res.status, body.error ?? "incorrect username or password");
    }
    const data = (await res.json()) as { access_token: string; user: User };
    session.set(data.access_token);
    return data.user;
  },

  signOut: () => session.set(null),

  /** Who we are signed in as, and what that role is allowed to do. */
  me: () => request<User>("/v1/auth/me"),

  /** Public: whether signing in is required at all. Never 401s. */
  mode: () => request<{ auth_enabled: boolean; demo_accounts: boolean }>(
    "/v1/auth/mode"),

  queue: () => request<Snapshot>("/v1/queue"),

  /** Blind ESI. The response deliberately carries no recommendation. */
  nurseAssess: (stayId: number, esi: number) =>
    request<AssessmentView>(
      `/v1/encounters/${stayId}/nurse-assessments?esi=${esi}`,
      { method: "POST" },
    ),

  /** The current step, without advancing it. Carries no recommendation before
      the nurse has committed, because the payload has none to carry. */
  assessment: (stayId: number) =>
    request<AssessmentView>(`/v1/assessments/${stayId}`),

  /**
   * 409 if the nurse has not committed, or if the token does not match.
   * The token is minted only when the assessment is stored, so the order is a
   * server invariant rather than a convention this client happens to follow.
   */
  reveal: (stayId: number, revealToken = "") =>
    request<AssessmentView>(
      `/v1/assessments/${stayId}/reveal?reveal_token=${encodeURIComponent(revealToken)}`,
      { method: "POST" },
    ),

  /** 422 when the outcome requires a reason and none was given. */
  finalize: (stayId: number, reasonCode = "", reasonNote = "") =>
    request<AssessmentView>(
      `/v1/assessments/${stayId}/finalize` +
        `?reason_code=${encodeURIComponent(reasonCode)}` +
        `&reason_note=${encodeURIComponent(reasonNote)}`,
      { method: "POST" },
    ),

  worsening: (stayId: number) =>
    request<AssessmentView>(`/v1/encounters/${stayId}/worsening`, { method: "POST" }),

  forecast: (nurses: number, spaces: number) =>
    request<Forecast>(`/v1/operations/forecast?nurses=${nurses}&spaces=${spaces}`),

  logs: (view: "atria" | "nurse", limit = 120) =>
    request<Logs>(`/v1/logs?view=${view}&limit=${limit}`),

  history: (mode: "audit" | "general", limit = 80) =>
    request<History>(`/v1/history?mode=${mode}&limit=${limit}`),

  degraded: (on: boolean) =>
    request<{ degraded: boolean }>(`/api/degraded/${on ? 1 : 0}`, { method: "POST" }),

  shadow: () => request<ShadowReport>("/v1/shadow"),

  /** Open or close treatment bays. Nobody already being treated is turned out. */
  setBays: (count: number) =>
    request<{ slots: number; in_treatment: number; max: number }>(
      `/v1/operations/bays/${count}`, { method: "POST" }),

  /** Check a patient in by hand, then record whatever vitals were taken. */
  addPatient: async (p: {
    stayId: number; age?: number; gender?: string;
    complaint: string; transport: string;
    vitals: Record<string, number | undefined>;
  }) => {
    const q = new URLSearchParams({
      stay_id: String(p.stayId),
      chiefcomplaint: p.complaint || "unspecified",
      arrival_transport: p.transport,
    });
    if (p.age !== undefined) q.set("age", String(p.age));
    if (p.gender) q.set("gender", p.gender);
    await request(`/v1/encounters?${q}`, { method: "POST" });

    // Vitals go as a separate observation so they run through the same path as
    // a reading arriving from a monitor, rather than a second way in.
    const v = new URLSearchParams();
    for (const [k, value] of Object.entries(p.vitals)) {
      if (value !== undefined && !Number.isNaN(value)) v.set(k, String(value));
    }
    if ([...v.keys()].length) {
      await request(`/v1/encounters/${p.stayId}/observations?${v}`,
                    { method: "POST" });
    }
  },

  // Browsers cannot set headers on a WebSocket, so the token rides in the query
  // string. Same signed token, checked the same way on the other end.
  wsUrl: () =>
    `${BASE.replace(/^http/, "ws")}/ws` +
    (session.token ? `?token=${encodeURIComponent(session.token)}` : ""),
};
