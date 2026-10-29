import { Link } from "react-router-dom";
import { formatCountdown } from "@/lib/api";

interface RateLimitAlertProps {
  /** Seconds left; render only while > 0. */
  seconds: number;
  forgotPath: string;
  testId?: string;
}

/** "Too many attempts — try again in m:ss" with a way out (reset password). */
export function RateLimitAlert({ seconds, forgotPath, testId }: RateLimitAlertProps): JSX.Element {
  return (
    <p
      role="alert"
      aria-live="polite"
      className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-error-container/50 px-3 py-2 font-label-md text-label-md text-on-error-container"
      data-testid={testId}
    >
      <span>Too many attempts — try again in {formatCountdown(seconds)}</span>
      <Link to={forgotPath} className="font-semibold underline underline-offset-4">
        Forgot password?
      </Link>
    </p>
  );
}
