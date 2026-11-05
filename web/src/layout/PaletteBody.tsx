import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FileText, FolderKanban, Keyboard, Package, Search, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useNavigate } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { DOC_TYPE_LABELS, STATUS_LABELS } from "@/features/documents/api";
import { formatDate } from "@/lib/dates";
import { formatInr } from "@/lib/money";
import { can } from "@/lib/permissions";
import { useDebounced } from "@/lib/useDebounced";
import { cn } from "@/lib/utils";

import { CREATE, GROUPS } from "./nav";
import type { NavEntry } from "./nav";

type Results = components["schemas"]["SearchResult"];

interface Item {
  key: string;
  group: string;
  label: string;
  detail?: string;
  icon: LucideIcon;
  run: () => void;
  /** Other words it is found by. */
  words?: string;
}

/** Every word typed appears somewhere in the text (any order, any case). */
function matches(text: string, typed: string): boolean {
  const hay = text.toLowerCase();
  return typed
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => hay.includes(w));
}

const joined = (...parts: (string | null | undefined | false)[]) =>
  parts.filter(Boolean).join(" · ");

function partyKind(p: Results["parties"][number]): string {
  if (p.is_customer && p.is_vendor) return "Client and vendor";
  return p.is_vendor ? "Vendor" : "Client";
}

/** What the server found, as palette rows. */
function recordItems(r: Results, go: (to: string) => void): Item[] {
  return [
    ...r.documents.map((d) => ({
      key: `d:${d.id}`,
      group: "Bills & quotations",
      label: `${DOC_TYPE_LABELS[d.doc_type]} ${d.doc_number ?? "(draft)"}`,
      detail: joined(
        d.party_name,
        formatDate(d.doc_date),
        formatInr(d.grand_total),
        STATUS_LABELS[d.status],
      ),
      icon: FileText,
      run: () => {
        go(`/documents/${d.id}`);
      },
    })),
    ...r.parties.map((p) => ({
      key: `p:${p.id}`,
      group: "Clients & vendors",
      label: p.display_name,
      detail: joined(partyKind(p), p.gstin && `GSTIN ${p.gstin}`, !p.is_active && "Archived"),
      icon: Users,
      run: () => {
        go(`/parties/${p.id}`);
      },
    })),
    ...r.projects.map((p) => ({
      key: `j:${p.id}`,
      group: "Projects",
      label: p.name,
      detail: joined(p.code !== p.name && p.code, p.client_name),
      icon: FolderKanban,
      run: () => {
        go(`/projects/${p.id}`);
      },
    })),
    ...r.catalog_items.map((c) => ({
      key: `c:${c.id}`,
      group: "Catalog",
      label: c.name,
      detail: joined(c.unit, c.sac_hsn && `HSN/SAC ${c.sac_hsn}`, formatInr(c.default_rate)),
      icon: Package,
      run: () => {
        go(`/catalog?q=${encodeURIComponent(c.name)}`);
      },
    })),
  ];
}

