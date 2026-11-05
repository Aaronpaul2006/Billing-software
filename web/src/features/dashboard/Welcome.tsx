import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle, FilePlus2, FileText, IndianRupee, UserPlus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { useMe } from "@/api/me";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Setup = components["schemas"]["SetupStatus"];
type Step = Exclude<keyof Setup, "complete">;

/** Quick actions, shown to the roles the API lets do them (docs/01-architecture.md §3). */
const ACTIONS: { to: string; label: string; icon: LucideIcon; roles: readonly string[] }[] = [
  {
    to: "/documents/new",
    label: "New bill",
    icon: FilePlus2,
    roles: ["OWNER", "ADMIN", "ACCOUNTANT", "SITE_ENGINEER"],
  },
  {
    to: "/documents/new?type=QUOTATION",
    label: "New quotation",
    icon: FileText,
    roles: ["OWNER", "ADMIN", "ACCOUNTANT", "SITE_ENGINEER"],
  },
  {
    to: "/payments/new",
    label: "Record a payment",
    icon: IndianRupee,
    roles: ["OWNER", "ADMIN", "ACCOUNTANT"],
  },
  {
    to: "/parties/new",
    label: "Add a client",
    icon: UserPlus,
    roles: ["OWNER", "ADMIN", "ACCOUNTANT"],
  },
];

const STEPS: { key: Step; label: string; to: string }[] = [
  {
    key: "gst_registration",
    label: "Add your GST registration",
    to: "/settings/gst-registrations",
  },
  { key: "number_series", label: "Set up your bill number series", to: "/settings/series" },
  { key: "client", label: "Add your first client", to: "/parties/new" },
  { key: "project", label: "Add a project", to: "/projects/new" },
  { key: "first_bill", label: "Issue your first bill", to: "/documents/new" },
  { key: "team", label: "Invite your team", to: "/settings/members" },
];

function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function SetupChecklist() {
  const setup = useQuery({
    queryKey: ["tenant", "setup"],
    queryFn: async () => unwrap(await api.GET("/api/v1/tenant/setup")),
  });
  if (!setup.data || setup.data.complete) return null; // errors: the dashboard says enough
  const data = setup.data;
  const done = STEPS.filter((s) => data[s.key]).length;
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Set up your business</h2>
        </CardTitle>
        <CardDescription>
          {done} of {STEPS.length} done. This list goes away once everything is set up.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="grid gap-2 sm:grid-cols-2" aria-label="Setup steps">
          {STEPS.map((step) => (
            <li key={step.key} className="flex items-center gap-2 text-sm">
              {data[step.key] ? (
                <>
                  <CheckCircle2 className="text-success size-4" aria-label="Done" />
                  <span className="text-muted-foreground line-through">{step.label}</span>
                </>
              ) : (
                <>
                  <Circle className="text-muted-foreground size-4" aria-label="To do" />
                  <Link to={step.to} className="underline">
                    {step.label}
                  </Link>
                </>
              )}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

/** The top of the first page after sign-in (H.2): greeting, quick actions, setup. */
export function Welcome({ now = new Date() }: { now?: Date }) {
  const { role } = useSession();
  const me = useMe();
  const first = me.data?.full_name.split(" ")[0];
  const actions = ACTIONS.filter((a) => a.roles.includes(role));
  return (
    <div className="mb-6 grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-lg font-medium">
          {greeting(now.getHours())}
          {first ? `, ${first}` : ""}
        </p>
        {actions.length > 0 && (
          <nav aria-label="Quick actions" className="flex flex-wrap gap-2">
            {actions.map(({ to, label, icon: Icon }) => (
              <Button key={to} variant="outline" size="sm" asChild>
                <Link to={to}>
                  <Icon aria-hidden /> {label}
                </Link>
              </Button>
            ))}
          </nav>
        )}
      </div>
      {(role === "OWNER" || role === "ADMIN") && <SetupChecklist />}
    </div>
  );
}
