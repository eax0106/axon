import type { paths } from "@axon/contracts";
import createClient from "openapi-fetch";

const TOKEN_KEY = "axon.token";
const CHANGED = "axon:session";

// Storage can throw (private mode, blocked site data); the app then works for the tab's life.
let memoryToken: string | null = null;
export const session = {
  token(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return memoryToken;
    }
  },
  /** Sign in (a token) or out (null); everything subscribed re-renders. */
  set(token: string | null): void {
    memoryToken = token;
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* memoryToken holds it */
    }
    window.dispatchEvent(new Event(CHANGED));
  },
  subscribe(onChange: () => void): () => void {
    window.addEventListener(CHANGED, onChange);
    window.addEventListener("storage", onChange); // signed in or out in another tab
    return () => {
      window.removeEventListener(CHANGED, onChange);
      window.removeEventListener("storage", onChange);
    };
  },
};

/** What the API says when a feature needs a vendor key that isn't set (see app/main.py). */
export type ProviderNotConfigured = {
  error: "provider_not_configured";
  kind: string;
  provider: string;
  missing_keys: string[];
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(detailOf(body) ?? `Request failed (${status})`);
  }

  get provider(): ProviderNotConfigured | null {
    const b = this.body as Partial<ProviderNotConfigured> | null;
    return this.status === 503 && b?.error === "provider_not_configured"
      ? (b as ProviderNotConfigured)
      : null;
  }
}

function detailOf(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: a list of {msg}.
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg).join(", ");
  return null;
}

export const api = createClient<paths>({ baseUrl: "/api" });

api.use({
  onRequest({ request }) {
    const token = session.token();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    // An expired or revoked session: drop it and let the app send the user to sign in.
    if (response.status === 401 && session.token()) session.set(null);
    return response;
  },
});

/**
 * The response body, or ApiError on any non-2xx answer. Typed from the schema; most responses
 * are declared there as plain objects, so for those the caller names the shape it reads (T).
 */
export async function unwrap<T = never, D = unknown>(
  request: Promise<{ data?: D; error?: unknown; response: Response }>,
): Promise<[T] extends [never] ? D : T> {
  const { data, error, response } = await request;
  if (!response.ok) throw new ApiError(response.status, error);
  return data as [T] extends [never] ? D : T;
}
