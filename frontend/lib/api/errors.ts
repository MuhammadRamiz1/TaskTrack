/** Error envelope returned by every API error: {"error": {code, message, details, request_id}}. */
export type ErrorEnvelope = {
  error: { code: string; message: string; details?: Record<string, unknown>; request_id?: string };
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId?: string;

  constructor(status: number, body: Partial<ErrorEnvelope> | null) {
    const err = body?.error;
    super(err?.message ?? (status >= 500 ? "Something went wrong on our side. Please try again." : "Request failed."));
    this.name = "ApiError";
    this.status = status;
    this.code = err?.code ?? (status >= 500 ? "server_error" : "unknown_error");
    this.details = err?.details ?? {};
    this.requestId = err?.request_id;
  }

  /** Field errors from a validation_error, as {field: "first message"}. */
  get fieldErrors(): Record<string, string> {
    if (this.code !== "validation_error" && this.code !== "comment_required") return {};
    const out: Record<string, string> = {};
    for (const [field, value] of Object.entries(this.details)) {
      if (Array.isArray(value) && value.length) out[field] = String(value[0]);
      else if (typeof value === "string") out[field] = value;
    }
    return out;
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const fields = Object.values(error.fieldErrors);
    return fields.length && error.message === "Invalid input." ? fields[0] : error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

/** Copy server field errors onto a react-hook-form instance; returns true if any matched. */
export function applyFieldErrors(
  error: unknown,
  setError: (name: never, error: { type: string; message: string }) => void,
  known: readonly string[],
): boolean {
  if (!(error instanceof ApiError)) return false;
  let matched = false;
  for (const [field, message] of Object.entries(error.fieldErrors)) {
    if (known.includes(field)) {
      setError(field as never, { type: "server", message });
      matched = true;
    }
  }
  return matched;
}
