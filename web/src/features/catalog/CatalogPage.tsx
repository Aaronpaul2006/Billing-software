import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, FileUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, newIdempotencyKey, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { ErrorState } from "@/components/ErrorState";
import { Field } from "@/components/FormField";
import { PageHeader } from "@/components/PageHeader";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/errors";
import { ifMatch } from "@/lib/forms";
import { cleanMoneyInput, formatInr, MONEY_INPUT, sumMoney } from "@/lib/money";
import { useDebounced } from "@/lib/useDebounced";

import { CatalogImport } from "./CatalogImport";

type Item = components["schemas"]["CatalogItem"];
type Variant = components["schemas"]["CatalogVariant"];

const CAN_EDIT = new Set(["OWNER", "ADMIN", "ACCOUNTANT"]); // backend: masters.edit
const SIGNED_MONEY = /^-?\d{1,12}(\.\d{1,2})?$/;

function problemText(e: unknown): string {
  if (e instanceof ApiError && e.code === "variant_exists")
    return "This item already has that variant.";
  if (e instanceof ApiError && e.code === "variant_used") {
    return "Bills use this variant: archive it instead, so it is no longer offered.";
  }
  if (e instanceof ApiError && e.code === "catalog_item_used") {
    return "Bills use this item: archive it instead.";
  }
  if (e instanceof ApiError && e.problem.errors?.length) {
    return e.problem.errors.map((x) => x.message).join(" ");
  }
  return errorMessage(e);
}

/** "+₹20.00" / "-₹15.00" / "base rate". */
function delta(amount: string): string {
  if (/^-?0+(\.0+)?$/.test(amount)) return "same rate";
  return amount.startsWith("-") ? formatInr(amount) : `+${formatInr(amount)}`;
}

