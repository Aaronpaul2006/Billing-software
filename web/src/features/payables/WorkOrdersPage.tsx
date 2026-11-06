import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "@/api/client";
import { useSession } from "@/auth/context";
import { DataTable } from "@/components/DataTable";
import type { Column } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { LoadMore } from "@/components/LoadMore";
import { Money } from "@/components/Money";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { formatDate } from "@/lib/dates";
import { can } from "@/lib/permissions";

import type { WorkOrder } from "./api";
import { billedPercent } from "./status";

type Show = "OPEN" | "CLOSED" | "";

export function WorkOrderBadge({ status }: { status: WorkOrder["status"] }) {
  return status === "OPEN" ? (
    <StatusBadge status="active">Open</StatusBadge>
  ) : (
    <StatusBadge status="completed">Closed</StatusBadge>
  );
}

const columns: Column<WorkOrder>[] = [
  {
    id: "wo",
    header: "Work order",
    card: "title",
    cell: (wo) => (
      <>
        <Link to={`/work-orders/${wo.id}`} className="font-medium hover:underline">
          {wo.wo_number}
        </Link>
        <div className="text-help text-muted-foreground">{wo.title}</div>
      </>
    ),
  },
  {
    id: "sub",
    header: "Subcontractor",
    card: "subtitle",
    cell: (wo) => (
      <>
        {wo.vendor_name}
        <div className="text-help text-muted-foreground">
          {wo.project_code} · {formatDate(wo.wo_date)}
        </div>
      </>
    ),
  },
  {
    id: "status",
    header: "Status",
    card: "badge",
    cell: (wo) => <WorkOrderBadge status={wo.status} />,
  },
  {
    id: "value",
    header: "Value",
    align: "right",
    card: "detail",
    cell: (wo) => <Money value={wo.value} />,
  },
  {
    id: "billed",
    header: "Billed so far",
    align: "right",
    card: "amount",
    cell: (wo) => (
      <span className="whitespace-nowrap">
        <Money value={wo.billed} />
        <span className="text-muted-foreground text-help"> · {billedPercent(wo)} %</span>
      </span>
    ),
  },
  {
    id: "retention",
    header: "Retention held",
    align: "right",
    card: "detail",
    cell: (wo) => <Money value={wo.retention_held} muted={wo.retention_held === "0.00"} />,
  },
];

export function WorkOrdersPage() {
  const { role } = useSession();
  const mayRecord = can(role, "payments.record");
  const [search, setSearch] = useState("");
  const [show, setShow] = useState<Show>("OPEN");
  const q = useDeferredValue(search.trim());
  const orders = useInfiniteQuery({
    queryKey: ["work-orders", { q, show }],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/work-orders", {
          params: {
            query: {
              ...(q ? { q } : {}),
              ...(show ? { status: show } : {}),
              ordering: "-wo_date",
              limit: 50,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = orders.data?.pages.flatMap((p) => p.results) ?? [];
  const add = mayRecord ? (
    <Button asChild>
      <Link to="/work-orders/new">
        <Plus aria-hidden /> New work order
      </Link>
    </Button>
  ) : undefined;

  return (
    <>
      <PageHeader
        title="Work orders"
        description="Work let to subcontractors at agreed rates, and the RA bills they send against it."
        actions={add}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-60 flex-1">
          <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" aria-hidden />
          <Input
            type="search"
            placeholder="Search by number, scope or subcontractor"
            aria-label="Search work orders"
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
          value={show}
          onChange={(e) => {
            setShow(e.target.value as Show);
          }}
        >
          <option value="OPEN">Open</option>
          <option value="CLOSED">Closed</option>
          <option value="">All</option>
        </NativeSelect>
      </div>
      {orders.error ? (
        <ErrorState error={orders.error} />
      ) : (
        <>
          <DataTable
            label="Work orders"
            rows={rows}
            columns={columns}
            rowKey={(wo) => wo.id}
            rowLabel={(wo) => `${wo.wo_number} ${wo.vendor_name}`}
            loading={orders.isPending}
            empty={
              q || show !== "OPEN"
                ? { title: "No work orders match" }
                : {
                    title: "No open work orders",
                    description:
                      "Let work to a subcontractor item by item; their RA bills are then checked against it.",
                    action: add,
                  }
            }
          />
          <LoadMore query={orders} />
        </>
      )}
    </>
  );
}
