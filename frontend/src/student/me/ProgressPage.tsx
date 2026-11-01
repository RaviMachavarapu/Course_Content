import { TopBar } from "@/components";
import { LogoutButton } from "../auth/LogoutButton";

export function ProgressPage(): JSX.Element {
  return <TopBar title="Progress" right={<LogoutButton />} />;
}
