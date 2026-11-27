"use client";

import { Eye, EyeOff } from "lucide-react";
import * as React from "react";

import { Input } from "@/components/ui/form";
import { cn } from "@/lib/utils";
import { passwordStrength } from "@/lib/validation";

export const PasswordInput = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { showStrength?: boolean }
>(({ showStrength, className, ...props }, ref) => {
  const [visible, setVisible] = React.useState(false);
  const value = String(props.value ?? "");
  const strength = passwordStrength(value);
  return (
    <div>
      <div className="relative">
        <Input ref={ref} type={visible ? "text" : "password"} className={cn("pr-11", className)} {...props} />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="absolute inset-y-0 right-0 grid w-11 place-items-center text-muted hover:text-ink"
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
      {showStrength && value && (
        <div className="mt-2 flex items-center gap-2" aria-live="polite">
          <div className="flex flex-1 gap-1" aria-hidden>
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className={cn(
                  "h-1.5 flex-1 rounded-full",
                  i < strength.score ? (strength.score >= 3 ? "bg-success" : "bg-warning") : "bg-line",
                )}
              />
            ))}
          </div>
          <span className="text-xs font-semibold text-muted">{strength.label}</span>
        </div>
      )}
    </div>
  );
});
PasswordInput.displayName = "PasswordInput";
