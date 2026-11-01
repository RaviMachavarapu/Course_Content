import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Input } from "@/components";
import { ApiError, authErrorMessage } from "@/lib/api";
import { AuthShell } from "./AuthShell";
import { confirmError, displayNameError, emailError, passwordError } from "./validation";
import { useRegister } from "./useStudentAuth";

interface FieldErrors {
  displayName?: string;
  email?: string;
  password?: string;
  confirm?: string;
}

export function RegisterPage(): JSX.Element {
  const navigate = useNavigate();
  const register = useRegister();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);

  function onSubmit(e: FormEvent): void {
    e.preventDefault();
    setFormError(null);
    const next: FieldErrors = {
      displayName: displayNameError(displayName) ?? undefined,
      email: emailError(email) ?? undefined,
      password: passwordError(password) ?? undefined,
      confirm: confirmError(password, confirm) ?? undefined,
    };
    setErrors(next);
    if (next.displayName || next.email || next.password || next.confirm) return;

    register.mutate(
      { email, password, displayName },
      {
        onSuccess: () => navigate("/catalog", { replace: true }),
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            setErrors((p) => ({ ...p, email: err.message }));
          } else if (err instanceof ApiError && err.code === "weak_password") {
            setErrors((p) => ({ ...p, password: err.message }));
          } else {
            setFormError(authErrorMessage(err, "Could not create your account. Try again."));
          }
        },
      },
    );
  }

  return (
    <AuthShell
      title="Create account"
      subtitle="Start learning in a minute."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="font-semibold text-tertiary underline underline-offset-4">
            Sign in
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
          label="Display name"
          autoComplete="name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          error={errors.displayName}
        />
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
          loading={register.isPending}
          fullWidth
          data-testid="btn-sl1"
        >
          Create account
        </Button>
      </form>
    </AuthShell>
  );
}
