import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useDeferredValue, useId, useState } from "react";

import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface PickedParty {
  id: string;
  name: string;
}

/**
 * Search-as-you-type picker for a customer (or vendor). Asks the API for at
 * most 10 matches; nothing is loaded until the user types.
 */
export function PartyPicker({
  id,
  value,
  onChange,
  role = "customer",
  invalid = false,
  describedBy,
}: {
  id: string;
  value: PickedParty | null;
  onChange: (party: PickedParty | null) => void;
  role?: "customer" | "vendor";
  invalid?: boolean;
  describedBy?: string | undefined;
}) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const q = useDeferredValue(text.trim());
  const listId = useId();

  const matches = useQuery({
    queryKey: ["parties", "pick", role, q],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/parties", {
          params: {
            query: {
              q,
              is_active: true,
              ordering: "display_name",
              limit: 10,
              ...(role === "customer" ? { is_customer: true } : { is_vendor: true }),
            },
          },
        }),
      ).results,
    enabled: open && q.length > 0,
  });

  if (value && !open) {
    return (
      <div className="flex items-center gap-2">
        <Input id={id} readOnly value={value.name} aria-describedby={describedBy} />
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setOpen(true);
            setText("");
          }}
        >
          Change
        </Button>
      </div>
    );
  }

  const listShown = open && q.length > 0;
  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="search"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={listShown}
          // only while the list is on the page (an id that does not exist is an error)
          aria-controls={listShown ? listId : undefined}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          autoComplete="off"
          placeholder={role === "customer" ? "Search clients by name or GSTIN" : "Search vendors"}
          value={text}
          onFocus={() => {
            setOpen(true);
          }}
          onChange={(e) => {
            setText(e.target.value);
            setOpen(true);
          }}
        />
        {value && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Keep the current choice"
            onClick={() => {
              setOpen(false);
            }}
          >
            <X aria-hidden />
          </Button>
        )}
      </div>
      {listShown && (
        <ul
          id={listId}
          aria-label="Matching parties"
          className="bg-popover absolute z-10 mt-1 max-h-64 w-full overflow-auto rounded-md border p-1 shadow-md"
        >
          {matches.isPending ? (
            <li className="text-muted-foreground px-2 py-1.5 text-sm">Searching…</li>
          ) : !matches.data?.length ? (
            <li className="text-muted-foreground px-2 py-1.5 text-sm">No match.</li>
          ) : (
            matches.data.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  className={cn(
                    "hover:bg-accent focus-visible:bg-accent flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-left text-sm outline-none",
                  )}
                  onClick={() => {
                    onChange({ id: p.id, name: p.display_name });
                    setOpen(false);
                    setText("");
                  }}
                >
                  <span>
                    {p.display_name}
                    {p.gstin && (
                      <span className="text-muted-foreground ml-2 font-mono text-xs">
                        {p.gstin}
                      </span>
                    )}
                  </span>
                  {value?.id === p.id && <Check className="size-4" aria-hidden />}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
