import { describe, expect, it } from "vitest";

import { cleanParams, formatClock, formatDuration, initials, titleCase } from "@/lib/utils";
import { passwordStrength, strongPassword } from "@/lib/validation";

describe("formatting", () => {
  it("formats durations and running clocks", () => {
    expect(formatDuration(5400)).toBe("1h 30m");
    expect(formatDuration(45)).toBe("0m");
    expect(formatDuration(null)).toBe("0m");
    expect(formatClock(3725)).toBe("01:02:05");
    expect(formatClock(-5)).toBe("00:00:00");
  });

  it("builds initials and title case", () => {
    expect(initials("Ada  Lovelace King")).toBe("AL");
    expect(initials("")).toBe("?");
    expect(titleCase("IN_PROGRESS")).toBe("In Progress");
  });

  it("drops empty query params so they are not sent", () => {
    expect(cleanParams({ a: "", b: undefined, c: null, d: [], e: 0, f: false, g: "x", h: ["y"] })).toEqual({
      e: 0,
      f: false,
      g: "x",
      h: ["y"],
    });
  });
});

describe("password policy (mirrors the server)", () => {
  it.each([
    ["short1!A", false],
    ["alllowercaseletters", false],
    ["ALLUPPER12345", false],
    ["ALLUPPER12345!", true],
    ["Correct-Horse-9", true],
  ])("%s -> valid=%s", (value, valid) => {
    expect(strongPassword.safeParse(value).success).toBe(valid);
  });

  it("scores strength", () => {
    expect(passwordStrength("abc").score).toBe(0);
    expect(passwordStrength("Correct-Horse-Battery-9").label).toBe("Strong");
  });
});
