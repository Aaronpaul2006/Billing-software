import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { useSession } from "@/auth/context";
import { DataTable } from "@/components/DataTable";
import type { Column, SortState } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { LoadMore } from "@/components/LoadMore";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { SavedFilters } from "@/components/SavedFilters";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { projectStatus } from "@/features/projects/status";
import { STATES } from "@/lib/india";
import { sumMoney } from "@/lib/money";
import { can } from "@/lib/permissions";

import { STATUS_LABELS } from "./api";
import type { ProjectStatus } from "./api";

type Row = components["schemas"]["Project"];

const columns: Column<Row>[] = [
  {
    id: "project",
    header: "Project",
    sortable: true,
    card: "title",
    cell: (p) => (
      <>
        <Link to={`/projects/${p.id}`} className="font-medium hover:underline">
          {p.name}
        </Link>
        <div className="text-help text-muted-foreground font-mono">{p.code}</div>
      </>
    ),
  },
  { id: "client", header: "Client", card: "subtitle", cell: (p) => p.client_name },
  {
    id: "site",
    header: "Site",
    cell: (p) => STATES[p.site_state_code] ?? p.site_state_code,
  },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (p) => <StatusBadge status={projectStatus(p.status)} />,
  },
  {
    id: "contract",
    header: "Contract value",
    align: "right",
    card: "amount",
    cell: (p) => <Money value={p.contract_value} />,
  },
];

interface Filters extends Record<string, string> {
  search: string;
  status: string;
}
const NO_FILTERS: Filters = { search: "", status: "" };

export function ProjectsPage() {
  const mayEdit = can(useSession().role, "masters.edit");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<ProjectStatus | "">("");
  const [sort, setSort] = useState<SortState>({ column: "project", direction: "asc" });
  const q = useDeferredValue(search.trim());
  const filtered = search.trim() !== "" || status !== "";
  const apply = (f: Filters) => {
    setSearch(f.search);
    setStatus(f.status as ProjectStatus | "");
  };

  const projects = useInfiniteQuery({
    queryKey: ["projects", { q, status, sort }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/projects", {
          params: {
            query: {
              ...(q ? { q } : {}),
              ...(status ? { status } : {}),
              ordering: sort.direction === "desc" ? "-name" : "name",
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = projects.data?.pages.flatMap((p) => p.results) ?? [];
  const valued = rows.filter((p) => p.contract_value !== null);
  const add = mayEdit ? (
    <Button asChild>
      <Link to="/projects/new">
        <Plus aria-hidden /> New project
      </Link>
    </Button>
  ) : undefined;

  return (
    <>
      <PageHeader
        title="Projects"
        description="Sites you bill: client, place of supply, deductions and the BOQ."
        actions={add}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 flex-1">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" aria-hidden />
          <Input
            type="search"
            placeholder="Search by code or name"
            aria-label="Search projects"
            className="pl-8"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
          />
        </div>
        <NativeSelect
          aria-label="Status"
          className="w-auto"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as ProjectStatus | "");
          }}
        >
          <option value="">Any status</option>
          {Object.entries(STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </NativeSelect>
        <SavedFilters list="projects" current={{ search, status }} onApply={apply} />
      </div>

      {projects.error ? (
        <ErrorState error={projects.error} />
      ) : (
        <>
          <DataTable
            label="Projects"
            rows={rows}
            columns={columns}
            rowKey={(p) => p.id}
            rowLabel={(p) => p.name}
            loading={projects.isPending}
            sort={sort}
            onSortChange={setSort}
            empty={
              filtered
                ? {
                    title: "No project matches",
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
                    title: "No projects yet",
                    description: "Add a site to bill it against its BOQ, with retention and TDS.",
                    action: add,
                  }
            }
            totals={
              valued.length > 1
                ? {
                    label: `Total of ${String(valued.length)} with a contract value`,
                    cells: {
                      contract: (
                        <Money value={sumMoney(valued.map((p) => p.contract_value ?? "0"))} />
                      ),
                    },
                  }
                : undefined
            }
          />
          <LoadMore query={projects} />
        </>
      )}
    </>
  );
}
