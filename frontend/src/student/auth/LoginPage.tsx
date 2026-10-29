import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { type LoginRedirectState, safeFrom } from "@/app/csrfRecovery";
import { Button, Input, RateLimitAlert } from "@/components";
import { authErrorMessage, retryAfterSeconds } from "@/lib/api";
import { useCountdown } from "@/lib/useCountdown";
import { AuthShell } from "./AuthShell";
import { emailError } from "./validation";
import { useLogin } from "./useStudentAuth";

export function LoginPage(): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation() as { state?: LoginRedirectState | null };
  const notice = location.state?.notice;
  const login = useLogin();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);
  const countdown = useCountdown();
  const waiting = countdown.remaining > 0;

  function onSubmit(e: FormEvent): void {
    e.preventDefault();
    if (waiting) return;
    setFormError(null);
    const next = {
      email: emailError(email) ?? undefined,
      password: password ? undefined : "Password is required",
    };
    setErrors(next);
    if (next.email || next.password) return;

    login.mutate(
      { email, password },
      {
        onSuccess: () =>
          navigate(safeFrom(location.state?.from, "/catalog", "student"), { replace: true }),
        onError: (err) => {
          const wait = retryAfterSeconds(err);
          if (wait) countdown.start(wait);
          else setFormError(authErrorMessage(err, "Could not sign in. Try again."));
        },
      },
    );
  }

  return (
    <AuthShell
      title="Sign in"
      subtitle="Welcome back."
      footer={
        <>
          New here?{" "}
          <Link
            to="/register"
            className="font-semibold text-tertiary underline underline-offset-4"
            data-testid="btn-sl4"
          >
            Create account
          </Link>
        </>
      }
    >
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
        {notice && !formError && !waiting && (
          <p
            role="status"
            className="rounded-lg bg-surface-container-high px-3 py-2 font-label-md text-label-md text-on-surface"
          >
            {notice}
          </p>
        )}
        <RateLimitAlert seconds={countdown.remaining} forgotPath="/forgot-password" />
        {formError && (
          <p
            role="alert"
            className="rounded-lg bg-error-container/50 px-3 py-2 font-label-md text-label-md text-on-error-container"
          >
            {formError}
          </p>
        )}
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        <div className="flex items-center justify-between">
          <Link
            to="/forgot-password"
            className="font-label-sm text-label-sm text-on-surface-variant underline underline-offset-4"
            data-testid="btn-sl3"
          >
            Forgot password?
          </Link>
        </div>
        <Button
          type="submit"
          variant="student"
          loading={login.isPending}
          disabled={waiting}
          fullWidth
          data-testid="btn-sl2"
        >
          Sign in
        </Button>
      </form>
    </AuthShell>
  );
}
