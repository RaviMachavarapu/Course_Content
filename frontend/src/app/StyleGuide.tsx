import { useState } from "react";
import {
  Button,
  type ButtonVariant,
  Card,
  CardBody,
  CardHeader,
  Chip,
  type ChipStatus,
  EmptyState,
  ErrorState,
  Input,
  Modal,
  ProgressBar,
  Select,
  SidebarNav,
  Skeleton,
  TabPanel,
  Tabs,
  TopBar,
} from "@/components";
import { useToast } from "@/lib/store";

function Section({ title, children }: { title: string; children: React.ReactNode }): JSX.Element {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-headline-md text-headline-md text-on-surface">{title}</h2>
      <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-5">
        {children}
      </div>
    </section>
  );
}

const BUTTON_VARIANTS: ButtonVariant[] = ["primary", "secondary", "student", "ghost", "danger"];
const CHIP_STATUSES: ChipStatus[] = ["processing", "ready", "error", "published", "pending"];

export function StyleGuide(): JSX.Element {
  const [modalOpen, setModalOpen] = useState(false);
  const [tab, setTab] = useState("overview");
  const { toast } = useToast();

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-10 p-6 md:p-10">
      <header className="flex flex-col gap-1">
        <p className="font-label-sm text-label-sm uppercase tracking-wide text-primary">
          Academic Modernist
        </p>
        <h1 className="font-display-lg text-display-lg">UI Kit / Style Guide</h1>
        <p className="text-body-md text-on-surface-variant">
          Every component in every state. Route: <code>/styleguide</code>.
        </p>
      </header>

      <Section title="Typography">
        <div className="flex flex-col gap-2">
          <p className="font-display-lg text-display-lg">Display · Public Sans</p>
          <p className="font-headline-lg text-headline-lg">Headline large</p>
          <p className="font-headline-md text-headline-md">Headline medium</p>
          <p className="font-body-lg text-body-lg">Body large · Inter — long-form reading.</p>
          <p className="font-body-md text-body-md">Body medium · Inter — default copy.</p>
          <p className="font-label-md text-label-md">Label medium (500)</p>
          <p className="font-label-sm text-label-sm uppercase tracking-wide">Label small (600)</p>
        </div>
      </Section>

      <Section title="Colour roles">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { name: "primary", cls: "bg-primary text-on-primary" },
            { name: "secondary", cls: "bg-secondary text-on-secondary" },
            { name: "tertiary", cls: "bg-tertiary text-on-tertiary" },
            { name: "error", cls: "bg-error text-on-error" },
            { name: "primary-container", cls: "bg-primary-container text-on-primary-container" },
            {
              name: "secondary-container",
              cls: "bg-secondary-container text-on-secondary-container",
            },
            { name: "tertiary-container", cls: "bg-tertiary-container text-on-tertiary-container" },
            { name: "surface-container-high", cls: "bg-surface-container-high text-on-surface" },
          ].map(({ name, cls }) => (
            <div
              key={name}
              className={`rounded-lg border border-outline-variant p-3 font-label-sm text-label-sm ${cls}`}
            >
              {name}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Button">
        <div className="flex flex-col gap-4">
          {BUTTON_VARIANTS.map((v) => (
            <div key={v} className="flex flex-wrap items-center gap-3">
              <span className="w-20 font-label-sm text-label-sm text-on-surface-variant">{v}</span>
              <Button variant={v}>Default</Button>
              <Button variant={v} iconLeft="add">
                With icon
              </Button>
              <Button variant={v} size="sm">
                Small
              </Button>
              <Button variant={v} loading>
                Loading
              </Button>
              <Button variant={v} disabled>
                Disabled
              </Button>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Card">
        <div className="grid gap-4 sm:grid-cols-2">
          <Card variant="admin">
            <CardHeader>Admin card (flat, bordered)</CardHeader>
            <CardBody className="text-body-md text-on-surface-variant">
              High-density surface for dashboards and tables.
            </CardBody>
          </Card>
          <Card variant="elevated">
            <CardBody>
              <p className="font-label-md text-label-md font-semibold">Elevated card</p>
              <p className="text-body-md text-on-surface-variant">
                Level 2 shadow, lifts on hover.
              </p>
            </CardBody>
          </Card>
        </div>
      </Section>

      <Section title="Chip — status">
        <div className="flex flex-wrap gap-3">
          {CHIP_STATUSES.map((s) => (
            <Chip key={s} status={s} />
          ))}
        </div>
      </Section>

      <Section title="Input & Select">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Default" placeholder="Type here" />
          <Input label="With hint" hint="We never share this." placeholder="you@example.com" />
          <Input label="With error" error="Required field" defaultValue="bad" />
          <Input label="Disabled" placeholder="Unavailable" disabled />
          <Select
            label="Select"
            placeholder="Choose one"
            options={[
              { value: "a", label: "Option A" },
              { value: "b", label: "Option B" },
            ]}
          />
          <Select
            label="Select with error"
            error="Pick a value"
            options={[{ value: "a", label: "Option A" }]}
          />
        </div>
      </Section>

      <Section title="Tabs">
        <Tabs
          tabs={[
            { id: "overview", label: "Overview", icon: "dashboard" },
            { id: "activity", label: "Activity", icon: "history" },
            { id: "settings", label: "Settings", icon: "tune" },
          ]}
          value={tab}
          onChange={setTab}
        />
        <TabPanel id="overview" active={tab === "overview"}>
          <p className="pt-3 text-body-md text-on-surface-variant">Overview panel content.</p>
        </TabPanel>
        <TabPanel id="activity" active={tab === "activity"}>
          <p className="pt-3 text-body-md text-on-surface-variant">Activity panel content.</p>
        </TabPanel>
        <TabPanel id="settings" active={tab === "settings"}>
          <p className="pt-3 text-body-md text-on-surface-variant">Settings panel content.</p>
        </TabPanel>
      </Section>

      <Section title="Progress">
        <div className="flex flex-col gap-3">
          <ProgressBar value={35} tone="active" showLabel />
          <ProgressBar value={100} tone="complete" showLabel />
        </div>
      </Section>

      <Section title="Skeleton">
        <div className="grid gap-4 sm:grid-cols-2">
          <Skeleton className="h-24" />
          <Skeleton lines={4} />
        </div>
      </Section>

      <Section title="Modal & Toast">
        <div className="flex flex-wrap gap-3">
          <Button onClick={() => setModalOpen(true)}>Open modal</Button>
          <Button variant="secondary" onClick={() => toast({ title: "Saved", tone: "success" })}>
            Success toast
          </Button>
          <Button
            variant="secondary"
            onClick={() => toast({ title: "Heads up", description: "Something to note." })}
          >
            Info toast
          </Button>
          <Button
            variant="danger"
            onClick={() => toast({ title: "Failed", description: "Try again.", tone: "error" })}
          >
            Error toast
          </Button>
        </div>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="Confirm action"
          footer={
            <>
              <Button variant="secondary" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button onClick={() => setModalOpen(false)}>Confirm</Button>
            </>
          }
        >
          <p className="text-body-md text-on-surface-variant">
            Modal body — Escape, backdrop click, or the buttons close it.
          </p>
        </Modal>
      </Section>

      <Section title="Empty & Error states">
        <div className="grid gap-4 sm:grid-cols-2">
          <EmptyState
            title="No courses yet"
            description="Published courses will appear here."
            action={<Button size="sm">Browse catalog</Button>}
          />
          <ErrorState onRetry={() => toast({ title: "Retrying…" })} />
        </div>
      </Section>

      <Section title="TopBar">
        <div className="overflow-hidden rounded-lg border border-outline-variant">
          <TopBar
            title="Neural Networks 101"
            backTo="#"
            backLabel="Back to Ingestion"
            right={<Chip status="pending" />}
          />
          <div className="bg-background p-4 text-body-md text-on-surface-variant">Page body…</div>
        </div>
        <div className="mt-4 overflow-hidden rounded-lg border border-outline-variant">
          <TopBar
            title="Focus mode"
            focus
            right={<span className="font-label-sm text-label-sm">62%</span>}
          />
        </div>
      </Section>

      <Section title="SidebarNav">
        {/* transform on the wrapper makes the nav's position:fixed resolve to this box */}
        <p className="mb-2 font-label-sm text-label-sm text-on-surface-variant">
          Active state tracks the current route; here “Style guide” is active.
        </p>
        {/* transform on the wrapper makes the nav's position:fixed resolve to this box */}
        <div
          className="relative h-[420px] overflow-hidden rounded-lg border border-outline-variant"
          style={{ transform: "translateZ(0)" }}
        >
          <SidebarNav
            items={[
              { to: "/admin", label: "Ingestion", icon: "upload_file", end: true },
              { to: "/admin/review", label: "Review", icon: "fact_check" },
              { to: "/styleguide", label: "Style guide", icon: "palette" },
              { to: "/admin/settings", label: "Settings", icon: "settings", footer: true },
            ]}
            title="Shikshak Dp"
            subtitle="AI Engine"
          />
        </div>
      </Section>
    </div>
  );
}