/** The palette's contents, loaded the first time it opens (D.6). */
export function PaletteBody({ onDone, onHelp }: { onDone: () => void; onHelp: () => void }) {
  const { role } = useSession();
  const navigate = useNavigate();
  const id = useId();
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus(); // it arrives after the dialog has opened (loaded on first use)
  }, []);
  const [active, setActive] = useState(0);
  const typed = text.trim();
  const q = useDebounced(typed, 200);
  const searching = typed.length >= 2;
  const found = useQuery({
    queryKey: ["search", q],
    queryFn: async () => unwrap(await api.GET("/api/v1/search", { params: { query: { q } } })),
    enabled: q.length >= 2,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });

  const go = (to: string) => {
    onDone();
    void navigate(to);
  };
  const allowed = (e: NavEntry) => !e.action || can(role, e.action);
  const create: Item[] = CREATE.filter(allowed).map((e) => ({
    key: `new:${e.to}`,
    group: "Create",
    label: e.label,
    icon: e.icon,
    run: () => {
      go(e.to);
    },
    words: e.keywords,
  }));
  const pages: Item[] = GROUPS.flatMap((g) =>
    g.items.filter(allowed).map((e) => ({
      key: `go:${e.to}`,
      group: "Go to",
      label: e.label,
      detail: g.title,
      icon: e.icon,
      run: () => {
        go(e.to);
      },
      words: e.keywords,
    })),
  );
  const help: Item = {
    key: "help",
    group: "Help",
    label: "Keyboard shortcuts",
    icon: Keyboard,
    run: () => {
      onDone();
      onHelp();
    },
  };
  const local = [...create, ...pages, help];
  const items: Item[] = typed
    ? [
        ...local.filter((i) => matches(`${i.label} ${i.words ?? ""} ${i.detail ?? ""}`, typed)),
        ...(searching && found.data ? recordItems(found.data, go) : []),
      ]
    : local;
  const current = Math.min(active, Math.max(items.length - 1, 0));
  const optionId = (i: number) => `${id}-option-${String(i)}`;

  useEffect(() => {
    document.getElementById(optionId(current))?.scrollIntoView({ block: "nearest" });
  });

  const onKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    // Keys typed here are for the palette, not for the page behind it (the bill
    // screen's own shortcuts). Tab stays with the dialog, which keeps focus inside.
    if (e.key !== "Tab") e.stopPropagation();
    const n = items.length;
    if (n === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((current + 1) % n);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((current - 1 + n) % n);
    } else if (e.key === "Enter") {
      e.preventDefault();
      items[current]?.run();
    }
  };

  let status: string;
  if (searching && (found.isFetching || q !== typed)) status = "Searching…";
  else if (searching && found.isError) status = "Search is not working right now. Pages still are.";
  else if (!typed) status = "Type a bill number, a client, a project or a page.";
  else if (items.length === 0) status = `Nothing found for “${typed}”.`;
  else status = `${String(items.length)} ${items.length === 1 ? "result" : "results"}`;

  const groups: { name: string; rows: { item: Item; index: number }[] }[] = [];
  items.forEach((item, index) => {
    const last = groups.at(-1);
    if (last?.name === item.group) last.rows.push({ item, index });
    else groups.push({ name: item.group, rows: [{ item, index }] });
  });

  return (
    <>
      <div className="flex items-center gap-2 border-b px-3">
        <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
        <input
          ref={input}
          role="combobox"
          aria-label="Search, or jump to a page"
          aria-expanded={items.length > 0}
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={items.length > 0 ? optionId(current) : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder="Bill number, client, project or page…"
          className="placeholder:text-muted-foreground h-12 min-w-0 flex-1 bg-transparent text-base outline-none"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
        />
      </div>
      <div
        id={`${id}-list`}
        role="listbox"
        aria-label="Results"
        className="max-h-[min(60vh,28rem)] overflow-y-auto p-2"
      >
        {groups.map((g, gi) => (
          <div
            key={g.name}
            role="group"
            aria-labelledby={`${id}-group-${String(gi)}`}
            className="pb-1"
          >
            <div
              id={`${id}-group-${String(gi)}`}
              role="presentation"
              className="text-muted-foreground px-2 pt-2 pb-1 text-xs font-medium"
            >
              {g.name}
            </div>
            {g.rows.map(({ item, index }) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.key}
                  id={optionId(index)}
                  role="option"
                  aria-selected={index === current}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm sm:min-h-0",
                    index === current && "bg-accent text-accent-foreground",
                  )}
                  onMouseMove={() => {
                    if (index !== current) setActive(index);
                  }}
                  onClick={item.run}
                >
                  <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{item.label}</span>
                    {item.detail && (
                      <span className="text-muted-foreground block truncate text-xs">
                        {item.detail}
                      </span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <div className="text-muted-foreground flex items-center justify-between gap-4 border-t px-3 py-2 text-xs">
        <p role="status">{status}</p>
        <p className="hidden sm:block" aria-hidden>
          ↑ ↓ to move · Enter to open · Esc to close
        </p>
      </div>
    </>
  );
}
