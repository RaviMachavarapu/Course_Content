import { Link } from "react-router-dom";
import { EmptyState, TopBar } from "@/components";

/** Themed stand-in for screens delivered in later phases (T025+/T031+). */
export function Placeholder({ area, name }: { area: string; name: string }): JSX.Element {
  return (
    <>
      <TopBar title={name} />
      <div className="flex-1 p-4 md:p-margin-desktop">
        <EmptyState
          icon="construction"
          title={`${name} — coming soon`}
          description={`The ${area} "${name}" screen is scaffolded and will be built in a later task. The design system and shell are live.`}
          action={
            <Link
              to="/styleguide"
              className="font-label-md text-label-md text-primary underline underline-offset-4"
            >
              View the style guide
            </Link>
          }
        />
      </div>
    </>
  );
}
