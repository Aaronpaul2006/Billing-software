import { NavLink, Outlet } from "react-router";

import { useSession } from "@/auth/context";
import { SETTINGS_TABS } from "@/layout/nav";
import { can } from "@/lib/permissions";
import { cn } from "@/lib/utils";

/**
 * The settings screen (D.11): the business's settings as tabs on the left
 * (a row of tabs above the page on phones), each page beside them.
 */
export function SettingsLayout() {
  const { role } = useSession();
  const tabs = SETTINGS_TABS.filter((t) => !t.action || can(role, t.action));
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[12rem_minmax(0,1fr)]">
      <nav aria-label="Settings sections" className="lg:sticky lg:top-6 lg:self-start">
        <p className="text-muted-foreground mb-2 hidden px-2 text-xs font-medium lg:block">
          Business settings
        </p>
        <ul className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 lg:mx-0 lg:grid lg:overflow-visible lg:px-0">
          {tabs.map(({ to, label, icon: Icon }) => (
            <li key={to} className="shrink-0">
              <NavLink
                to={to}
                className={({ isActive }) =>
                  cn(
                    "hover:bg-accent flex min-h-9 items-center gap-2 rounded-md px-3 text-sm whitespace-nowrap",
                    isActive
                      ? "bg-accent text-accent-foreground font-medium"
                      : "text-muted-foreground",
                  )
                }
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
