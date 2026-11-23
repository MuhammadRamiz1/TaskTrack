import { describe, expect, it } from "vitest";

import { ApiError, applyFieldErrors, errorMessage } from "@/lib/api/errors";

describe("ApiError", () => {
  const validation = new ApiError(400, {
    error: {
      code: "validation_error",
      message: "Invalid input.",
      details: { email: ["Taken."], other: "x" },
      request_id: "r1",
    },
  });

  it("exposes the envelope", () => {
    expect(validation.code).toBe("validation_error");
    expect(validation.requestId).toBe("r1");
    expect(validation.fieldErrors).toEqual({ email: "Taken.", other: "x" });
  });

  it("prefers the first field message for generic validation errors", () => {
    expect(errorMessage(validation)).toBe("Taken.");
    expect(errorMessage(new ApiError(409, { error: { code: "task_locked", message: "Read-only." } }))).toBe("Read-only.");
    expect(errorMessage(new ApiError(502, null))).toMatch(/on our side/);
  });

  it("maps only known fields onto a form", () => {
    const set: string[] = [];
    const matched = applyFieldErrors(validation, (name) => set.push(name as string), ["email"]);
    expect(matched).toBe(true);
    expect(set).toEqual(["email"]);
  });
});