function ItemForm({ item, onDone }: { item?: Item; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(item?.name ?? "");
  const [unit, setUnit] = useState(item?.unit ?? "");
  const [hsn, setHsn] = useState(item?.sac_hsn ?? "");
  const [rate, setRate] = useState(item?.default_rate ?? "");
  const [gst, setGst] = useState(item?.gst_rate ?? "18.00");
  const [error, setError] = useState<string | null>(null);
  const [key] = useState(newIdempotencyKey);
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: name.trim(),
        unit: unit.trim() || null,
        sac_hsn: hsn.trim() || null,
        default_rate: cleanMoneyInput(rate) || null,
        gst_rate: gst.trim(),
      };
      return item
        ? unwrap(
            await api.PATCH("/api/v1/catalog-items/{item_id}", {
              params: { path: { item_id: item.id } },
              body,
              headers: { "If-Match": ifMatch(item.version) },
            }),
          )
        : unwrap(
            await api.POST("/api/v1/catalog-items", { body, headers: { "Idempotency-Key": key } }),
          );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["catalog-items"] });
      onDone();
    },
    onError: (e) => {
      setError(problemText(e));
    },
  });
  const prefix = item ? `item-${item.id}` : "item-new";
  return (
    <form
      aria-label={item ? `Edit ${item.name}` : "New item"}
      className="bg-muted/40 grid gap-3 rounded-lg border p-3 sm:grid-cols-6"
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        if (!name.trim()) {
          setError("Enter the item's name.");
          return;
        }
        if (rate.trim() && !MONEY_INPUT.test(cleanMoneyInput(rate))) {
          setError("Enter the rate as an amount, e.g. 380 or 380.50.");
          return;
        }
        save.mutate();
      }}
    >
      <div className="sm:col-span-2">
        <Field id={`${prefix}-name`} label="Name">
          <Input
            id={`${prefix}-name`}
            value={name}
            maxLength={200}
            onChange={(e) => {
              setName(e.target.value);
            }}
          />
        </Field>
      </div>
      <Field id={`${prefix}-unit`} label="Unit">
        <Input
          id={`${prefix}-unit`}
          value={unit}
          maxLength={20}
          placeholder="bag, cum…"
          onChange={(e) => {
            setUnit(e.target.value);
          }}
        />
      </Field>
      <Field id={`${prefix}-hsn`} label="HSN / SAC">
        <Input
          id={`${prefix}-hsn`}
          value={hsn}
          inputMode="numeric"
          onChange={(e) => {
            setHsn(e.target.value);
          }}
        />
      </Field>
      <Field id={`${prefix}-rate`} label="Rate (₹)">
        <Input
          id={`${prefix}-rate`}
          value={rate}
          inputMode="decimal"
          onChange={(e) => {
            setRate(e.target.value);
          }}
        />
      </Field>
      <Field id={`${prefix}-gst`} label="GST %">
        <Input
          id={`${prefix}-gst`}
          value={gst}
          inputMode="decimal"
          onChange={(e) => {
            setGst(e.target.value);
          }}
        />
      </Field>
      {error && (
        <Alert variant="destructive" className="sm:col-span-6">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="flex gap-2 sm:col-span-6">
        <Button type="submit" disabled={save.isPending}>
          {item ? "Save" : "Add item"}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function Variants({ item, canEdit }: { item: Item; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [attribute, setAttribute] = useState("");
  const [value, setValue] = useState("");
  const [change, setChange] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(newIdempotencyKey);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["catalog-items"] });
  };
  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/catalog-items/{item_id}/variants", {
          params: { path: { item_id: item.id } },
          body: {
            attribute: attribute.trim(),
            value: value.trim(),
            rate_delta: cleanMoneyInput(change) || "0",
          },
          headers: { "Idempotency-Key": key },
        }),
      ),
    onSuccess: () => {
      setKey(newIdempotencyKey());
      setValue("");
      setChange("");
      refresh();
    },
    onError: (e) => {
      setError(problemText(e));
    },
  });
  const archive = useMutation({
    mutationFn: async (v: Variant) =>
      unwrap(
        await api.PATCH("/api/v1/catalog-variants/{variant_id}", {
          params: { path: { variant_id: v.id } },
          body: { is_active: !v.is_active },
          headers: { "If-Match": ifMatch(v.version) },
        }),
      ),
    onSuccess: refresh,
    onError: (e) => {
      setError(problemText(e));
    },
  });
  const remove = useMutation({
    mutationFn: async (v: Variant) => {
      unwrap(
        await api.DELETE("/api/v1/catalog-variants/{variant_id}", {
          params: { path: { variant_id: v.id } },
        }),
      );
    },
    onSuccess: refresh,
    onError: (e) => {
      setError(problemText(e));
    },
  });
  return (
    <section aria-label={`Variants of ${item.name}`} className="mt-3 grid gap-2">
      {item.variants.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No variants. Add one when the rate depends on a brand, grade or size.
        </p>
      ) : (
        <ul className="divide-y rounded-md border text-sm">
          {item.variants.map((v) => {
            const rate = item.default_rate ? sumMoney([item.default_rate, v.rate_delta]) : null;
            return (
              <li key={v.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <span className="flex-1">
                  {v.attribute}: <strong>{v.value}</strong>{" "}
                  <span className="text-muted-foreground">
                    {delta(v.rate_delta)}
                    {rate !== null ? ` → ${formatInr(rate)}` : ""}
                  </span>
                  {!v.is_active && (
                    <Badge variant="secondary" className="ml-2">
                      Archived
                    </Badge>
                  )}
                </span>
                {canEdit && (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={archive.isPending}
                      onClick={() => {
                        setError(null);
                        archive.mutate(v);
                      }}
                    >
                      {v.is_active ? "Archive" : "Restore"}
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label={`Delete ${v.attribute}: ${v.value}`}
                      disabled={remove.isPending}
                      onClick={() => {
                        setError(null);
                        remove.mutate(v);
                      }}
                    >
                      <Trash2 aria-hidden />
                    </Button>
                  </>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertCircle aria-hidden />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {canEdit && (
        <form
          aria-label={`Add a variant of ${item.name}`}
          className="grid gap-2 sm:grid-cols-[1fr_1fr_8rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            if (!attribute.trim() || !value.trim()) {
              setError("Enter what varies and its value.");
              return;
            }
            if (change.trim() && !SIGNED_MONEY.test(cleanMoneyInput(change))) {
              setError("Enter the rate change as an amount, e.g. 20 or -15.");
              return;
            }
            add.mutate();
          }}
        >
          <Field id={`${item.id}-attribute`} label="What varies">
            <Input
              id={`${item.id}-attribute`}
              value={attribute}
              placeholder="Brand"
              maxLength={50}
              onChange={(e) => {
                setAttribute(e.target.value);
              }}
            />
          </Field>
          <Field id={`${item.id}-value`} label="Value">
            <Input
              id={`${item.id}-value`}
              value={value}
              placeholder="UltraTech"
              maxLength={100}
              onChange={(e) => {
                setValue(e.target.value);
              }}
            />
          </Field>
          <Field id={`${item.id}-change`} label="Rate change (₹)">
            <Input
              id={`${item.id}-change`}
              value={change}
              placeholder="+20 or -15"
              inputMode="decimal"
              onChange={(e) => {
                setChange(e.target.value.replace(/^\+/, ""));
              }}
            />
          </Field>
          <Button type="submit" variant="outline" disabled={add.isPending}>
            Add variant
          </Button>
        </form>
      )}
    </section>
  );
}

/** Items and rates used on bills, with their variants (brand, grade...). */
export function CatalogPage() {
  const session = useSession();
  const canEdit = CAN_EDIT.has(session.role);
  // "new", "import", "edit:<id>", "variants:<id>"
  const [panel, setPanel] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const page = useQuery({
    queryKey: ["catalog-items", "all", q],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/catalog-items", {
          params: { query: { limit: 100, ordering: "name", ...(q ? { q } : {}) } },
        }),
      ),
  });
  const items = { error: page.error, data: page.data?.results };
  return (
    <>
      <PageHeader
        title="Catalog"
        description="Items and rates you put on bills. Variants (brand, grade, size) add to or take off the item's rate."
        actions={
          canEdit && (
            <>
              {panel !== "import" && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setPanel("import");
                  }}
                >
                  <FileUp aria-hidden /> Import from Excel
                </Button>
              )}
              {panel !== "new" && (
                <Button
                  onClick={() => {
                    setPanel("new");
                  }}
                >
                  <Plus aria-hidden /> Add item
                </Button>
              )}
            </>
          )
        }
      />
      {panel === "import" && (
        <div className="mb-4 max-w-4xl">
          <CatalogImport
            onDone={() => {
              setPanel(null);
            }}
          />
        </div>
      )}
      <div className="mb-4 max-w-4xl">
        <Input
          type="search"
          aria-label="Search items"
          placeholder="Search by name, brand or HSN/SAC"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
        />
      </div>
      {panel === "new" && (
        <div className="mb-4 max-w-4xl">
          <ItemForm
            onDone={() => {
              setPanel(null);
            }}
          />
        </div>
      )}
      {items.error ? (
        <ErrorState error={items.error} />
      ) : !items.data ? (
        <Skeleton className="h-24 w-full" />
      ) : items.data.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          {q ? "No item matches." : "No items yet."}
        </p>
      ) : (
        <ul className="grid max-w-4xl gap-3">
          {items.data.map((item) => (
            <li key={item.id} className="rounded-lg border p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-48 flex-1">
                  <div className="font-medium">
                    {item.name}
                    {!item.is_active && (
                      <Badge variant="secondary" className="ml-2">
                        Archived
                      </Badge>
                    )}
                  </div>
                  <div className="text-muted-foreground text-sm">
                    {item.default_rate ? formatInr(item.default_rate) : "No rate"}
                    {item.unit ? ` per ${item.unit}` : ""} · GST {item.gst_rate} %
                    {item.sac_hsn ? ` · HSN/SAC ${item.sac_hsn}` : ""}
                    {item.variants.length > 0
                      ? ` · ${String(item.variants.length)} variant${item.variants.length === 1 ? "" : "s"}`
                      : ""}
                  </div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setPanel(panel === `variants:${item.id}` ? null : `variants:${item.id}`);
                  }}
                >
                  Variants
                </Button>
                {canEdit && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setPanel(`edit:${item.id}`);
                    }}
                  >
                    Edit
                  </Button>
                )}
              </div>
              {panel === `edit:${item.id}` && (
                <div className="mt-3">
                  <ItemForm
                    item={item}
                    onDone={() => {
                      setPanel(null);
                    }}
                  />
                </div>
              )}
              {panel === `variants:${item.id}` && <Variants item={item} canEdit={canEdit} />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
