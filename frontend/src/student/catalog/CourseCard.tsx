import { useNavigate } from "react-router-dom";
import { Button, Card, Icon, ProgressBar } from "@/components";
import type { ArtifactType, CatalogCourse } from "./api";

const COUNT_LABELS: Record<ArtifactType, [string, string]> = {
  audio_overview: ["Audio Track", "Audio Tracks"],
  slide_deck: ["Slide Deck", "Slide Decks"],
  flashcards: ["Flashcard Set", "Flashcard Sets"],
  quiz: ["Quiz", "Quizzes"],
  report: ["Report", "Reports"],
  infographic: ["Infographic", "Infographics"],
};
const COUNT_ORDER: ArtifactType[] = [
  "audio_overview",
  "slide_deck",
  "flashcards",
  "quiz",
  "infographic",
  "report",
];

function formatDuration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function CourseCard({ course }: { course: CatalogCourse }): JSX.Element {
  const navigate = useNavigate();
  const counts = COUNT_ORDER.filter((t) => (course.artifact_counts[t] ?? 0) > 0).map((t) => {
    const n = course.artifact_counts[t] ?? 0;
    return `${n} ${COUNT_LABELS[t][n === 1 ? 0 : 1]}`;
  });

  return (
    <Card className="flex flex-col overflow-hidden" data-testid="course-card">
      <div className="relative h-36 bg-tertiary-container/40">
        {course.cover_image_url ? (
          <img
            src={course.cover_image_url}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-tertiary">
            <Icon name="menu_book" className="text-[40px]" />
          </div>
        )}
        {course.total_audio_seconds != null && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-full bg-inverse-surface/70 px-2 py-0.5 font-label-sm text-label-sm text-inverse-on-surface">
            <Icon name="headphones" className="text-[14px]" />
            {formatDuration(course.total_audio_seconds)}
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2 p-4">
        {course.category && (
          <span className="font-label-sm text-label-sm text-tertiary">{course.category}</span>
        )}
        <h3 className="font-headline-md text-headline-md">{course.title}</h3>
        {course.description && (
          <p className="line-clamp-2 text-body-md text-on-surface-variant">{course.description}</p>
        )}
        {counts.length > 0 && (
          <p className="text-label-sm text-on-surface-variant">{counts.join(" · ")}</p>
        )}

        <div className="mt-auto flex flex-col gap-3 pt-2">
          <div className="flex items-center gap-2">
            <ProgressBar value={course.percent_complete} className="flex-1" />
            <span className="font-label-sm text-label-sm tabular-nums text-on-surface-variant">
              {course.percent_complete}% Complete
            </span>
          </div>
          <Button
            variant="student"
            iconLeft="play_arrow"
            data-testid="btn-ct7"
            onClick={() => navigate(`/learn/${course.slug}`)}
          >
            Start Learning
          </Button>
        </div>
      </div>
    </Card>
  );
}
