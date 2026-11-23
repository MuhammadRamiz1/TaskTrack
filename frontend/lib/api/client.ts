/**
 * Typed API client generated from the OpenAPI schema (openapi-typescript types +
 * openapi-fetch). `api` is the plain client; `$api` adds TanStack Query hooks:
 *
 *   const { data } = $api.useQuery("get", "/api/v1/tasks/{task_id}/", { params: { path: { task_id } } });
 *
 * Every request carries the in-memory access token. A 401 with an expired token
 * triggers one shared refresh and a single retry; any other non-2xx becomes an ApiError.
 */
import createFetchClient, { type Middleware } from "openapi-fetch";
import createQueryClient from "openapi-react-query";

import { getAccessToken, readCookie, refreshSession } from "@/lib/auth/token";

import { ApiError } from "./errors";
import type { paths } from "./schema";

const RETRY_CODES = new Set(["token_expired", "token_invalid", "session_revoked", "not_authenticated"]);
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function withAuth(request: Request): Request {
  const headers = new Headers(request.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (UNSAFE.has(request.method)) headers.set("X-CSRFToken", readCookie("csrftoken") ?? "");
  return new Request(request, { headers, credentials: "same-origin" });
}

async function errorBody(response: Response) {
  try {
    return await response.clone().json();
  } catch {
    return null;
  }
}

/** fetch with auth, one refresh-and-retry on 401. Also used for downloads and uploads. */
export async function authFetch(input: Request): Promise<Response> {
  const retry = input.clone();
  const response = await fetch(withAuth(input));
  if (response.status !== 401 || input.url.includes("/auth/refresh/")) return response;
  const body = await errorBody(response);
  if (!RETRY_CODES.has(body?.error?.code)) return response;
  const me = await refreshSession();
  return me ? fetch(withAuth(retry)) : response;
}

const throwOnError: Middleware = {
  async onResponse({ response }) {
    if (!response.ok) throw new ApiError(response.status, await errorBody(response));
    return response;
  },
};

export const api = createFetchClient<paths>({ baseUrl: "", fetch: authFetch });
api.use(throwOnError);

export const $api = createQueryClient(api);

/** Download a protected file (attachments, exports) and hand it to the browser. */
export async function downloadFile(url: string, fallbackName: string) {
  const response = await authFetch(new Request(url));
  if (!response.ok) throw new ApiError(response.status, await errorBody(response));
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallbackName;
  const blobUrl = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = decodeURIComponent(name);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
}

/** Multipart upload (attachments). */
export async function uploadFile(url: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  const response = await authFetch(new Request(url, { method: "POST", body: form }));
  if (!response.ok) throw new ApiError(response.status, await errorBody(response));
  return response.json();
}
