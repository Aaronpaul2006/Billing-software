import {
  BadgePercent,
  BarChart3,
  BookOpen,
  Building2,
  ChevronsUpDown,
  ClipboardList,
  Download,
  FileText,
  FolderKanban,
  Hash,
  IndianRupee,
  Keyboard,
  Landmark,
  LayoutDashboard,
  LayoutTemplate,
  LogOut,
  Menu,
  Package,
  Printer,
  Receipt,
  Settings,
  UserCog,
  UserRound,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router";

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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { setTextSize, setThemeChoice, textSize, themeChoice } from "@/lib/appearance";
import type { TextSize, ThemeChoice } from "@/lib/appearance";
import { can } from "@/lib/permissions";
import type { Action } from "@/lib/permissions";
import { cn } from "@/lib/utils";

import { InvitationsBanner } from "./InvitationsBanner";
import { ShortcutsHelp } from "./ShortcutsHelp";
import { VerifyEmailBanner } from "./VerifyEmailBanner";

interface NavEntry {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /** Shown only to roles that may do this (the server checks too). */
  action?: Action;
  /** For links that share a page (Bills and Quotations are both /documents). */
  match?: (path: string, query: URLSearchParams) => boolean;
}

/** The sidebar, grouped by job (D.5). */
const GROUPS: { title: string; items: NavEntry[] }[] = [
  {
    title: "Sell",
    items: [
      {
        to: "/documents?type=quotations",
        label: "Quotations",
        icon: ClipboardList,
        match: (path, q) => path === "/documents" && q.get("type") === "quotations",
      },
      {
        to: "/documents?type=bills",
        label: "Bills",
        icon: FileText,
        match: (path, q) => path.startsWith("/documents") && q.get("type") !== "quotations",
      },
      { to: "/templates", label: "Templates", icon: LayoutTemplate },
    ],
  },
  {
    title: "Money",
    items: [
      { to: "/payments", label: "Payments", icon: IndianRupee },
      { to: "/expenses", label: "Expenses", icon: Receipt },
      { to: "/tds-certificates", label: "TDS certificates", icon: BadgePercent },
    ],
  },
  {
    title: "Work",
    items: [
      { to: "/projects", label: "Projects", icon: FolderKanban },
      { to: "/parties", label: "Clients & vendors", icon: Users },
      { to: "/catalog", label: "Catalog", icon: Package },
    ],
  },
  {
    title: "Insight",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/reports", label: "Reports", icon: BarChart3, action: "reports.view" },
      { to: "/exports", label: "Exports", icon: Download, action: "reports.view" },
    ],
  },
  {
    title: "Settings",
    items: [
      { to: "/settings/company", label: "Company", icon: Settings, action: "tenant.settings" },
      { to: "/settings/members", label: "Members", icon: UserCog, action: "members.manage" },
      {
        to: "/settings/gst-registrations",
        label: "GST registrations",
        icon: Landmark,
        action: "tenant.settings",
      },
      { to: "/settings/series", label: "Number series", icon: Hash, action: "tenant.settings" },
      { to: "/settings/print", label: "Bill printing", icon: Printer, action: "tenant.settings" },
      { to: "/settings/tally", label: "Tally export", icon: BookOpen, action: "tenant.settings" },
    ],
  },
];

const itemClass = (active: boolean) =>
  cn(
    "hover:bg-sidebar-accent flex items-center gap-2 rounded-md px-2 py-1.5 text-sm",
    active && "bg-sidebar-accent text-sidebar-accent-foreground font-medium",
  );

function NavItem({ entry, onNavigate }: { entry: NavEntry; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const [query] = useSearchParams();
  const { to, label, icon: Icon, end, match } = entry;
  const body = (
    <>
      <Icon className="size-4" aria-hidden />
      {label}
    </>
  );
  if (match) {
    const active = match(pathname, query);
    return (
      <Link
        to={to}
        onClick={onNavigate}
        aria-current={active ? "page" : undefined}
        className={itemClass(active)}
      >
        {body}
      </Link>
    );
  }
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) => itemClass(isActive)}
    >
      {body}
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
        <Button variant="ghost" className="w-full justify-between px-2">
          <span className="flex min-w-0 items-center gap-2">
            <Building2 aria-hidden />
            <span className="truncate font-semibold">{currentName}</span>
            {/* the spoken name starts with what is shown (WCAG 2.5.3) */}
            <span className="sr-only">, company</span>
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

