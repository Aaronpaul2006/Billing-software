import { useInfiniteQuery } from "@tanstack/react-query";
import { FileUp, Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { DataTable } from "@/components/DataTable";
import type { Column, SortState } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { LoadMore } from "@/components/LoadMore";
import { PageHeader } from "@/components/PageHeader";
import { SavedFilters } from "@/components/SavedFilters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { can } from "@/lib/permissions";

import { PartyImport } from "./PartyImport";

type Role = "all" | "customers" | "vendors";
type Row = components["schemas"]["Party"];

const ROLE_QUERY: Record<Role, { is_customer?: boolean; is_vendor?: boolean }> = {
  all: {},
  customers: { is_customer: true },
  vendors: { is_vendor: true },
};

const columns: Column<Row>[] = [
  {
    id: "name",
    header: "Name",
    sortable: true,
    card: "title",
    cell: (p) => (
      <>
        <Link to={`/parties/${p.id}`} className="font-medium hover:underline">
          {p.display_name}
        </Link>
        {p.legal_name && p.legal_name !== p.display_name && (
          <div className="text-help text-muted-foreground">{p.legal_name}</div>
        )}
      </>
    ),
  },
  {
    id: "type",
    header: "Type",
    card: "badge",
    cell: (p) => (
      <span className="flex flex-wrap gap-1">
        {p.is_customer && <Badge variant="secondary">Client</Badge>}
        {p.is_vendor && <Badge variant="outline">Vendor</Badge>}
        {!p.is_active && <Badge variant="outline">Archived</Badge>}
      </span>
    ),
  },
  {
    id: "gstin",
    header: "GSTIN",
    card: "subtitle",
    cell: (p) => (p.gstin ? <span className="font-mono text-xs">{p.gstin}</span> : "–"),
  },
  { id: "state", header: "State", cell: (p) => p.state_name ?? "–" },
  { id: "phone", header: "Phone", cell: (p) => p.phone ?? "–" },
];

interface Filters extends Record<string, string> {
  search: string;
  role: string;
  archived: string;
}
const NO_FILTERS: Filters = { search: "", role: "all", archived: "" };

export function PartiesPage() {
  const mayEdit = can(useSession().role, "masters.edit");
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<Role>("all");
  const [archived, setArchived] = useState(false);
  const [importing, setImporting] = useState(false);
  const [sort, setSort] = useState<SortState>({ column: "name", direction: "asc" });
  const q = useDeferredValue(search.trim());
  const filtered = search.trim() !== "" || role !== "all" || archived;
  const apply = (f: Filters) => {
    setSearch(f.search);
    setRole(f.role as Role);
    setArchived(f.archived === "yes");
  };

  const parties = useInfiniteQuery({
    queryKey: ["parties", { q, role, archived, sort }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/parties", {
          params: {
            query: {
              ...(q ? { q } : {}),
              ...ROLE_QUERY[role],
              is_active: !archived,
              ordering: sort.direction === "desc" ? "-display_name" : "display_name",
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = parties.data?.pages.flatMap((p) => p.results) ?? [];
  const add = mayEdit ? (
    <Button asChild>
      <Link to="/parties/new">
        <Plus aria-hidden /> New client or vendor
      </Link>
    </Button>
  ) : undefined;

  return (
    <>
      <PageHeader
        title="Clients & vendors"
        description="Clients you bill, and vendors and subcontractors you buy from."
        actions={
          <>
            {mayEdit && !importing && (
              <Button
                variant="outline"
                onClick={() => {
                  setImporting(true);
                }}
              >
                <FileUp aria-hidden /> Import from Excel
              </Button>
            )}
            {mayEdit && !importing && (
              <Button variant="outline" asChild>
                <Link to="/tally-import">
                  <FileUp aria-hidden /> Import from Tally
                </Link>
              </Button>
            )}
            {add}
          </>
        }
      />
      {importing && (
        <div className="mb-4 max-w-4xl">
          <PartyImport
            onDone={() => {
              setImporting(false);
            }}
          />
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 flex-1">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" aria-hidden />
          <Input
            type="search"
            placeholder="Search by name or GSTIN"
            aria-label="Search parties"
            className="pl-8"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
          />
        </div>
        <NativeSelect
          aria-label="Show"
          className="w-auto"
          value={role}
          onChange={(e) => {
            setRole(e.target.value as Role);
          }}
        >
          <option value="all">Clients and vendors</option>
          <option value="customers">Clients</option>
          <option value="vendors">Vendors</option>
        </NativeSelect>
        <label className="flex min-h-9 items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => {
              setArchived(e.target.checked);
            }}
          />
          Archived
        </label>
        <SavedFilters
          list="parties"
          current={{ search, role, archived: archived ? "yes" : "" }}
          onApply={apply}
        />
      </div>

      {parties.error ? (
        <ErrorState error={parties.error} />
      ) : (
        <>
          <DataTable
            label="Clients and vendors"
            rows={rows}
            columns={columns}
            rowKey={(p) => p.id}
            rowLabel={(p) => p.display_name}
            loading={parties.isPending}
            sort={sort}
            onSortChange={setSort}
            empty={
              filtered
                ? {
                    title: q ? "No one matches your search" : "No one matches these filters",
                    action: (
                      <Button
                        variant="outline"
                        onClick={() => {
                          apply(NO_FILTERS);
                        }}
                      >
                        Clear the filters
                      </Button>
                    ),
                  }
                : {
                    title: "No clients or vendors yet",
                    description:
                      "Add the clients you bill (with their GSTIN) or import them from Excel.",
                    action: add,
                  }
            }
          />
          <LoadMore query={parties} />
        </>
      )}
    </>
  );
}
