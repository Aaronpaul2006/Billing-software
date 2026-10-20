import type { RouteObject } from "react-router";

import { RequireAuth } from "@/auth/RequireAuth";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { PartiesPage } from "@/features/parties/PartiesPage";
import { PartyFormPage } from "@/features/parties/PartyFormPage";
import { AppShell } from "@/layout/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { MfaSetupPage } from "@/pages/MfaSetupPage";
import { NotFoundPage, PlaceholderPage } from "@/pages/PlaceholderPage";

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireAuth enrolment />,
    children: [{ path: "/mfa/setup", element: <MfaSetupPage /> }],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: "documents", element: <PlaceholderPage title="Invoices & quotes" /> },
          { path: "payments", element: <PlaceholderPage title="Payments" /> },
          { path: "parties", element: <PartiesPage /> },
          { path: "parties/new", element: <PartyFormPage /> },
          { path: "parties/:partyId", element: <PartyFormPage /> },
          { path: "projects", element: <PlaceholderPage title="Projects" /> },
          { path: "expenses", element: <PlaceholderPage title="Expenses" /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
