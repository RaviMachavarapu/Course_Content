import { cn } from "@/lib/cn";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /**
   * "admin" — flat, bordered, dense (dashboards/tables).
   * "elevated" — Level 2 shadow, hover lift (course cards, active panels).
   */
  variant?: "admin" | "elevated";
  as?: "div" | "article" | "section";
}

export function Card({
  variant = "admin",
  as: Tag = "div",
  className,
  children,
  ...rest
}: CardProps): JSX.Element {
  return (
    <Tag
      className={cn(
        "rounded-xl bg-surface-container-lowest border border-outline-variant",
        variant === "admin" && "shadow-level-1",
        variant === "elevated" &&
          "shadow-level-2 transition-shadow hover:shadow-[0_8px_20px_rgba(46,68,130,0.12)]",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function CardBody({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return <div className={cn("p-4", className)} {...rest} />;
}

export function CardHeader({
  className,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>): JSX.Element {
  return (
    <div
      className={cn(
        "px-4 py-3 border-b border-outline-variant font-label-md text-label-md font-semibold",
        className,
      )}
      {...rest}
    />
  );
}
