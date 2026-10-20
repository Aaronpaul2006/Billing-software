import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
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

type Role = "all" | "customers" | "vendors";

const ROLE_QUERY: Record<Role, { is_customer?: boolean; is_vendor?: boolean }> = {
  all: {},
  customers: { is_customer: true },
  vendors: { is_vendor: true },
};

export function PartiesPage() {
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<Role>("all");
  const [archived, setArchived] = useState(false);
  const q = useDeferredValue(search.trim());

  const parties = useInfiniteQuery({
    queryKey: ["parties", { q, role, archived }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/parties", {
          params: {
            query: {
              ...(q ? { q } : {}),
              ...ROLE_QUERY[role],
              is_active: !archived,
              ordering: "display_name",
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

  return (
    <>
      <PageHeader
        title="Parties"
        description="Clients you bill and vendors you buy from."
        actions={
          <Button asChild>
            <Link to="/parties/new">
              <Plus aria-hidden /> New party
            </Link>
          </Button>
        }
      />
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
          <option value="all">Customers and vendors</option>
          <option value="customers">Customers</option>
          <option value="vendors">Vendors</option>
        </NativeSelect>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={archived}
            onChange={(e) => {
              setArchived(e.target.checked);
            }}
          />
          Archived
        </label>
      </div>

      {parties.error ? (
        <ErrorState error={parties.error} />
      ) : parties.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          {q ? "No party matches your search." : "No parties yet."}
        </p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>GSTIN</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Phone</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>
                    <Link to={`/parties/${p.id}`} className="font-medium hover:underline">
                      {p.display_name}
                    </Link>
                    {p.legal_name && p.legal_name !== p.display_name && (
                      <div className="text-muted-foreground text-xs">{p.legal_name}</div>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{p.gstin ?? "–"}</TableCell>
                  <TableCell>{p.state_name ?? "–"}</TableCell>
                  <TableCell className="flex gap-1">
                    {p.is_customer && <Badge variant="secondary">Customer</Badge>}
                    {p.is_vendor && <Badge variant="outline">Vendor</Badge>}
                  </TableCell>
                  <TableCell>{p.phone ?? "–"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {parties.hasNextPage && (
            <div className="mt-4 flex justify-center">
              <Button
                variant="outline"
                disabled={parties.isFetchingNextPage}
                onClick={() => void parties.fetchNextPage()}
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
