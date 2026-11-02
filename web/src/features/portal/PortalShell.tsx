import { useQuery } from "@tanstack/react-query";
import { FileText, FolderKanban, Home, IndianRupee, LogOut, ScrollText } from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { useMe } from "@/api/me";
import { useAuth, useSession } from "@/auth/context";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { portalMeQuery } from "./api";

const NAV = [
  { to: "/portal", label: "Overview", icon: Home },
  { to: "/portal/bills", label: "Bills & quotes", icon: FileText },
  { to: "/portal/payments", label: "Payments", icon: IndianRupee },
  { to: "/portal/statement", label: "Statement", icon: ScrollText },
  { to: "/portal/projects", label: "Projects", icon: FolderKanban },
] as const;

/** The client portal: a client's own bills, payments and projects with one business. */
export function PortalShell() {
  const { logout, switchTenant } = useAuth();
  const session = useSession();
  const me = useQuery(portalMeQuery);
  const business = me.data?.business;
  // Someone who also works in a business of their own (or is a client of
  // several) switches here, like the company switcher in the main app.
  const others = (useMe().data?.memberships ?? []).filter((m) => m.tenant_id !== session.tenant_id);
  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2 p-3">
          <div className="grid">
            <span className="font-semibold">
              {business?.trade_name ?? business?.legal_name ?? "…"}
            </span>
            <span className="text-muted-foreground text-xs">
              Client portal{me.data ? ` · ${me.data.client.display_name}` : ""}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {others.map((m) => (
              <Button
                key={m.tenant_id}
                variant="outline"
                size="sm"
                onClick={() => void switchTenant(m.tenant_id)}
              >
                Switch to {m.legal_name}
              </Button>
            ))}
            <Button variant="ghost" size="sm" onClick={() => void logout()}>
              <LogOut aria-hidden /> Sign out
            </Button>
          </div>
        </div>
        <nav aria-label="Portal" className="mx-auto flex max-w-5xl gap-1 overflow-x-auto px-3 pb-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/portal"}
              className={({ isActive }) =>
                cn(
                  "hover:bg-accent flex shrink-0 items-center gap-2 rounded-md px-3 py-1.5 text-sm",
                  isActive && "bg-accent font-medium",
                )
              }
            >
              <Icon className="size-4" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}
