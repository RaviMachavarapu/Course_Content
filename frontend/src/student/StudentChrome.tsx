import { SidebarNav, type NavItem } from "@/components";

const STUDENT_NAV: NavItem[] = [
  { to: "/catalog", label: "Catalog", icon: "grid_view" },
  { to: "/my-listening", label: "My Listening", icon: "headphones" },
  { to: "/progress", label: "Progress", icon: "trending_up" },
  { to: "/achievements", label: "Achievements", icon: "military_tech" },
  { to: "/account", label: "Account", icon: "person", footer: true },
];

/** Student sidebar + main column. Wrap page content (or an `<Outlet />`). */
export function StudentChrome({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <div className="min-h-screen bg-background text-on-background">
      <SidebarNav items={STUDENT_NAV} title="Shikshak Dp" subtitle="Learn" accent="tertiary" />
      <div className="flex min-h-screen flex-col lg:ml-64">{children}</div>
    </div>
  );
}
