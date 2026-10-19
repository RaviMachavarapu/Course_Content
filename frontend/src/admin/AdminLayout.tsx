import { Outlet } from "react-router-dom";
import { SidebarNav, type NavItem } from "@/components";
import { AdminHeader } from "./AdminHeader";

const ADMIN_NAV: NavItem[] = [
  { to: "/admin/ingestion?focus=form", label: "New Artifact", icon: "add_circle", testid: "btn-ig1" },
  { to: "/admin/ingestion", label: "Ingestion", icon: "upload_file", end: true },
  { to: "/admin/review", label: "Review", icon: "fact_check" },
  { to: "/admin/editor", label: "Editor", icon: "edit_note" },
  { to: "/admin/settings", label: "Settings", icon: "settings", footer: true },
];

export function AdminLayout(): JSX.Element {
  return (
    <div className="min-h-screen bg-background text-on-background">
      <SidebarNav items={ADMIN_NAV} title="Shikshak Dp" subtitle="AI Engine" accent="primary" />
      <div className="flex min-h-screen flex-col lg:ml-64">
        <AdminHeader />
        <Outlet />
      </div>
    </div>
  );
}
