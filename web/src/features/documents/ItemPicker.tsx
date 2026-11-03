import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useDeferredValue, useId, useMemo, useState } from "react";
import type { KeyboardEvent } from "react";

import { api, unwrap } from "@/api/client";
import { Input } from "@/components/ui/input";
import { formatInr } from "@/lib/money";
import { cn } from "@/lib/utils";

import { boqChoices, catalogChoices } from "./items";
import type { BoqItem, PickedItem } from "./items";

const MAX = 8;

function words(text: string): string[] {
  return text.toLowerCase().split(/\s+/).filter(Boolean);
}

/**
 * Type to find an item: the project's BOQ (by item code or words), then the
 * catalog (asked from the server). With nothing typed: BOQ items, then the
 * items used most recently. Arrow keys, Enter to choose, Esc to close.
 */
export function ItemPicker({
  id,
  label,
  boq,
  boqOnly = false,
  onPick,
  onCreate,
  invalid = false,
}: {
  id: string;
  /** The current choice's name, shown when not searching. */
  label: string;
  boq: BoqItem[];
  /** RA bills: BOQ items only. */
  boqOnly?: boolean;
  onPick: (item: PickedItem | null) => void;
  /** Offered as "New item" when set (roles that may add catalog items). */
  onCreate?: ((name: string) => void) | undefined;
  invalid?: boolean;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDeferredValue(text.trim());
  const listId = useId();

  const catalog = useQuery({
    queryKey: ["catalog-items", "pick", q],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/catalog-items", {
          params: {
            query: q
              ? { q, is_active: true, ordering: "name", limit: MAX }
              : { used: true, is_active: true, ordering: "-last_used_at", limit: MAX },
          },
        }),
      ).results,
    enabled: open && !boqOnly,
    staleTime: 30_000,
  });

  const options = useMemo(() => {
    const want = words(q);
    const fromBoq = boqChoices(boq)
      .filter((o) => want.every((w) => o.label.toLowerCase().includes(w)))
      .slice(0, MAX);
    const fromCatalog = boqOnly ? [] : catalogChoices(catalog.data ?? []);
    return [...fromBoq, ...fromCatalog];
  }, [q, boq, boqOnly, catalog.data]);
  const offerCreate = onCreate !== undefined && !boqOnly && q.length > 0;
  const count = options.length + (offerCreate ? 1 : 0);

  const choose = (index: number) => {
    const picked = options[index];
    if (picked) onPick(picked);
    else if (offerCreate) onCreate(q);
    setOpen(false);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, Math.max(count - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && open && count > 0) {
      e.preventDefault();
      choose(active);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      setText("");
    }
  };

  const optionId = (i: number) => `${listId}-${String(i)}`;
  return (
    <div className="relative">
      <Input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && count > 0 ? optionId(active) : undefined}
        aria-invalid={invalid}
        autoComplete="off"
        placeholder={boqOnly ? "Type a BOQ item code or words" : "Type to find an item"}
        value={open ? text : label}
        onFocus={() => {
          setOpen(true);
          setActive(0);
        }}
        onBlur={() => {
          setOpen(false);
          setText("");
        }}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setActive(0);
          if (e.target.value === "" && label) onPick(null); // cleared: free text again
        }}
        onKeyDown={onKeyDown}
      />
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Items"
          className="bg-popover absolute z-20 mt-1 max-h-72 w-full min-w-72 overflow-auto rounded-md border p-1 shadow-md"
        >
          {!q && !boqOnly && options.length > 0 && boq.length === 0 && (
            <li role="presentation" className="text-muted-foreground px-2 py-1 text-xs">
              Recently used
            </li>
          )}
          {options.map((o, i) => (
            <li
              key={o.key}
              id={optionId(i)}
              role="option"
              aria-selected={i === active}
              className={cn(
                "flex cursor-pointer justify-between gap-3 rounded-sm px-2 py-1.5 text-sm",
                i === active && "bg-accent",
              )}
              onMouseDown={(e) => {
                e.preventDefault(); // keep the focus until chosen
                choose(i);
              }}
              onMouseEnter={() => {
                setActive(i);
              }}
            >
              <span className="truncate">{o.label}</span>
              <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                {o.fill.rate
                  ? `${formatInr(o.fill.rate)}${o.fill.unit ? ` / ${o.fill.unit}` : ""}`
                  : ""}
              </span>
            </li>
          ))}
          {offerCreate && (
            <li
              id={optionId(options.length)}
              role="option"
              aria-selected={active === options.length}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm font-medium",
                active === options.length && "bg-accent",
              )}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(options.length);
              }}
            >
              <Plus className="size-4" aria-hidden /> New item “{q}”
            </li>
          )}
          {count === 0 && (
            <li role="presentation" className="text-muted-foreground px-2 py-1.5 text-sm">
              {q ? "No item matches. Write it in the Description box instead." : "Type to search."}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
