import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button, Icon, Input, RateLimitAlert } from "@/components";
import { authErrorMessage, retryAfterSeconds } from "@/lib/api";
import { useCountdown } from "@/lib/useCountdown";
import { emailError } from "@/student/auth/validation";
import { type LoginRedirectState, safeFrom } from "@/app/csrfRecovery";
import { useAdminLogin } from "./useAdminAuth";

export function AdminLoginPage(): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation() as { state?: LoginRedirectState | null };
  const notice = location.state?.notice;
  const login = useAdminLogin();

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
          navigate(safeFrom(location.state?.from, "/admin/ingestion", "admin"), { replace: true }),
        onError: (err) => {
          const wait = retryAfterSeconds(err);
          if (wait) countdown.start(wait);
          else setFormError(authErrorMessage(err, "Could not sign in. Try again."));
        },
      },
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded bg-primary">
            <Icon name="school" filled className="text-[20px] text-white" />
          </div>
          <div className="leading-tight">
            <p className="font-display text-label-md font-extrabold text-primary">Shikshak Dp</p>
            <p className="font-label-sm text-label-sm text-on-surface-variant">Admin console</p>
          </div>
        </div>

        <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-6 shadow-level-1">
          <h1 className="font-headline-md text-headline-md">Admin sign in</h1>
          <form className="mt-5 flex flex-col gap-4" onSubmit={onSubmit} noValidate>
            {notice && !formError && !waiting && (
              <p
                role="status"
                className="rounded-lg bg-surface-container-high px-3 py-2 font-label-md text-label-md text-on-surface"
              >
                {notice}
              </p>
            )}
            {waiting && (
              <RateLimitAlert seconds={countdown.remaining} forgotPath="/admin/forgot-password" />
            )}
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
            <div className="flex justify-end">
              <Link
                to="/admin/forgot-password"
                className="font-label-sm text-label-sm text-on-surface-variant underline underline-offset-4"
                data-testid="btn-al2"
              >
                Forgot password?
              </Link>
            </div>
            <Button
              type="submit"
              variant="primary"
              loading={login.isPending}
              disabled={waiting}
              fullWidth
              data-testid="btn-al1"
            >
              Sign in
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}
