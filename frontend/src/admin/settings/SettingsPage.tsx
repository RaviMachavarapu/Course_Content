import { useSearchParams } from "react-router-dom";
import { type TabItem, TabPanel, Tabs } from "@/components";
import { AudioTab } from "./AudioTab";
import { NotebookLmTab } from "./NotebookLmTab";
import { PromptsTab } from "./PromptsTab";
import { UsersTab } from "./UsersTab";

const TABS: TabItem[] = [
  { id: "prompts", label: "Generation Prompts", icon: "edit_note" },
  { id: "notebooklm", label: "NotebookLM", icon: "cloud" },
  { id: "audio", label: "Audio", icon: "graphic_eq" },
  { id: "users", label: "Users", icon: "group" },
];

export function SettingsPage(): JSX.Element {
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab") ?? "prompts";
  const active = TABS.some((t) => t.id === raw) ? raw : "prompts";

  return (
    <div className="flex flex-1 flex-col gap-6 p-4 md:p-margin-desktop">
      <h1 className="font-headline-lg text-headline-lg text-on-background">Settings</h1>

      <Tabs
        tabs={TABS}
        value={active}
        onChange={(id) => setParams((p) => {
          p.set("tab", id);
          return p;
        })}
      />

      <TabPanel id="prompts" active={active === "prompts"}>
        {active === "prompts" && <PromptsTab />}
      </TabPanel>
      <TabPanel id="notebooklm" active={active === "notebooklm"}>
        {active === "notebooklm" && <NotebookLmTab />}
      </TabPanel>
      <TabPanel id="audio" active={active === "audio"}>
        {active === "audio" && <AudioTab />}
      </TabPanel>
      <TabPanel id="users" active={active === "users"}>
        {active === "users" && <UsersTab />}
      </TabPanel>
    </div>
  );
}
