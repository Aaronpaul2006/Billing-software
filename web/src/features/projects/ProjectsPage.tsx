import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { STATES } from "@/lib/india";
import { formatInr } from "@/lib/money";
import { StatusBadge } from "@/components/StatusBadge";
import { projectStatus } from "@/features/projects/status";

import { STATUS_LABELS } from "./api";
import type { ProjectStatus } from "./api";

export function ProjectsPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<ProjectStatus | "">("");
  const q = useDeferredValue(search.trim());

  const projects = useInfiniteQuery({
    queryKey: ["projects", { q, status }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/projects", {
          params: {
            query: {
              ...(q ? { q } : {}),
              ...(status ? { status } : {}),
              ordering: "code",
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

  return (
    <>
      <PageHeader
        title="Projects"
        description="Sites you bill: client, place of supply, deductions and the BOQ."
        actions={
          <Button asChild>
            <Link to="/projects/new">
              <Plus aria-hidden /> New project
            </Link>
          </Button>
        }
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
      </div>

      {projects.error ? (
        <ErrorState error={projects.error} />
      ) : projects.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          {q || status ? "No project matches." : "No projects yet."}
        </p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Client</TableHead>
                <TableHead>Site</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Contract value</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <Link to={`/projects/${p.id}`} className="font-medium hover:underline">
                      {p.name}
                    </Link>
                    <div className="text-muted-foreground font-mono text-xs">{p.code}</div>
                  </TableCell>
                  <TableCell>{p.client_name}</TableCell>
                  <TableCell>{STATES[p.site_state_code] ?? p.site_state_code}</TableCell>
                  <TableCell>
                    <StatusBadge status={projectStatus(p.status)} />
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {p.contract_value ? formatInr(p.contract_value) : "–"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {projects.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={projects.isFetchingNextPage}
                onClick={() => void projects.fetchNextPage()}
              >
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
