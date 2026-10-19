import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";
import { useUIStore } from "@/lib/store";
import { Icon } from "./Icon";

export interface NavItem {
  to: string;
  label: string;
  icon: string;
  /** Pin to the bottom of the list (e.g. Settings). */
  footer?: boolean;
  end?: boolean;
  testid?: string;
}

interface SidebarNavProps {
  items: NavItem[];
  title: string;
  subtitle?: string;
  /** Accent for the logo tile / active item — "primary" (admin) or "tertiary" (student). */
  accent?: "primary" | "tertiary";
}

export function SidebarNav({
  items,
  title,
  subtitle,
  accent = "primary",
}: SidebarNavProps): JSX.Element {
  const open = useUIStore((s) => s.sidebarOpen);
  const setOpen = useUIStore((s) => s.setSidebarOpen);

  const main = items.filter((i) => !i.footer);
  const footer = items.filter((i) => i.footer);

  const link = (item: NavItem): JSX.Element => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      data-testid={item.testid}
      onClick={() => setOpen(false)}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-lg px-3 py-2 font-label-md text-label-md transition-colors",
          isActive
            ? accent === "tertiary"
              ? "bg-tertiary-container/20 font-semibold text-tertiary"
              : "bg-primary-container/20 font-semibold text-primary"
            : "text-on-surface-variant hover:bg-surface-container-high",
        )
      }
    >
      {({ isActive }) => (
        <>
          <Icon name={item.icon} filled={isActive} />
          {item.label}
        </>
      )}
    </NavLink>
  );

  return (
    <>
      {open && (
        <button
          aria-label="Close menu"
          className="fixed inset-0 z-30 bg-inverse-surface/40 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}
      <nav
        className={cn(
          "fixed left-0 top-0 z-40 flex h-screen w-64 flex-col gap-2 border-r border-outline-variant",
          "bg-surface px-md py-lg transition-transform lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="mb-6 flex items-center gap-2 px-2">
          <div
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded",
              accent === "tertiary" ? "bg-tertiary" : "bg-primary",
            )}
          >
            <Icon name="school" filled className="text-[18px] text-white" />
          </div>
          <div className="leading-tight">
            <p className="font-headline-md text-label-md font-extrabold text-primary">{title}</p>
            {subtitle && (
              <p className="font-label-sm text-label-sm text-on-surface-variant">{subtitle}</p>
            )}
          </div>
        </div>

        <ul className="flex flex-1 flex-col gap-1">
          {main.map((i) => (
            <li key={i.to}>{link(i)}</li>
          ))}
        </ul>
        {footer.length > 0 && (
          <ul className="flex flex-col gap-1 border-t border-outline-variant pt-2">
            {footer.map((i) => (
              <li key={i.to}>{link(i)}</li>
            ))}
          </ul>
        )}
      </nav>
    </>
  );
}
