import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Button, Icon, Input } from "@/components";
import { emailError } from "@/student/auth/validation";
import { adminAuthApi } from "./api";

export function AdminForgotPasswordPage(): JSX.Element {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | undefined>();
  const request = useMutation({
    mutationFn: () => adminAuthApi.requestPasswordReset(email),
  });

  function onSubmit(e: FormEvent): void {
    e.preventDefault();
    const next = emailError(email) ?? undefined;
    setError(next);
    if (next) return;
    request.mutate();
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
          {request.isSuccess ? (
            <>
              <h1 className="font-headline-md text-headline-md">Check your email</h1>
              <p className="mt-1 font-body-md text-body-md text-on-surface-variant">
                If that email has an admin account, we sent a reset link. It expires in 30
                minutes.
              </p>
              <Link
                to="/admin/login"
                className="mt-5 inline-block font-label-md text-label-md text-tertiary underline underline-offset-4"
              >
                Back to sign in
              </Link>
            </>
          ) : (
            <>
              <h1 className="font-headline-md text-headline-md">Forgot password</h1>
              <p className="mt-1 font-body-md text-body-md text-on-surface-variant">
                Enter your email and we&apos;ll send you a reset link.
              </p>
              <form className="mt-5 flex flex-col gap-4" onSubmit={onSubmit} noValidate>
                <Input
                  label="Email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  error={error}
                />
                <Button
                  type="submit"
                  variant="primary"
                  loading={request.isPending}
                  fullWidth
                  data-testid="btn-afp1"
                >
                  Send reset link
                </Button>
              </form>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
