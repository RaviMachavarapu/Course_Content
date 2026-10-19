import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Input } from "@/components";
import { ApiError } from "@/lib/api";
import { AuthShell } from "./AuthShell";
import { emailError } from "./validation";
import { useLogin } from "./useStudentAuth";

export function LoginPage(): JSX.Element {
  const navigate = useNavigate();
  const login = useLogin();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);

  function onSubmit(e: FormEvent): void {
    e.preventDefault();
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
        onSuccess: () => navigate("/catalog", { replace: true }),
        onError: (err) => {
          setFormError(err instanceof ApiError ? err.message : "Could not sign in. Try again.");
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
          fullWidth
          data-testid="btn-sl2"
        >
          Sign in
        </Button>
      </form>
    </AuthShell>
  );
}
