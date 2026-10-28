import { Link, useOutletContext, useParams } from "react-router-dom";
import { EmptyState } from "@/components";
import type { ArtifactType } from "../catalog/api";
import { ARTIFACT_META, WORKSPACE_ARTIFACT_ORDER } from "./artifactMeta";
import { AudioPlayer } from "./audio/AudioPlayer";
import { FlashcardsViewer } from "./flashcards/FlashcardsViewer";
import { InfographicViewer } from "./infographic/InfographicViewer";
import { QuizViewer } from "./quiz/QuizViewer";
import { ReportViewer } from "./report/ReportViewer";
import { SlidesViewer } from "./slides/SlidesViewer";
import type { WorkspaceContext } from "./WorkspaceLayout";

export function ArtifactRoute(): JSX.Element | null {
  const { course } = useOutletContext<WorkspaceContext>();
  const { moduleIndex, type } = useParams();
  const idx = Number(moduleIndex);
  const artifactType = type as ArtifactType;

  const module = course.modules.find((m) => m.index === idx);
  const entry = module?.artifacts.find((a) => a.type === artifactType);

  if (!module || !entry || !ARTIFACT_META[artifactType]) {
    return (
      <EmptyState
        icon="do_not_disturb_on"
        title="Not available"
        description="This resource hasn’t been published for this module."
        action={
          <Link
            to={`/learn/${course.slug}`}
            className="font-label-md text-label-md text-tertiary underline underline-offset-4"
          >
            Back to Course Overview
          </Link>
        }
      />
    );
  }

  // `key` gives each artifact a fresh viewer: the module switcher keeps the
  // type, so without it React would reuse the old deck's state (index, seen
  // cards, audio seek flag) for the new artifact.
  if (artifactType === "slide_deck")
    return <SlidesViewer key={entry.id} artifactId={entry.id} slug={course.slug} />;
  if (artifactType === "flashcards")
    return <FlashcardsViewer key={entry.id} artifactId={entry.id} slug={course.slug} />;
  if (artifactType === "quiz")
    return <QuizViewer key={entry.id} artifactId={entry.id} slug={course.slug} />;
  if (artifactType === "report")
    return <ReportViewer key={entry.id} artifactId={entry.id} slug={course.slug} />;
  if (artifactType === "audio_overview")
    return (
      <AudioPlayer
        key={entry.id}
        artifactId={entry.id}
        slug={course.slug}
        nextHref={nextResourceHref(course, module.index, artifactType)}
        moduleTitle={module.title}
      />
    );
  if (artifactType === "infographic")
    return (
      <InfographicViewer
        key={entry.id}
        artifactId={entry.id}
        slug={course.slug}
        moduleTitle={module.title}
      />
    );

  // exhaustive: every ArtifactType has a real viewer above
  return null;
}

/** Where "Next Lesson" goes: the next published type in this module, else the
 * first published type of the next module, else the course overview. */
function nextResourceHref(
  course: WorkspaceContext["course"],
  moduleIndex: number,
  type: ArtifactType,
): string {
  const module = course.modules.find((m) => m.index === moduleIndex);
  if (!module) return `/learn/${course.slug}`;
  const here = WORKSPACE_ARTIFACT_ORDER.indexOf(type);
  const nextInModule = WORKSPACE_ARTIFACT_ORDER.slice(here + 1).find((t) =>
    module.artifacts.some((a) => a.type === t),
  );
  if (nextInModule) return `/learn/${course.slug}/${moduleIndex}/${nextInModule}`;

  const nextModule = course.modules.find((m) => m.index === moduleIndex + 1);
  const firstType = nextModule
    ? WORKSPACE_ARTIFACT_ORDER.find((t) => nextModule.artifacts.some((a) => a.type === t))
    : undefined;
  if (nextModule && firstType) return `/learn/${course.slug}/${nextModule.index}/${firstType}`;
  return `/learn/${course.slug}`;
}
