import { useQuery } from "@tanstack/react-query";
import { FileText, FolderKanban, Home, IndianRupee, LogOut, ScrollText } from "lucide-react";
import { NavLink, Outlet } from "react-router";

import { useMe } from "@/api/me";
import { useAuth, useSession } from "@/auth/context";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { portalMeQuery } from "./api";

const NAV = [
  { to: "/portal", label: "Overview", short: "Home", icon: Home },
  { to: "/portal/bills", label: "Bills & quotes", short: "Bills", icon: FileText },
  { to: "/portal/payments", label: "Payments", short: "Payments", icon: IndianRupee },
  { to: "/portal/statement", label: "Statement", short: "Statement", icon: ScrollText },
  { to: "/portal/projects", label: "Projects", short: "Projects", icon: FolderKanban },
] as const;

/**
 * The portal's sections (D.12): a row under the header on wider screens, a
 * bar along the bottom on phones, where every section stays in reach of a
 * thumb (no hidden items to scroll to).
 */
function PortalNav() {
  return (
    <nav
      aria-label="Portal"
      className="bg-background fixed inset-x-0 bottom-0 z-40 border-t pb-[env(safe-area-inset-bottom)] md:static md:z-auto md:border-t-0 md:pb-0"
    >
      <ul className="mx-auto grid max-w-5xl grid-cols-5 md:flex md:gap-1 md:px-3 md:pb-2">
        {NAV.map(({ to, label, short, icon: Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={to === "/portal"}
              className={({ isActive }) =>
                cn(
                  "flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs md:min-h-9 md:flex-row md:gap-2 md:rounded-md md:px-3 md:text-sm",
                  "hover:bg-accent",
                  isActive
                    ? "text-primary md:bg-accent md:text-foreground font-medium"
                    : "text-muted-foreground md:text-foreground",
                )
              }
            >
              <Icon className="size-5 md:size-4" aria-hidden />
              <span className="md:hidden">{short}</span>
              <span className="hidden md:inline">{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

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
        <PortalNav />
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 p-4 pb-24 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}
