import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { formatCountdown } from "@/lib/api";

interface RateLimitAlertProps {
  /** Seconds left; the visible box shows only while > 0. Keep this mounted. */
  seconds: number;
  forgotPath: string;
}

export const RATE_LIMIT_ENDED_MESSAGE = "You can try signing in again.";

/**
 * "Too many attempts — try again in m:ss" with a way out (reset password).
 *
 * Screen readers hear it twice: once when the wait starts and once when it
 * ends, through a polite live region that stays mounted. The ticking box
 * itself is not a live region, so the time isn't read out every second.
 */
export function RateLimitAlert({ seconds, forgotPath }: RateLimitAlertProps): JSX.Element {
  const active = seconds > 0;
  const wasActive = useRef(false);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    if (active && !wasActive.current) {
      setAnnouncement(`Too many attempts. Try again in ${formatCountdown(seconds)}.`);
    } else if (!active && wasActive.current) {
      setAnnouncement(RATE_LIMIT_ENDED_MESSAGE);
    }
    wasActive.current = active;
  }, [active, seconds]);

  return (
    <>
      <p aria-live="polite" className="sr-only" data-testid="rate-limit-announcement">
        {announcement}
      </p>
      {active && (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-error-container/50 px-3 py-2 font-label-md text-label-md text-on-error-container"
          data-testid="rate-limit-countdown"
        >
          <span>Too many attempts — try again in {formatCountdown(seconds)}</span>
          <Link to={forgotPath} className="font-semibold underline underline-offset-4">
            Forgot password?
          </Link>
        </div>
      )}
    </>
  );
}
