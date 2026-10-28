import { Button, Card, CardBody } from "@/components";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/store";
import { McpBadge, WorkerBadge } from "../AdminStatus";
import { useMcpStatus } from "../useAdminApi";
import { useRefreshMcpAuth } from "./useSettings";

const REAUTH_CMD =
  "docker compose --profile mcp run --rm --service-ports mcp npx -y notebooklm-mcp-server@4.0.2 auth";
/** noVNC for the mcp auth browser: `VITE_VNC_URL` when the build sets it,
 * else port 6080 on the host this app is served from (compose publishes it
 * there; it was hardcoded to localhost, which only worked on the dev host). */
export function vncUrl(
  configured: string | undefined,
  loc: { protocol: string; hostname: string },
): string {
  return configured || `${loc.protocol}//${loc.hostname}:6080/vnc.html`;
}
const VNC_URL = vncUrl(import.meta.env.VITE_VNC_URL as string | undefined, window.location);

export function NotebookLmTab(): JSX.Element {
  const mcp = useMcpStatus();
  const refresh = useRefreshMcpAuth();
  const { toast } = useToast();
  const isFixture = mcp.data?.account_email === "fixture@localhost";

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardBody className="flex flex-col gap-4 p-5">
          <div className="flex items-center justify-between">
            <h3 className="font-headline-md text-headline-md">Connection</h3>
            <McpBadge healthy={mcp.data?.healthy} isFixture={isFixture} />
          </div>
          {isFixture && (
            <p
              role="status"
              className="rounded-lg bg-tertiary-container/30 px-3 py-2 text-body-md text-on-surface"
            >
              No Google account is linked yet — content is generated from built-in sample data (
              <code>FixtureProvider</code>). Link your account below to generate from your own
              sources.
            </p>
          )}
          <dl className="grid gap-2 text-body-md sm:grid-cols-[max-content_1fr] sm:gap-x-6">
            <dt className="text-on-surface-variant">Account email</dt>
            <dd data-testid="mcp-email">{mcp.data?.account_email ?? "—"}</dd>
            <dt className="text-on-surface-variant">Last successful call</dt>
            <dd>
              {mcp.data?.last_ok_at ? new Date(mcp.data.last_ok_at).toLocaleString() : "never"}
            </dd>
            <dt className="text-on-surface-variant">Detail</dt>
            <dd>{mcp.data?.detail ?? "—"}</dd>
          </dl>
          <div>
            <Button
              data-testid="btn-st3"
              iconLeft="refresh"
              loading={refresh.isPending}
              onClick={() =>
                refresh.mutate(undefined, {
                  onSuccess: () => toast({ title: "Auth reload requested", tone: "success" }),
                  onError: (err) =>
                    toast({
                      title: "Reload failed",
                      description: err instanceof ApiError ? err.message : undefined,
                      tone: "error",
                    }),
                })
              }
            >
              Reload auth
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="flex flex-col gap-4 p-5" data-testid="system-health-strip">
          <div className="flex items-center justify-between">
            <h3 className="font-headline-md text-headline-md">System health</h3>
            <WorkerBadge stale={mcp.data?.worker_heartbeat_stale} />
          </div>
          <dl className="grid gap-2 text-body-md sm:grid-cols-[max-content_1fr] sm:gap-x-6">
            <dt className="text-on-surface-variant">Worker last heartbeat</dt>
            <dd>
              {mcp.data?.worker_last_heartbeat_at
                ? new Date(mcp.data.worker_last_heartbeat_at).toLocaleString()
                : "never"}
            </dd>
            <dt className="text-on-surface-variant">Generation jobs</dt>
            <dd data-testid="job-counters">
              {mcp.data?.jobs_succeeded ?? 0} succeeded · {mcp.data?.jobs_failed ?? 0} failed
            </dd>
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardBody className="flex flex-col gap-3 p-5">
          <h3 className="font-headline-md text-headline-md">
            {isFixture ? "Link your Google account" : "Re-authenticate"}
          </h3>
          <p className="text-body-md text-on-surface-variant">
            This opens a real Google sign-in page inside a virtual browser — this app never asks for
            your Google password directly. Run this in a terminal on the machine hosting Docker:
          </p>
          <code className="select-all rounded-lg bg-surface-container-high px-3 py-2 font-mono text-body-sm">
            {REAUTH_CMD}
          </code>
          <p className="text-body-md text-on-surface-variant">
            Then open the link below, click <strong>Connect</strong>, and sign in with the Google
            account you want to use — exactly as you would on google.com. When you're done, come
            back and click <strong>Reload auth</strong> above.
          </p>
          <a
            href={VNC_URL}
            target="_blank"
            rel="noreferrer"
            data-testid="btn-mcp-vnc"
            className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-primary px-3 py-1.5 font-label-md text-label-md text-primary hover:bg-primary/5"
          >
            Open Google sign-in
          </a>
        </CardBody>
      </Card>
    </div>
  );
}
