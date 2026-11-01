import { type FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Button, Icon, Input } from "@/components";
import { ApiError, PASSWORD_RESET_DONE_MESSAGE, authErrorMessage } from "@/lib/api";
import { confirmError, passwordError } from "@/student/auth/validation";
import { adminAuthApi } from "./api";

export function AdminResetPasswordPage(): JSX.Element {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ password?: string; confirm?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);

  const confirmReset = useMutation({
    mutationFn: () => adminAuthApi.confirmPasswordReset(token, password),
  });

  function onSubmit(e: FormEvent): void {
    e.preventDefault();
    setFormError(null);
    const next = {
      password: passwordError(password) ?? undefined,
      confirm: confirmError(password, confirm) ?? undefined,
    };
    setErrors(next);
    if (next.password || next.confirm) return;

    confirmReset.mutate(undefined, {
      onSuccess: () =>
        navigate("/admin/login", { replace: true, state: { notice: PASSWORD_RESET_DONE_MESSAGE } }),
      onError: (err) => {
        if (err instanceof ApiError && err.code === "weak_password") {
          setErrors((p) => ({ ...p, password: err.message }));
        } else {
          setFormError(authErrorMessage(err, "Could not reset your password. Try again."));
        }
      },
    });
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
          {!token ? (
            <>
              <h1 className="font-headline-md text-headline-md">Invalid reset link</h1>
              <p className="mt-1 font-body-md text-body-md text-on-surface-variant">
                This link is missing its reset token.
              </p>
              <Link
                to="/admin/forgot-password"
                className="mt-5 inline-block font-label-md text-label-md text-tertiary underline underline-offset-4"
              >
                Request a new link
              </Link>
            </>
          ) : (
            <>
              <h1 className="font-headline-md text-headline-md">Set a new password</h1>
              <form className="mt-5 flex flex-col gap-4" onSubmit={onSubmit} noValidate>
                {formError && (
                  <p
                    role="alert"
                    className="rounded-lg bg-error-container/50 px-3 py-2 font-label-md text-label-md text-on-error-container"
                  >
                    {formError}
                  </p>
                )}
                <Input
                  label="New password"
                  type="password"
                  autoComplete="new-password"
                  hint="At least 10 characters, with a letter and a number or symbol."
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  error={errors.password}
                />
                <Input
                  label="Confirm password"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  error={errors.confirm}
                />
                <Button
                  type="submit"
                  variant="primary"
                  loading={confirmReset.isPending}
                  fullWidth
                  data-testid="btn-admin-reset-confirm"
                >
                  Reset password
                </Button>
              </form>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
