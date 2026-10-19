import { useCallback, useState } from "react";
import { Button, Card, ErrorState, Input, Modal, Skeleton } from "@/components";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/store";
import { useAdminSession } from "../auth/useAdminAuth";
import { useAdminUsers, useUserMutations } from "./useSettings";

export function UsersTab(): JSX.Element {
  const { user: me } = useAdminSession();
  const { data, isPending, isError, refetch } = useAdminUsers();
  const { create, setActive } = useUserMutations();
  const { toast } = useToast();

  const [adding, setAdding] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const resetForm = useCallback(() => {
    setEmail("");
    setName("");
    setPassword("");
    setFormError(null);
  }, []);

  const closeAdd = useCallback(() => {
    setAdding(false);
    resetForm();
  }, [resetForm]);

  if (isError) return <ErrorState title="Could not load admins" onRetry={() => void refetch()} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="font-headline-md text-headline-md">Admin accounts</h3>
        <Button data-testid="btn-st5" iconLeft="person_add" onClick={() => setAdding(true)}>
          Add admin
        </Button>
      </div>

      {isPending ? (
        <Skeleton className="h-40" />
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-body-md">
              <thead className="border-b border-outline-variant font-label-sm text-label-sm text-on-surface-variant">
                <tr>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-4 py-2">Email</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2">Last login</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {(data ?? []).map((u) => {
                  const isSelf = u.id === me?.id;
                  return (
                    <tr key={u.id} className="border-b border-outline-variant/60">
                      <td className="px-4 py-3">
                        {u.display_name}
                        {isSelf && (
                          <span className="ml-2 font-label-sm text-label-sm text-on-surface-variant">
                            (you)
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-on-surface-variant">{u.email}</td>
                      <td className="px-4 py-3">
                        <span className={u.is_active ? "text-secondary" : "text-error"}>
                          {u.is_active ? "Active" : "Deactivated"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-label-sm text-on-surface-variant">
                        {u.last_login_at ? new Date(u.last_login_at).toLocaleDateString() : "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button
                          variant={u.is_active ? "ghost" : "secondary"}
                          size="sm"
                          data-testid={`btn-st6-${u.id}`}
                          disabled={isSelf || setActive.isPending}
                          title={isSelf ? "You cannot deactivate your own account" : undefined}
                          onClick={() =>
                            setActive.mutate(
                              { id: u.id, is_active: !u.is_active },
                              {
                                onError: (err) =>
                                  toast({
                                    title: "Update failed",
                                    description:
                                      err instanceof ApiError ? err.message : undefined,
                                    tone: "error",
                                  }),
                              },
                            )
                          }
                        >
                          {u.is_active ? "Deactivate" : "Reactivate"}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Modal
        open={adding}
        onClose={closeAdd}
        title="Add admin"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setAdding(false);
                resetForm();
              }}
            >
              Cancel
            </Button>
            <Button
              data-testid="btn-st5-confirm"
              loading={create.isPending}
              disabled={!email.trim() || !name.trim() || !password}
              onClick={() => {
                setFormError(null);
                create.mutate(
                  { email: email.trim(), display_name: name.trim(), password },
                  {
                    onSuccess: () => {
                      setAdding(false);
                      resetForm();
                      toast({ title: "Admin added", tone: "success" });
                    },
                    onError: (err) =>
                      setFormError(
                        err instanceof ApiError ? err.message : "Could not create the admin.",
                      ),
                  },
                );
              }}
            >
              Create
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input label="Display name" value={name} onChange={(e) => setName(e.target.value)} />
          <Input
            label="Temporary password"
            type="password"
            hint="At least 10 characters, with a letter and a number or symbol"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {formError && (
            <p role="alert" className="font-label-sm text-label-sm text-error">
              {formError}
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}
