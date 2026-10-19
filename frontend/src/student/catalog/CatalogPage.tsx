import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, Icon, Skeleton, TopBar } from "@/components";
import { useLogout } from "../auth/useStudentAuth";
import { CourseCard } from "./CourseCard";
import { useCatalog } from "./useCatalog";

function ProfileMenu(): JSX.Element {
  const navigate = useNavigate();
  const logout = useLogout();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        aria-label="Profile menu"
        data-testid="btn-ct5"
        onClick={() => setOpen((v) => !v)}
        className="flex h-8 w-8 items-center justify-center rounded-full bg-tertiary text-on-tertiary focus-visible:outline-none focus-visible:shadow-focus"
      >
        <Icon name="person" filled className="text-[18px]" />
      </button>
      {open && (
        <>
          <button
            aria-hidden="true"
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 cursor-default"
          />
          <div className="absolute right-0 z-40 mt-1 w-40 rounded-lg border border-outline-variant bg-surface-container-lowest py-1 shadow-level-2">
            <button
              onClick={() =>
                logout.mutate(undefined, {
                  onSettled: () => navigate("/login", { replace: true }),
                })
              }
              className="flex w-full items-center gap-2 px-3 py-2 text-left font-label-md text-label-md hover:bg-surface-container-high focus-visible:outline-none focus-visible:shadow-focus"
            >
              <Icon name="logout" className="text-[18px]" />
              Log out
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function CatalogPage(): JSX.Element {
  const { data, isPending, isError, refetch } = useCatalog();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>("All");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.courses ?? []).filter((c) => {
      const matchesQuery =
        !q ||
        c.title.toLowerCase().includes(q) ||
        c.description.toLowerCase().includes(q);
      const matchesCategory = category === "All" || c.category === category;
      return matchesQuery && matchesCategory;
    });
  }, [data?.courses, query, category]);

  const chips = ["All", ...(data?.categories ?? [])];

  return (
    <>
      <TopBar
        title="Course Catalogs"
        right={
          <>
            <label className="relative hidden items-center sm:flex">
              <Icon
                name="search"
                className="pointer-events-none absolute left-2 text-[18px] text-on-surface-variant"
              />
              <input
                aria-label="Search courses"
                data-testid="btn-ct1"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search courses"
                className="w-56 rounded-full border border-outline-variant bg-surface-container-lowest py-1.5 pl-8 pr-3 text-body-md focus:border-tertiary focus:outline-none focus-visible:shadow-focus"
              />
            </label>
            <ProfileMenu />
          </>
        }
      />

      <div className="flex flex-1 flex-col gap-5 p-4 md:p-margin-desktop">
        <p className="text-body-md text-on-surface-variant">
          Browse published courses and pick up where you left off.
        </p>

        <div className="flex sm:hidden">
          <input
            aria-label="Search courses"
            data-testid="btn-ct1-mobile"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search courses"
            className="w-full rounded-full border border-outline-variant bg-surface-container-lowest px-4 py-2 text-body-md focus:border-tertiary focus:outline-none focus-visible:shadow-focus"
          />
        </div>

        {chips.length > 1 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by category">
            {chips.map((c) => (
              <button
                key={c}
                data-testid="category-chip"
                aria-pressed={category === c}
                onClick={() => setCategory(c)}
                className={
                  category === c
                    ? "rounded-full bg-tertiary px-3 py-1 font-label-md text-label-md text-on-tertiary focus-visible:outline-none focus-visible:shadow-focus"
                    : "rounded-full border border-outline-variant px-3 py-1 font-label-md text-label-md text-on-surface-variant hover:border-tertiary focus-visible:outline-none focus-visible:shadow-focus"
                }
              >
                {c}
              </button>
            ))}
          </div>
        )}

        {isError && <ErrorState title="Could not load the catalog" onRetry={() => void refetch()} />}

        {isPending && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-72" />
            ))}
          </div>
        )}

        {data && filtered.length === 0 && (
          <EmptyState
            icon="school"
            title={data.courses.length === 0 ? "No courses yet" : "No courses match your filters"}
            description={
              data.courses.length === 0
                ? "Published courses will show up here."
                : "Try a different search or category."
            }
          />
        )}

        {filtered.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((course) => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
