import {
  BarChart3,
  BookOpen,
  Building2,
  ChevronsUpDown,
  Download,
  FileText,
  FolderKanban,
  Hash,
  IndianRupee,
  Landmark,
  LayoutDashboard,
  LogOut,
  Package,
  Printer,
  Receipt,
  Settings,
  UserCog,
  UserRound,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router";

import { useMe } from "@/api/me";
import { useAuth, useSession } from "@/auth/context";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

import { InvitationsBanner } from "./InvitationsBanner";
import { VerifyEmailBanner } from "./VerifyEmailBanner";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/documents", label: "Invoices & quotes", icon: FileText },
  { to: "/payments", label: "Payments", icon: IndianRupee },
  { to: "/parties", label: "Parties", icon: Users },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/catalog", label: "Catalog", icon: Package },
  { to: "/expenses", label: "Expenses", icon: Receipt },
  { to: "/reports", label: "Reports", icon: BarChart3 },
  { to: "/exports", label: "Exports", icon: Download },
] as const;

/** Business settings: OWNER and ADMIN only (the API refuses the others anyway). */
const SETTINGS_NAV = [
  { to: "/settings/company", label: "Company", icon: Settings },
  { to: "/settings/members", label: "Members", icon: UserCog },
  { to: "/settings/gst-registrations", label: "GST registrations", icon: Landmark },
  { to: "/settings/series", label: "Number series", icon: Hash },
  { to: "/settings/print", label: "Bill printing", icon: Printer },
  { to: "/settings/tally", label: "Tally export", icon: BookOpen },
] as const;

function NavItem({
  to,
  label,
  icon: Icon,
  end,
}: {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "hover:bg-sidebar-accent flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
          isActive && "bg-sidebar-accent text-sidebar-accent-foreground font-medium",
        )
      }
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </NavLink>
  );
}

function TenantSwitcher() {
  const session = useSession();
  const { switchTenant } = useAuth();
  const me = useMe();
  const memberships = me.data?.memberships ?? [];
  const currentName = memberships.find((m) => m.tenant_id === session.tenant_id)?.legal_name ?? "…";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="w-full justify-between px-2" aria-label="Company">
          <span className="flex min-w-0 items-center gap-2">
            <Building2 aria-hidden />
            <span className="truncate font-semibold">{currentName}</span>
          </span>
          {memberships.length > 1 && <ChevronsUpDown className="opacity-50" aria-hidden />}
        </Button>
      </DropdownMenuTrigger>
      {memberships.length > 1 && (
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuLabel>Switch company</DropdownMenuLabel>
          {memberships.map((m) => (
            <DropdownMenuCheckItem
              key={m.tenant_id}
              checked={m.tenant_id === session.tenant_id}
              onSelect={() => {
                if (m.tenant_id !== session.tenant_id) void switchTenant(m.tenant_id);
              }}
            >
              <span className="truncate">{m.legal_name}</span>
              <span className="text-muted-foreground ml-auto text-xs">{m.role}</span>
            </DropdownMenuCheckItem>
          ))}
        </DropdownMenuContent>
      )}
    </DropdownMenu>
  );
}

function UserMenu() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const session = useSession();
  const me = useMe();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="w-full justify-start px-2">
          <span className="truncate text-sm">{me.data?.full_name ?? me.data?.email ?? "…"}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel className="grid">
          <span className="truncate">{me.data?.email}</span>
          <span className="text-muted-foreground text-xs font-normal">{session.role}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void navigate("/account")}>
          <UserRound aria-hidden /> Your account
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppShell() {
  const session = useSession();
  const manages = session.role === "OWNER" || session.role === "ADMIN";
  return (
    <div className="flex min-h-svh">
      <aside className="bg-sidebar text-sidebar-foreground border-sidebar-border hidden w-60 shrink-0 flex-col border-r p-3 md:flex">
        <TenantSwitcher />
        <nav className="mt-4 grid gap-1" aria-label="Main">
          {NAV.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>
        {manages && (
          <nav className="mt-6 grid gap-1" aria-label="Settings">
            <p className="text-muted-foreground px-2 text-xs font-medium">Settings</p>
            {SETTINGS_NAV.map((item) => (
              <NavItem key={item.to} {...item} />
            ))}
          </nav>
        )}
        <div className="mt-auto">
          <UserMenu />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b p-2 md:hidden">
          <TenantSwitcher />
        </header>
        <VerifyEmailBanner />
        <InvitationsBanner />
        <main className="flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
