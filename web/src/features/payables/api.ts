import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

export type VendorBill = components["schemas"]["VendorBill"];
export type VendorPayment = components["schemas"]["VendorPayment"];
export type TdsSuggestion = components["schemas"]["TdsSuggestion"];
export type VendorBillDetail = components["schemas"]["VendorBillDetail"];
export type WorkOrder = components["schemas"]["WorkOrder"];
export type WorkOrderDetail = components["schemas"]["WorkOrderDetail"];
export type WorkOrderItem = components["schemas"]["WorkOrderItem"];
export type RetentionRelease = components["schemas"]["VendorRetentionRelease"];

export function vendorBillKey(id: string) {
  return ["vendor-bill", id];
}

export function useVendorBill(id: string | undefined) {
  return useQuery({
    queryKey: vendorBillKey(id ?? ""),
    enabled: id !== undefined,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/vendor-bills/{bill_id}", {
          params: { path: { bill_id: id ?? "" } },
        }),
      ),
  });
}

/** A vendor's bills still owed, oldest first (to set a payment against). */
export function useOpenVendorBills(vendorId: string) {
  return useQuery({
    queryKey: ["vendor-bills", "open", vendorId],
    enabled: vendorId !== "",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/vendor-bills", {
          params: {
            query: {
              vendor_party_id: vendorId,
              status: "RECORDED",
              payment_state: "OPEN",
              ordering: "bill_date",
              limit: 100,
            },
          },
        }),
      ).results,
  });
}

export function workOrderKey(id: string) {
  return ["work-order", id];
}

export function useWorkOrder(id: string | undefined) {
  return useQuery({
    queryKey: workOrderKey(id ?? ""),
    enabled: id !== undefined,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/work-orders/{wo_id}", {
          params: { path: { wo_id: id ?? "" } },
        }),
      ),
  });
}

/** A subcontractor's released retention still to pay, oldest first. */
export function useOpenReleases(vendorId: string) {
  return useQuery({
    queryKey: ["vendor-retention-releases", "open", vendorId],
    enabled: vendorId !== "",
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/vendor-retention-releases", {
          params: {
            query: { vendor_party_id: vendorId, open: true, ordering: "release_date", limit: 100 },
          },
        }),
      ).results,
  });
}
