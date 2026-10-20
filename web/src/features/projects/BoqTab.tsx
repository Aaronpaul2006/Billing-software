import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FileUp, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, unwrap } from "@/api/client";
import { ApiError } from "@/api/problem";
import { ErrorState } from "@/components/ErrorState";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatInr, formatQty } from "@/lib/money";

import { useProjectOutlet } from "./api";
import { BoqImport } from "./BoqImport";
import { BoqItemForm } from "./BoqItemForm";

type Panel = { kind: "none" } | { kind: "add" } | { kind: "edit"; id: string } | { kind: "import" };

export function BoqTab() {
  const { project } = useProjectOutlet();
  const queryClient = useQueryClient();
  const [panel, setPanel] = useState<Panel>({ kind: "none" });
  const [notice, setNotice] = useState<string | null>(null);

  const items = useInfiniteQuery({
    queryKey: ["boq", project.id],
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/api/v1/projects/{project_id}/boq-items", {
          params: {
            path: { project_id: project.id },
            query: {
              ordering: "sort_order",
              limit: 100,
              ...(pageParam ? { cursor: pageParam } : {}),
            },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
  const rows = items.data?.pages.flatMap((p) => p.results) ?? [];

  const remove = useMutation({
    mutationFn: async (id: string) => {
      unwrap(
        await api.DELETE("/api/v1/boq-items/{item_id}", { params: { path: { item_id: id } } }),
      );
    },
    onSuccess: () => {
      setNotice(null);
      void queryClient.invalidateQueries({ queryKey: ["boq", project.id] });
    },
    onError: (e) => {
      setNotice(
        e instanceof ApiError && e.code === "boq_item_billed"
          ? "This item has been billed, so it cannot be deleted. Change its quantity or mark it a variation instead."
          : e.message,
      );
    },
  });

  const close = () => {
    setPanel({ kind: "none" });
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2">
        <Button
          onClick={() => {
            setPanel({ kind: "add" });
          }}
        >
          <Plus aria-hidden /> Add item
        </Button>
        <Button
          variant="outline"
          onClick={() => {
            setPanel({ kind: "import" });
          }}
        >
          <FileUp aria-hidden /> Import from file
        </Button>
      </div>

      {panel.kind === "add" && <BoqItemForm projectId={project.id} onDone={close} />}
      {panel.kind === "import" && <BoqImport projectId={project.id} onDone={close} />}
      {notice && (
        <Alert variant="destructive">
          <AlertDescription>{notice}</AlertDescription>
        </Alert>
      )}

      {items.error ? (
        <ErrorState error={items.error} />
      ) : items.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          No BOQ items yet. Add them one by one or import the client's BOQ file.
        </p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>Unit</TableHead>
                <TableHead className="text-right">Contract qty</TableHead>
                <TableHead className="text-right">Rate</TableHead>
                <TableHead className="text-right">GST %</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((item) =>
                panel.kind === "edit" && panel.id === item.id ? (
                  <TableRow key={item.id}>
                    <TableCell colSpan={7}>
                      <BoqItemForm projectId={project.id} item={item} onDone={close} />
                    </TableCell>
                  </TableRow>
                ) : (
                  <TableRow key={item.id}>
                    <TableCell className="font-mono">{item.item_code}</TableCell>
                    <TableCell className="max-w-[28rem] whitespace-normal">
                      {item.description}
                      {item.is_variation && (
                        <Badge variant="outline" className="ml-2">
                          Variation
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>{item.unit}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatQty(item.contract_qty)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatInr(item.rate)}
                    </TableCell>
                    <TableCell className="text-right">{formatQty(item.gst_rate)}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Edit ${item.item_code}`}
                        onClick={() => {
                          setPanel({ kind: "edit", id: item.id });
                        }}
                      >
                        <Pencil aria-hidden />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Delete ${item.item_code}`}
                        disabled={remove.isPending}
                        onClick={() => {
                          if (window.confirm(`Delete item ${item.item_code}?`))
                            remove.mutate(item.id);
                        }}
                      >
                        <Trash2 aria-hidden />
                      </Button>
                    </TableCell>
                  </TableRow>
                ),
              )}
            </TableBody>
          </Table>
          {items.hasNextPage && (
            <div className="flex justify-center">
              <Button
                variant="outline"
                disabled={items.isFetchingNextPage}
                onClick={() => void items.fetchNextPage()}
              >
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