const THEMES: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "Same as this device" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];
const SIZES: { value: TextSize; label: string }[] = [
  { value: "normal", label: "Normal text" },
  { value: "large", label: "Large text" },
];

function UserMenu({ onHelp }: { onHelp: () => void }) {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const session = useSession();
  const me = useMe();
  const [theme, setTheme] = useState(themeChoice);
  const [size, setSize] = useState(textSize);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" className="w-full justify-between px-2">
          <span className="flex min-w-0 items-center gap-2">
            <UserRound aria-hidden />
            <span className="truncate text-sm">{me.data?.full_name ?? me.data?.email ?? "…"}</span>
            <span className="sr-only">, your account and sign out</span>
          </span>
          <ChevronsUpDown className="opacity-50" aria-hidden />
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
        <DropdownMenuItem onSelect={onHelp}>
          <Keyboard aria-hidden /> Keyboard shortcuts
          <kbd className="text-muted-foreground ml-auto text-xs">?</kbd>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
          Theme
        </DropdownMenuLabel>
        {THEMES.map((t) => (
          <DropdownMenuCheckItem
            key={t.value}
            checked={theme === t.value}
            onSelect={(e) => {
              e.preventDefault(); // keep the menu open to see the change
              setThemeChoice(t.value);
              setTheme(t.value);
            }}
          >
            {t.label}
          </DropdownMenuCheckItem>
        ))}
        <DropdownMenuLabel className="text-muted-foreground text-xs font-normal">
          Text size
        </DropdownMenuLabel>
        {SIZES.map((t) => (
          <DropdownMenuCheckItem
            key={t.value}
            checked={size === t.value}
            onSelect={(e) => {
              e.preventDefault();
              setTextSize(t.value);
              setSize(t.value);
            }}
          >
            {t.label}
          </DropdownMenuCheckItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => void logout()}>
          <LogOut aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The sidebar's contents: on wide screens beside the page, on phones in the menu panel. */
function SidebarBody({ onNavigate, onHelp }: { onNavigate?: () => void; onHelp: () => void }) {
  const session = useSession();
  return (
    <>
      <TenantSwitcher />
      <div className="mt-4 grid gap-5">
        {GROUPS.map((group) => {
          const items = group.items.filter((i) => !i.action || can(session.role, i.action));
          if (items.length === 0) return null;
          return (
            <nav key={group.title} className="grid gap-1" aria-label={group.title}>
              <p className="text-muted-foreground px-2 text-xs font-medium">{group.title}</p>
              {items.map((item) => (
                <NavItem key={item.label} entry={item} onNavigate={onNavigate} />
              ))}
            </nav>
          );
        })}
      </div>
      <div className="mt-auto pt-6">
        <UserMenu onHelp={onHelp} />
      </div>
    </>
  );
}

/** Phones and small tablets: a menu button opening the sidebar as a panel (D.1). */
function MobileMenu({ onHelp }: { onHelp: () => void }) {
  const [open, setOpen] = useState(false);
  const me = useMe();
  const session = useSession();
  const company =
    me.data?.memberships.find((m) => m.tenant_id === session.tenant_id)?.legal_name ?? "";
  return (
    <header className="bg-background sticky top-0 z-40 flex items-center gap-2 border-b px-2 py-1.5 md:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="size-11" aria-label="Open the menu">
            <Menu className="size-5" aria-hidden />
          </Button>
        </SheetTrigger>
        <SheetContent className="bg-sidebar text-sidebar-foreground overflow-y-auto p-3 pt-12">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          <SheetDescription className="sr-only">
            Sections, your account and sign out
          </SheetDescription>
          <SidebarBody
            onNavigate={() => {
              setOpen(false);
            }}
            onHelp={() => {
              setOpen(false);
              onHelp();
            }}
          />
        </SheetContent>
      </Sheet>
      <span className="truncate text-sm font-semibold">{company}</span>
    </header>
  );
}

export function AppShell() {
  const [help, setHelp] = useState(false);
  return (
    <div className="flex min-h-svh">
      <aside className="bg-sidebar text-sidebar-foreground border-sidebar-border hidden w-60 shrink-0 flex-col border-r p-3 md:flex">
        <SidebarBody
          onHelp={() => {
            setHelp(true);
          }}
        />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileMenu
          onHelp={() => {
            setHelp(true);
          }}
        />
        <VerifyEmailBanner />
        <InvitationsBanner />
        <main className="flex-1 p-4 md:p-6">
          <Outlet />
        </main>
        <ShortcutsHelp open={help} onOpenChange={setHelp} />
      </div>
    </div>
  );
}
