import { z } from "zod";

/** Mirrors the server policy (12+ chars, 3 of 4 character classes). The server re-checks
 * and also rejects common and personal-info-based passwords. */
export const strongPassword = z
  .string()
  .min(12, "Use at least 12 characters")
  .max(128, "Use at most 128 characters")
  .refine(
    (v) => [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(v)).length >= 3,
    "Use at least 3 of: lowercase, uppercase, digits, symbols",
  );

export const email = z.string().trim().min(1, "Email is required").pipe(z.email("Enter a valid email address"));

export const newPasswordForm = z
  .object({ password: strongPassword, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { message: "Passwords do not match", path: ["confirm"] });

export function passwordStrength(value: string): { score: number; label: string } {
  let score = 0;
  if (value.length >= 12) score++;
  if (value.length >= 16) score++;
  score += [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(value)).length - 1;
  score = Math.max(0, Math.min(4, score));
  return { score, label: ["Too weak", "Weak", "Fair", "Good", "Strong"][score] };
}
