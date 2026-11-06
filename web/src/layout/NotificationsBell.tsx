import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { formatDateTime } from "@/lib/dates";
import { cn } from "@/lib/utils";

const KEY = ["notifications"];

/** The bell: how many are unread, and the latest few (Part B). */
export function NotificationsBell({ className }: { className?: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const count = useQuery({
    queryKey: [...KEY, "unread-count"],
    queryFn: async () => unwrap(await api.GET("/api/v1/notifications/unread-count")).count,
    refetchInterval: 60_000,
  });
  const latest = useQuery({
    queryKey: [...KEY, "latest"],
    enabled: open,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/notifications", { params: { query: { limit: 8 } } })).results,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: KEY });
  };
  const read = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/notifications/{notification_id}/read", {
          params: { path: { notification_id: id } },
        }),
      ),
    onSuccess: refresh,
  });
  const readAll = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/notifications/read-all")),
    onSuccess: refresh,
  });
  const unread = count.data ?? 0;
  const items = latest.data ?? [];

  return (
    <DropdownMenu open={open} onOpenChange={setOpen} modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("relative", className)}
          aria-label={unread ? `Notifications, ${String(unread)} unread` : "Notifications"}
        >
          <Bell className="size-5" aria-hidden />
          {unread > 0 && (
            <span
              aria-hidden
              className="bg-destructive text-destructive-foreground absolute top-1 right-1 min-w-4 rounded-full px-1 text-[0.625rem] leading-4 font-semibold"
            >
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {latest.isPending ? (
          <DropdownMenuLabel className="text-muted-foreground font-normal">
            Looking…
          </DropdownMenuLabel>
        ) : items.length === 0 ? (
          <DropdownMenuLabel className="text-muted-foreground font-normal">
            Nothing yet. Quotations answered in the portal, bills falling overdue and payments
            coming due will show here.
          </DropdownMenuLabel>
        ) : (
          items.map((n) => (
            <DropdownMenuItem
              key={n.id}
              className="flex flex-col items-start gap-0.5 py-2"
              onSelect={() => {
                if (!n.read_at) read.mutate(n.id);
                if (n.link) void navigate(n.link);
              }}
            >
              <span className={cn("text-sm", !n.read_at && "font-semibold")}>
                {!n.read_at && <span className="sr-only">New: </span>}
                {n.title}
              </span>
              {n.body && <span className="text-muted-foreground text-xs">{n.body}</span>}
              <span className="text-muted-foreground text-xs">{formatDateTime(n.created_at)}</span>
            </DropdownMenuItem>
          ))
        )}
        {unread > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={(e) => {
                e.preventDefault();
                readAll.mutate();
              }}
            >
              Mark all read
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
