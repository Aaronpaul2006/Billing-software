import { Bookmark, X } from "lucide-react";
import { useState } from "react";

import { Field } from "@/components/FormField";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { readJson, writeJson } from "@/lib/appearance";

interface Saved {
  name: string;
  filters: Record<string, string>;
}

function load(key: string): Saved[] {
  const raw = readJson(key);
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (x): x is Saved =>
      typeof x === "object" &&
      x !== null &&
      typeof (x as Saved).name === "string" &&
      typeof (x as Saved).filters === "object",
  );
}

/**
 * Saved filters for a list (D.4): name the filters in use ("Unpaid bills of
 * Skyline") and pick them again later. Kept per person, in this browser only.
 */
export function SavedFilters<F extends Record<string, string>>({
  list,
  current,
  onApply,
}: {
  /** Which list, e.g. "bills": each list keeps its own. */
  list: string;
  current: F;
  onApply: (filters: F) => void;
}) {
  const key = `app.savedFilters.${list}`;
  const [saved, setSaved] = useState<Saved[]>(() => load(key));
  const [managing, setManaging] = useState(false);
  const [name, setName] = useState("");

  const store = (next: Saved[]) => {
    writeJson(key, next);
    setSaved(next);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline">
            <Bookmark aria-hidden /> Saved filters
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          {saved.length === 0 && <DropdownMenuItem disabled>None saved yet</DropdownMenuItem>}
          {saved.map((s) => (
            <DropdownMenuItem
              key={s.name}
              onSelect={() => {
                onApply(s.filters as F);
              }}
            >
              {s.name}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onSelect={() => {
              setName("");
              setManaging(true);
            }}
          >
            Save or remove…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={managing} onOpenChange={setManaging}>
        <DialogContent>
          <DialogTitle>Saved filters</DialogTitle>
          <DialogDescription>
            Save the filters in use now under a name. They are kept in this browser.
          </DialogDescription>
          <form
            aria-label="Save these filters"
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              const trimmed = name.trim();
              if (!trimmed) return;
              store([
                ...saved.filter((s) => s.name !== trimmed),
                { name: trimmed, filters: current },
              ]);
              setManaging(false);
            }}
          >
            <Field id="saved-filter-name" label="Name">
              <Input
                id="saved-filter-name"
                value={name}
                maxLength={60}
                placeholder="e.g. Unpaid bills"
                onChange={(e) => {
                  setName(e.target.value);
                }}
              />
            </Field>
            {saved.length > 0 && (
              <ul aria-label="Saved" className="grid gap-1 text-sm">
                {saved.map((s) => (
                  <li key={s.name} className="flex items-center justify-between gap-2">
                    {s.name}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove ${s.name}`}
                      onClick={() => {
                        store(saved.filter((x) => x.name !== s.name));
                      }}
                    >
                      <X aria-hidden />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setManaging(false);
                }}
              >
                Close
              </Button>
              <Button type="submit" disabled={!name.trim()}>
                Save these filters
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
