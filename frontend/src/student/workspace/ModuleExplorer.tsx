import { NavLink, useNavigate } from "react-router-dom";
import { Icon, ProgressBar } from "@/components";
import type { ArtifactType } from "../catalog/api";
import type { WorkspaceCourse } from "./api";
import { ARTIFACT_META, WORKSPACE_ARTIFACT_ORDER } from "./artifactMeta";

interface Props {
  course: WorkspaceCourse;
  activeModuleIndex: number;
  activeType?: ArtifactType;
}

export function ModuleExplorer({ course, activeModuleIndex, activeType }: Props): JSX.Element {
  const navigate = useNavigate();
  const current = course.modules.find((m) => m.index === activeModuleIndex) ?? course.modules[0];
  if (!current) return <p className="p-4 text-body-md text-on-surface-variant">No modules.</p>;

  const available = new Set(current.artifacts.map((a) => a.type));

  const switchModule = (index: number) => {
    const target = course.modules.find((m) => m.index === index);
    if (!target) return;
    const keep =
      activeType && target.artifacts.some((a) => a.type === activeType)
        ? activeType
        : target.artifacts[0]?.type;
    navigate(keep ? `/learn/${course.slug}/${index}/${keep}` : `/learn/${course.slug}`);
  };

  return (
    <aside className="flex w-full min-w-0 flex-col gap-4 border-b border-outline-variant p-4 lg:h-full lg:w-72 lg:border-b-0 lg:border-r">
      <div>
        <p className="font-label-sm text-label-sm uppercase tracking-wide text-on-surface-variant">
          Module Explorer
        </p>
        <p className="mt-1 font-label-md text-label-md text-tertiary">
          Current: Unit {current.index + 1}
        </p>
      </div>

      <label className="flex min-w-0 flex-col gap-1">
        <span className="sr-only">Switch module</span>
        <select
          data-testid="module-switcher"
          value={current.index}
          onChange={(e) => switchModule(Number(e.target.value))}
          className="w-full min-w-0 max-w-full rounded-lg border border-outline-variant bg-surface-container-lowest px-3 py-2 text-body-md focus:border-tertiary focus:outline-none focus-visible:shadow-focus"
        >
          {course.modules.map((m) => (
            <option key={m.id} value={m.index}>
              Unit {m.index + 1}: {m.title}
            </option>
          ))}
        </select>
      </label>

      <ProgressBar value={current.percent_complete} showLabel />

      <nav className="flex flex-col gap-1">
        {WORKSPACE_ARTIFACT_ORDER.filter((t) => available.has(t)).map((t) => {
          const meta = ARTIFACT_META[t];
          const done = current.artifacts.find((a) => a.type === t)?.completed;
          return (
            <NavLink
              key={t}
              to={`/learn/${course.slug}/${current.index}/${t}`}
              data-testid={meta.ws}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 font-label-md text-label-md transition-colors ${
                  isActive
                    ? "bg-tertiary-container/20 font-semibold text-tertiary"
                    : "text-on-surface-variant hover:bg-surface-container-high"
                }`
              }
            >
              <Icon name={meta.icon} className="text-[20px]" />
              <span className="flex-1">{meta.label}</span>
              {done && <Icon name="check_circle" filled className="text-[16px] text-secondary" />}
            </NavLink>
          );
        })}
      </nav>
    </aside>
  );
}
