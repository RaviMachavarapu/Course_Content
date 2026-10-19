import { Outlet } from "react-router-dom";
import { StudentChrome } from "./StudentChrome";

export function StudentLayout(): JSX.Element {
  return (
    <StudentChrome>
      <Outlet />
    </StudentChrome>
  );
}
