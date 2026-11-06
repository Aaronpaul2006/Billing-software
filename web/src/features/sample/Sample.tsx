import { useMutation, useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api, unwrap } from "@/api/client";
import { useMe } from "@/api/me";
import { useAuth, useSession } from "@/auth/context";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";

const wait = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

/**
 * "Explore with sample data" (Part B): a separate sample business, made in
 * the background in a few seconds, then opened. Nothing in it touches the
 * real business.
 */
export function ExploreSample({ pollMs = 1500, tries = 20 }: { pollMs?: number; tries?: number }) {
  const { switchTenant } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const tenant = useQuery({
    queryKey: ["tenant"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant")),
    staleTime: 60_000,
  });
  const open = useMutation({
    mutationFn: async () => {
      let state = unwrap(await api.POST("/api/v1/sample-business"));
      for (let i = 0; state.status !== "READY" && i < tries; i += 1) {
        await wait(pollMs);
        state = unwrap(await api.GET("/api/v1/sample-business"));
      }
      if (state.status !== "READY" || !state.tenant_id) {
        throw new Error("The sample business is still being made. Try again in a minute.");
      }
      await switchTenant(state.tenant_id);
    },
    onSuccess: () => {
      void navigate("/");
    },
    onError: (e) => {
      setError(e instanceof Error && !("problem" in e) ? e.message : errorMessage(e));
    },
  });
  if (tenant.data?.is_sample !== false) return null; // not inside the sample itself
  return (
    <div className="grid gap-1">
      <Button
        variant="outline"
        size="sm"
        className="justify-self-start"
        disabled={open.isPending}
        onClick={() => {
          setError(null);
          open.mutate();
        }}
      >
        <FlaskConical aria-hidden />
        {open.isPending ? "Making the sample business…" : "Explore with sample data"}
      </Button>
      <p className="text-help text-muted-foreground">
        A separate sample business with clients, bills and payments to try things on. Your own
        business stays as it is.
      </p>
      {error && <p className="text-destructive text-sm">{error}</p>}
    </div>
  );
}

/** At the top of every page in a sample business: back to the real one, or remove it. */
export function SampleBanner() {
  const session = useSession();
  const { switchTenant } = useAuth();
  const me = useMe();
  const tenant = useQuery({
    queryKey: ["tenant"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant")),
    staleTime: 60_000,
    enabled: session.role !== "CLIENT",
  });
  const real = me.data?.memberships.find((m) => m.tenant_id !== session.tenant_id);
  const remove = useMutation({
    mutationFn: async () => {
      unwrap(await api.POST("/api/v1/sample-business/remove"));
      if (real) await switchTenant(real.tenant_id);
    },
  });
  if (!tenant.data?.is_sample) return null;
  return (
    <div
      role="region"
      aria-label="Sample business"
      className="bg-warning-soft text-warning border-warning-border flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2 text-sm"
    >
      <span className="flex items-center gap-2 font-medium">
        <FlaskConical className="size-4" aria-hidden />A sample business: nothing here is real or
        reaches your own books.
      </span>
      <span className="ml-auto flex flex-wrap gap-2">
        {real && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              void switchTenant(real.tenant_id);
            }}
          >
            Back to {real.legal_name}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          disabled={remove.isPending}
          onClick={() => {
            remove.mutate();
          }}
        >
          Remove the sample
        </Button>
      </span>
    </div>
  );
}
