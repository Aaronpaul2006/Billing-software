import {
  BadgePercent,
  Banknote,
  BarChart3,
  BookOpen,
  ClipboardList,
  Download,
  FilePlus,
  FileText,
  FolderKanban,
  FolderPlus,
  History,
  Import,
  Hash,
  IndianRupee,
  Landmark,
  LayoutDashboard,
  LayoutTemplate,
  Package,
  Printer,
  Receipt,
  ReceiptText,
  Settings,
  TrendingUp,
  UserCog,
  UserPlus,
  Users,
  Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { Action } from "@/lib/permissions";

export interface NavEntry {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  /** Shown only to roles that may do this (the server checks too). */
  action?: Action;
  /** For links that share a page (Bills and Quotations are both /documents). */
  match?: (path: string, query: URLSearchParams) => boolean;
  /** Other words the command palette finds it by. */
  keywords?: string;
}

/** The sidebar, grouped by job (D.5). */
export const GROUPS: { title: string; items: NavEntry[] }[] = [
  {
    title: "Sell",
    items: [
      {
        to: "/documents?type=quotations",
        label: "Quotations",
        icon: ClipboardList,
        keywords: "estimates quotes",
        match: (path, q) => path === "/documents" && q.get("type") === "quotations",
      },
      {
        to: "/documents?type=bills",
        label: "Bills",
        icon: FileText,
        keywords: "invoices credit debit notes proforma",
        match: (path, q) => path.startsWith("/documents") && q.get("type") !== "quotations",
      },
      { to: "/templates", label: "Templates", icon: LayoutTemplate },
    ],
  },
  {
    title: "Money",
    items: [
      { to: "/payments", label: "Payments", icon: IndianRupee, keywords: "receipts received" },
      {
        to: "/vendor-bills",
        label: "Vendor bills",
        icon: ReceiptText,
        keywords: "payables purchases subcontractor supplier owe tds 194c",
      },
      {
        to: "/vendor-payments",
        label: "Payments to vendors",
        icon: Banknote,
        keywords: "payables paid out supplier subcontractor",
      },
      { to: "/expenses", label: "Expenses", icon: Receipt, keywords: "purchases costs" },
      {
        to: "/bank",
        label: "Bank statements",
        icon: Wallet,
        action: "payments.record",
        keywords: "bank reconcile reconciliation import statement utr",
      },
      {
        to: "/tds-certificates",
        label: "TDS certificates",
        icon: BadgePercent,
        keywords: "form 16a 26as",
      },
    ],
  },
  {
    title: "Work",
    items: [
      { to: "/projects", label: "Projects", icon: FolderKanban, keywords: "sites boq" },
      {
        to: "/parties",
        label: "Clients & vendors",
        icon: Users,
        keywords: "parties customers suppliers subcontractors",
      },
      { to: "/catalog", label: "Catalog", icon: Package, keywords: "items rates materials" },
    ],
  },
  {
    title: "Insight",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      {
        to: "/reports",
        label: "Reports",
        icon: BarChart3,
        action: "reports.view",
        keywords: "gst gstr receivables outstanding",
      },
      {
        to: "/cash-flow",
        label: "Cash flow",
        icon: TrendingUp,
        action: "reports.view",
        keywords: "forecast cashflow weeks balance due",
      },
      {
        to: "/exports",
        label: "Exports",
        icon: Download,
        action: "reports.view",
        keywords: "tally excel download",
      },
    ],
  },
  {
    title: "Settings",
    items: [
      {
        to: "/settings",
        label: "Business settings",
        icon: Settings,
        action: "tenant.settings",
        keywords: "company members gst series printing tally",
        match: (path) => path.startsWith("/settings"),
      },
    ],
  },
];

/** The settings pages, as tabs on the left of the settings screen (D.11). */
export const SETTINGS_TABS: NavEntry[] = [
  {
    to: "/settings/company",
    label: "Company",
    icon: Settings,
    action: "tenant.settings",
    keywords: "business name address logo pan bank upi",
  },
  {
    to: "/settings/members",
    label: "Members",
    icon: UserCog,
    action: "members.manage",
    keywords: "team users invite roles",
  },
  {
    to: "/settings/gst-registrations",
    label: "GST registrations",
    icon: Landmark,
    action: "tenant.settings",
    keywords: "gstin state",
  },
  {
    to: "/settings/series",
    label: "Number series",
    icon: Hash,
    action: "tenant.settings",
    keywords: "invoice numbering prefix",
  },
  {
    to: "/settings/print",
    label: "Bill printing",
    icon: Printer,
    action: "tenant.settings",
    keywords: "pdf print layout signature",
  },
  {
    to: "/settings/tally",
    label: "Tally export",
    icon: BookOpen,
    action: "tenant.settings",
    keywords: "ledgers accounts",
  },
  {
    to: "/settings/activity",
    label: "Activity log",
    icon: History,
    action: "audit.view",
    keywords: "audit who changed history trail",
  },
];

/** "New ..." actions for the command palette (D.6), for the roles that may do them. */
export const CREATE: NavEntry[] = [
  {
    to: "/documents/new",
    label: "New bill",
    icon: FilePlus,
    action: "documents.draft",
    keywords: "invoice create",
  },
  {
    to: "/documents/new?type=QUOTATION",
    label: "New quotation",
    icon: ClipboardList,
    action: "documents.draft",
    keywords: "estimate quote create",
  },
  {
    to: "/payments/new",
    label: "Record a payment",
    icon: IndianRupee,
    action: "payments.record",
    keywords: "receipt received money new",
  },
  {
    to: "/vendor-bills/new",
    label: "Record a vendor bill",
    icon: ReceiptText,
    action: "payments.record",
    keywords: "payables supplier subcontractor purchase new",
  },
  {
    to: "/vendor-payments/new",
    label: "Pay a vendor",
    icon: Banknote,
    action: "payments.record",
    keywords: "payables supplier subcontractor paid out new",
  },
  {
    to: "/expenses/new",
    label: "Record an expense",
    icon: Receipt,
    action: "expenses.record",
    keywords: "purchase cost new",
  },
  {
    to: "/tally-import",
    label: "Import from Tally",
    icon: Import,
    action: "masters.edit",
    keywords: "tally masters ledgers clients vendors items stock xml import",
  },
  {
    to: "/parties/new",
    label: "New client or vendor",
    icon: UserPlus,
    action: "masters.edit",
    keywords: "party customer supplier subcontractor create",
  },
  {
    to: "/projects/new",
    label: "New project",
    icon: FolderPlus,
    action: "masters.edit",
    keywords: "site create",
  },
];
