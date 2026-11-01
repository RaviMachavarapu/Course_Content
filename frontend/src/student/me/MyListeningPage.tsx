import { TopBar } from "@/components";
import { LogoutButton } from "../auth/LogoutButton";

export function MyListeningPage(): JSX.Element {
  return <TopBar title="My Listening" right={<LogoutButton />} />;
}
