import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Button, Input } from "@/components";
import { AuthShell } from "./AuthShell";
import { emailError } from "./validation";
import { studentAuthApi } from "./api";

export function ForgotPasswordPage(): JSX.Element {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | undefined>();
  const request = useMutation({
    mutationFn: () => studentAuthApi.requestPasswordReset(email),
  });

  function onSubmit(e: FormEvent): void {
    e.preventDefault();
    const next = emailError(email) ?? undefined;
    setError(next);
    if (next) return;
    request.mutate();
  }

  if (request.isSuccess) {
    return (
      <AuthShell title="Check your email" subtitle="If that email has an account, we sent a reset link. It expires in 30 minutes.">
        <Link
          to="/login"
          className="font-label-md text-label-md text-tertiary underline underline-offset-4"
        >
          Back to sign in
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Forgot password"
      subtitle="Enter your email and we'll send you a reset link."
      footer={
        <Link to="/login" className="font-semibold text-tertiary underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
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
          variant="student"
          loading={request.isPending}
          fullWidth
          data-testid="btn-fp1"
        >
          Send reset link
        </Button>
      </form>
    </AuthShell>
  );
}
