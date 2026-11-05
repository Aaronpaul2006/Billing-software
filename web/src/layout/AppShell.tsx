import { Building2, ChevronsUpDown, Keyboard, LogOut, Menu, Search, UserRound } from "lucide-react";
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
import { cn } from "@/lib/utils";

import { CommandPalette } from "./CommandPalette";
import { InvitationsBanner } from "./InvitationsBanner";
import { MOD_KEY } from "./keys";
import { GROUPS } from "./nav";
import type { NavEntry } from "./nav";
import { ShortcutsHelp } from "./ShortcutsHelp";
import { VerifyEmailBanner } from "./VerifyEmailBanner";

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
function SidebarBody({
  onNavigate,
  onHelp,
  onSearch,
}: {
  onNavigate?: () => void;
  onHelp: () => void;
  onSearch: () => void;
}) {
  const session = useSession();
  return (
    <>
      <TenantSwitcher />
      <Button
        variant="outline"
        className="text-muted-foreground mt-3 w-full justify-start px-2 font-normal"
        aria-keyshortcuts={MOD_KEY === "⌘" ? "Meta+K" : "Control+K"}
        onClick={onSearch}
      >
        <Search aria-hidden /> Search
        <kbd className="ml-auto font-sans text-xs" aria-hidden>
          {MOD_KEY} K
        </kbd>
      </Button>
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
function MobileMenu({ onHelp, onSearch }: { onHelp: () => void; onSearch: () => void }) {
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
            onSearch={() => {
              setOpen(false);
              onSearch();
            }}
          />
        </SheetContent>
      </Sheet>
      <span className="truncate text-sm font-semibold">{company}</span>
      <Button
        variant="ghost"
        size="icon"
        className="ml-auto size-11"
        aria-label="Search"
        onClick={onSearch}
      >
        <Search className="size-5" aria-hidden />
      </Button>
    </header>
  );
}

export function AppShell() {
  const [help, setHelp] = useState(false);
  const [search, setSearch] = useState(false);
  const showHelp = () => {
    setHelp(true);
  };
  const showSearch = () => {
    setSearch(true);
  };
  return (
    <div className="flex min-h-svh">
      <aside className="bg-sidebar text-sidebar-foreground border-sidebar-border hidden w-60 shrink-0 flex-col border-r p-3 md:flex">
        <SidebarBody onHelp={showHelp} onSearch={showSearch} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileMenu onHelp={showHelp} onSearch={showSearch} />
        <VerifyEmailBanner />
        <InvitationsBanner />
        <main className="flex-1 p-4 md:p-6">
          <Outlet />
        </main>
        <ShortcutsHelp open={help} onOpenChange={setHelp} />
        <CommandPalette open={search} onOpenChange={setSearch} onHelp={showHelp} />
      </div>
    </div>
  );
}
