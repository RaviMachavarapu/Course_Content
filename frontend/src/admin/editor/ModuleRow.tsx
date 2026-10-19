import { useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "@/components";
import { ARTIFACT_LABELS, ARTIFACT_TYPES, type ModuleSummary } from "../api";
import { StatusChip, StatusDot } from "../AdminStatus";

interface ModuleRowProps {
  module: ModuleSummary;
  index: number;
  isFirst: boolean;
  isLast: boolean;
  busy: boolean;
  onRename: () => void;
  onMove: (direction: "up" | "down") => void;
  onRegenerate: () => void;
  onDelete: () => void;
}

export function ModuleRow({
  module,
  index,
  isFirst,
  isLast,
  busy,
  onRename,
  onMove,
  onRegenerate,
  onDelete,
}: ModuleRowProps): JSX.Element {
  const [menuOpen, setMenuOpen] = useState(false);
  const byType = new Map(module.artifacts.map((a) => [a.type, a]));
  const close = () => setMenuOpen(false);

  const item = (
    testId: string,
    label: string,
    icon: string,
    onClick: () => void,
    disabled = false,
    danger = false,
  ) => (
    <button
      type="button"
      role="menuitem"
      data-testid={testId}
      disabled={disabled}
      onClick={() => {
        close();
        onClick();
      }}
      className={`flex w-full items-center gap-2 px-3 py-2 text-left font-label-md text-label-md hover:bg-surface-container-high focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-40 ${
        danger ? "text-error" : "text-on-surface"
      }`}
    >
      <Icon name={icon} className="text-[18px]" />
      {label}
    </button>
  );

  return (
    <div className="rounded-xl border border-outline-variant bg-surface-container-lowest">
      <div className="flex flex-wrap items-start justify-between gap-3 p-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-label-sm text-label-sm text-on-surface-variant">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="font-label-lg text-label-lg text-on-surface">{module.title}</span>
            <StatusChip status={module.status} />
          </div>
          <div className="mt-1 truncate text-label-sm text-on-surface-variant">
            {module.source_url}
          </div>
        </div>

        <div className="relative">
          <button
            type="button"
            aria-label={`Actions for ${module.title}`}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            data-testid="btn-ce2"
            disabled={busy}
            onClick={() => setMenuOpen((v) => !v)}
            className="rounded-full p-1.5 text-on-surface-variant hover:bg-surface-container-high focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-40"
          >
            <Icon name="more_vert" />
          </button>
          {menuOpen && (
            <>
              <button
                type="button"
                aria-hidden="true"
                tabIndex={-1}
                onClick={close}
                className="fixed inset-0 z-10 cursor-default"
              />
              <div
                role="menu"
                className="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest py-1 shadow-level-2"
              >
                <Link
                  role="menuitem"
                  data-testid="btn-ce3"
                  to={`/admin/modules/${module.id}/staging`}
                  onClick={close}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left font-label-md text-label-md text-on-surface hover:bg-surface-container-high focus-visible:outline-none focus-visible:shadow-focus"
                >
                  <Icon name="rate_review" className="text-[18px]" />
                  Open staging
                </Link>
                {item("btn-ce4", "Rename", "edit", onRename)}
                {item("btn-ce5", "Move up", "arrow_upward", () => onMove("up"), isFirst)}
                {item("btn-ce6", "Move down", "arrow_downward", () => onMove("down"), isLast)}
                {item("btn-ce7", "Re-run all", "restart_alt", onRegenerate)}
                {item("btn-ce8", "Delete", "delete", onDelete, false, true)}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 border-t border-outline-variant/60 p-4 sm:grid-cols-3 md:grid-cols-6">
        {ARTIFACT_TYPES.map((t) => {
          const artifact = byType.get(t);
          const inner = (
            <>
              <div className="flex items-center justify-between">
                <span className="font-label-sm text-label-sm text-on-surface-variant">
                  {ARTIFACT_LABELS[t]}
                </span>
                <StatusDot status={artifact?.status ?? "pending"} title={artifact?.status} />
              </div>
              <span className="mt-1 block font-label-sm text-label-sm capitalize text-on-surface">
                {artifact?.status ?? "pending"}
              </span>
            </>
          );
          return artifact ? (
            <Link
              key={t}
              data-testid="btn-ce9"
              to={`/admin/artifacts/${artifact.id}`}
              className="rounded-lg border border-outline-variant/60 p-2 hover:border-primary focus-visible:outline-none focus-visible:shadow-focus"
            >
              {inner}
            </Link>
          ) : (
            <div key={t} className="rounded-lg border border-outline-variant/60 p-2 opacity-60">
              {inner}
            </div>
          );
        })}
      </div>
    </div>
  );
}
