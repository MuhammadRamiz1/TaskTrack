"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { loginSchema } from "@/lib/validations/auth";

const inputWrap =
  "flex items-center rounded-[14px] border-[1.5px] transition focus-within:shadow-focus";
const inputOk =
  "border-line bg-primary-50 focus-within:border-primary focus-within:bg-surface";
const inputErr =
  "border-danger bg-danger-soft focus-within:shadow-[0_0_0_4px_rgb(229_72_77/0.15)]";

function FieldError({ id, message }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="text-[12.5px] font-medium text-danger">
      {message}
    </p>
  );
}

export default function LoginForm() {
  const [showPassword, setShowPassword] = useState(false);
  const [success, setSuccess] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm({
    resolver: zodResolver(loginSchema),
    mode: "onTouched",
    defaultValues: { email: "", password: "", remember: false },
  });

  const onSubmit = async (data) => {
    setSuccess(false);
    // TODO: replace with your real auth call to the backend
    await new Promise((r) => setTimeout(r, 900));
    console.log("Login payload:", data);
    setSuccess(true);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-[18px]">
      {/* Email */}
      <div className="flex flex-col gap-[7px]">
        <label htmlFor="email" className="text-[13.5px] font-semibold text-ink">
          Email
        </label>
        <div className={`${inputWrap} ${errors.email ? inputErr : inputOk}`}>
          <svg className="ml-3.5 size-[19px] shrink-0 text-primary-400" viewBox="0 0 24 24" fill="none" aria-hidden>
            <rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" strokeWidth="1.8" />
            <path d="M4 7l8 6 8-6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            id="email"
            type="email"
            placeholder="you@company.com"
            autoComplete="email"
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? "email-error" : undefined}
            className="min-w-0 flex-1 bg-transparent py-3.5 pr-3.5 pl-2.5 text-[15px] text-ink outline-none placeholder:text-placeholder"
            {...register("email")}
          />
        </div>
        <FieldError id="email-error" message={errors.email?.message} />
      </div>

      {/* Password */}
      <div className="flex flex-col gap-[7px]">
        <label htmlFor="password" className="text-[13.5px] font-semibold text-ink">
          Password
        </label>
        <div className={`${inputWrap} ${errors.password ? inputErr : inputOk}`}>
          <svg className="ml-3.5 size-[19px] shrink-0 text-primary-400" viewBox="0 0 24 24" fill="none" aria-hidden>
            <rect x="4.5" y="10" width="15" height="10" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
            <path d="M8 10V7.5a4 4 0 018 0V10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            id="password"
            type={showPassword ? "text" : "password"}
            placeholder="Enter your password"
            autoComplete="current-password"
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? "password-error" : undefined}
            className="min-w-0 flex-1 bg-transparent py-3.5 pr-3.5 pl-2.5 text-[15px] text-ink outline-none placeholder:text-placeholder"
            {...register("password")}
          />
          <button
            type="button"
            onClick={() => setShowPassword((s) => !s)}
            aria-label={showPassword ? "Hide password" : "Show password"}
            className="grid cursor-pointer place-items-center px-3.5 text-muted hover:text-primary"
          >
            {showPassword ? (
              <svg className="size-[19px]" viewBox="0 0 24 24" fill="none">
                <path d="M3 3l18 18M10.6 10.6a2 2 0 002.8 2.8M9.9 5.1A9.8 9.8 0 0112 5c5 0 9 5 9 7 0 .9-.8 2.4-2.2 3.8M6.1 6.1C4.1 7.6 3 9.9 3 12c0 2 4 7 9 7 1.6 0 3-.4 4.3-1.1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            ) : (
              <svg className="size-[19px]" viewBox="0 0 24 24" fill="none">
                <path d="M3 12c0-2 4-7 9-7s9 5 9 7-4 7-9 7-9-5-9-7z" stroke="currentColor" strokeWidth="1.8" />
                <circle cx="12" cy="12" r="2.8" stroke="currentColor" strokeWidth="1.8" />
              </svg>
            )}
          </button>
        </div>
        <FieldError id="password-error" message={errors.password?.message} />
      </div>

      {/* Remember / forgot */}
      <div className="flex items-center justify-between text-[13.5px]">
        <label className="inline-flex cursor-pointer items-center gap-2.5 text-muted select-none">
          <input
            type="checkbox"
            className="size-[18px] cursor-pointer rounded-md accent-primary-500"
            {...register("remember")}
          />
          Remember me
        </label>
        <a href="#forgot" className="font-semibold text-primary-600 hover:underline">
          Forgot password?
        </a>
      </div>

      <button
        type="submit"
        disabled={isSubmitting}
        className="mt-1 grid h-[52px] cursor-pointer place-items-center rounded-[14px] bg-linear-135 from-primary-400 to-primary-600 text-[15.5px] font-bold text-white shadow-button transition hover:-translate-y-px hover:brightness-105 disabled:cursor-progress disabled:opacity-75"
      >
        {isSubmitting ? (
          <span
            aria-label="Signing in"
            className="size-5 animate-spin rounded-full border-[2.5px] border-white/40 border-t-white"
          />
        ) : (
          "Sign in"
        )}
      </button>

      {success && (
        <p role="status" className="text-center text-[13.5px] font-semibold text-success">
          ✓ Signed in successfully
        </p>
      )}

      <div className="flex items-center gap-3 text-[12.5px] text-placeholder before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">
        or continue with
      </div>

      <button
        type="button"
        className="flex h-[50px] cursor-pointer items-center justify-center gap-2.5 rounded-[14px] border-[1.5px] border-line bg-surface text-[14.5px] font-semibold text-ink transition hover:border-primary-300 hover:bg-primary-50"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
          <path fill="#4285F4" d="M22 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.6a4.8 4.8 0 01-2.1 3.1v2.6h3.4c2-1.8 3.1-4.5 3.1-7.5z" />
          <path fill="#34A853" d="M12 22c2.8 0 5.2-.9 6.9-2.5l-3.4-2.6c-.9.6-2.1 1-3.5 1-2.7 0-5-1.8-5.8-4.3H2.7v2.7A10 10 0 0012 22z" />
          <path fill="#FBBC05" d="M6.2 13.6a6 6 0 010-3.8V7.1H2.7a10 10 0 000 9.2l3.5-2.7z" />
          <path fill="#EA4335" d="M12 5.9c1.5 0 2.9.5 4 1.6l3-3A10 10 0 002.7 7.1l3.5 2.7C7 7.7 9.3 5.9 12 5.9z" />
        </svg>
        Sign in with Google
      </button>
    </form>
  );
}
