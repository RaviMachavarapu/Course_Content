import { type FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Button, Input } from "@/components";
import { ApiError, PASSWORD_RESET_DONE_MESSAGE, authErrorMessage } from "@/lib/api";
import { AuthShell } from "./AuthShell";
import { confirmError, passwordError } from "./validation";
import { studentAuthApi } from "./api";

export function ResetPasswordPage(): JSX.Element {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ password?: string; confirm?: string }>({});
  const [formError, setFormError] = useState<string | null>(null);

  const confirmReset = useMutation({
    mutationFn: () => studentAuthApi.confirmPasswordReset(token, password),
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
        navigate("/login", { replace: true, state: { notice: PASSWORD_RESET_DONE_MESSAGE } }),
      onError: (err) => {
        if (err instanceof ApiError && err.code === "weak_password") {
          setErrors((p) => ({ ...p, password: err.message }));
        } else {
          setFormError(authErrorMessage(err, "Could not reset your password. Try again."));
        }
      },
    });
  }

  if (!token) {
    return (
      <AuthShell title="Invalid reset link" subtitle="This link is missing its reset token.">
        <Link
          to="/forgot-password"
          className="font-label-md text-label-md text-tertiary underline underline-offset-4"
        >
          Request a new link
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Set a new password" subtitle="Choose a new password for your account.">
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
          variant="student"
          loading={confirmReset.isPending}
          fullWidth
          data-testid="btn-reset-confirm"
        >
          Reset password
        </Button>
      </form>
    </AuthShell>
  );
}
