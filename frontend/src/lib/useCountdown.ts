import { useCallback, useEffect, useState } from "react";

/**
 * A seconds countdown to a deadline (measured against the clock, so a
 * throttled background tab still ends on time). `remaining` is 0 when idle.
 */
export function useCountdown(): { remaining: number; start: (seconds: number) => void } {
  const [deadline, setDeadline] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);

  const start = useCallback((seconds: number) => {
    setDeadline(Date.now() + seconds * 1000);
    setRemaining(Math.ceil(seconds));
  }, []);

  useEffect(() => {
    if (deadline === null) return undefined;
    const tick = (): void => {
      const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setRemaining(left);
      if (left === 0) setDeadline(null);
    };
    const id = window.setInterval(tick, 250);
    return () => window.clearInterval(id);
  }, [deadline]);

  return { remaining, start };
}
