import { Chip, type ChipStatus, Icon } from "@/components";
import { cn } from "@/lib/cn";
import { STATUS_LABELS, toChipStatus } from "./statusMap";

export function StatusChip({ status }: { status: string }): JSX.Element {
  return <Chip status={toChipStatus(status)}>{STATUS_LABELS[status] ?? undefined}</Chip>;
}

const DOT_COLOR: Record<ChipStatus, string> = {
  ready: "bg-secondary",
  processing: "bg-tertiary",
  error: "bg-error",
  published: "bg-primary",
  pending: "bg-outline-variant",
};

/** Small coloured dot for the six-per-row pipeline indicator. */
export function StatusDot({ status, title }: { status: string; title?: string }): JSX.Element {
  return (
    <span
      title={title}
      className={cn("inline-block h-2.5 w-2.5 rounded-full", DOT_COLOR[toChipStatus(status)])}
    />
  );
}

/**
 * `isFixture` distinguishes `FixtureProvider`'s always-healthy stand-in from
 * a real NotebookLM session, so this never claims "Connected" when no
 * Google account has actually been linked (the dev default,
 * `CONTENT_PROVIDER=fixture`, has no live MCP session at all).
 */
export function McpBadge({
  healthy,
  isFixture,
}: {
  healthy: boolean | undefined;
  isFixture?: boolean;
}): JSX.Element {
  const state = isFixture ? "fixture" : healthy === undefined ? "unknown" : healthy ? "ok" : "down";
  const style = {
    ok: "bg-secondary-container text-on-secondary-container",
    down: "bg-warning-container text-warning border border-warning-outline",
    unknown: "bg-surface-container-high text-on-surface-variant",
    fixture: "bg-surface-container-high text-on-surface-variant",
  }[state];
  const label = isFixture
    ? "NotebookLM: Fixture (dev)"
    : `NotebookLM: ${healthy === undefined ? "…" : healthy ? "Connected" : "Disconnected"}`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-label-sm text-label-sm",
        style,
      )}
    >
      <Icon
        name={isFixture ? "science" : healthy ? "cloud_done" : "cloud_off"}
        className="text-[16px]"
      />
      {label}
    </span>
  );
}

/** T043 — worker liveness, derived from `beat`'s periodic healthcheck heartbeat. */
export function WorkerBadge({ stale }: { stale: boolean | undefined }): JSX.Element {
  const state = stale === undefined ? "unknown" : stale ? "down" : "ok";
  const style = {
    ok: "bg-secondary-container text-on-secondary-container",
    down: "bg-warning-container text-warning border border-warning-outline",
    unknown: "bg-surface-container-high text-on-surface-variant",
  }[state];
  return (
    <span
      data-testid="worker-badge"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-label-sm text-label-sm",
        style,
      )}
    >
      <Icon name={stale ? "warning" : "bolt"} className="text-[16px]" />
      Worker: {stale === undefined ? "…" : stale ? "Stale" : "OK"}
    </span>
  );
}
