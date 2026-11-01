import { Navigate, type RouteObject, createBrowserRouter } from "react-router-dom";
import { AdminLoginPage } from "@/admin/auth/AdminLoginPage";
import { AdminForgotPasswordPage } from "@/admin/auth/AdminForgotPasswordPage";
import { AdminResetPasswordPage } from "@/admin/auth/AdminResetPasswordPage";
import { IngestionPage } from "@/admin/ingestion/IngestionPage";
import { PipelinePage } from "@/admin/ingestion/PipelinePage";
import { CourseStructurePage } from "@/admin/editor/CourseStructurePage";
import { EditorPage } from "@/admin/editor/EditorPage";
import { InspectPage } from "@/admin/inspect/InspectPage";
import { SettingsPage } from "@/admin/settings/SettingsPage";
import { StagingPage } from "@/admin/staging/StagingPage";
import { CatalogPage } from "@/student/catalog/CatalogPage";
import { LoginPage } from "@/student/auth/LoginPage";
import { RegisterPage } from "@/student/auth/RegisterPage";
import { ForgotPasswordPage } from "@/student/auth/ForgotPasswordPage";
import { ResetPasswordPage } from "@/student/auth/ResetPasswordPage";
import { AchievementsPage } from "@/student/me/AchievementsPage";
import { MyListeningPage } from "@/student/me/MyListeningPage";
import { ProgressPage } from "@/student/me/ProgressPage";
import { ArtifactRoute } from "@/student/workspace/ArtifactRoute";
import { OverviewPanel } from "@/student/workspace/OverviewPanel";
import { WorkspaceLayout } from "@/student/workspace/WorkspaceLayout";
import { Placeholder } from "./Placeholder";
import { RouteError } from "./RouteError";
import { RequireAdmin, RequireStudent, RequireStudentRaw } from "./guards";
import { StyleGuide } from "./StyleGuide";

// Each area has two error boundaries: one around its pages (inside the shell,
// so the nav stays usable) and one at the root for errors in the shell itself.
// The sign-in pages have no shell: they get the same boundary on their own.
export const routes: RouteObject[] = [
  // the component gallery is a development aid, not part of the product
  ...(import.meta.env.DEV ? [{ path: "/styleguide", element: <StyleGuide /> }] : []),
  { path: "/login", element: <LoginPage />, errorElement: <RouteError /> },
  { path: "/register", element: <RegisterPage />, errorElement: <RouteError /> },
  { path: "/forgot-password", element: <ForgotPasswordPage />, errorElement: <RouteError /> },
  { path: "/reset-password", element: <ResetPasswordPage />, errorElement: <RouteError /> },

  { path: "/admin/login", element: <AdminLoginPage />, errorElement: <RouteError /> },
  {
    path: "/admin/forgot-password",
    element: <AdminForgotPasswordPage />,
    errorElement: <RouteError />,
  },
  {
    path: "/admin/reset-password",
    element: <AdminResetPasswordPage />,
    errorElement: <RouteError />,
  },
  {
    path: "/admin",
    element: <RequireAdmin />,
    errorElement: <RouteError />,
    children: [
      {
        errorElement: <RouteError />,
        children: [
          { index: true, element: <Navigate to="/admin/ingestion" replace /> },
          { path: "ingestion", element: <IngestionPage /> },
          { path: "pipeline", element: <PipelinePage /> },
          { path: "modules/:moduleId/staging", element: <StagingPage /> },
          { path: "artifacts/:artifactId", element: <InspectPage /> },
          { path: "review", element: <Placeholder area="admin" name="Review" /> },
          { path: "editor", element: <EditorPage /> },
          { path: "editor/:courseId", element: <CourseStructurePage /> },
          { path: "courses", element: <Placeholder area="admin" name="Courses" /> },
          { path: "settings", element: <SettingsPage /> },
          { path: "*", element: <Placeholder area="admin" name="Not found" /> },
        ],
      },
    ],
  },

  {
    path: "/learn/:slug",
    element: <RequireStudentRaw />,
    errorElement: <RouteError />,
    children: [
      {
        element: <WorkspaceLayout />,
        children: [
          {
            errorElement: <RouteError />,
            children: [
              { index: true, element: <OverviewPanel /> },
              { path: ":moduleIndex/:type", element: <ArtifactRoute /> },
            ],
          },
        ],
      },
    ],
  },

  {
    path: "/",
    element: <RequireStudent />,
    errorElement: <RouteError />,
    children: [
      {
        errorElement: <RouteError />,
        children: [
          { index: true, element: <Navigate to="/catalog" replace /> },
          { path: "catalog", element: <CatalogPage /> },
          { path: "my-listening", element: <MyListeningPage /> },
          { path: "progress", element: <ProgressPage /> },
          { path: "achievements", element: <AchievementsPage /> },
          { path: "account", element: <Placeholder area="student" name="Account" /> },
          { path: "*", element: <Placeholder area="student" name="Not found" /> },
        ],
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
