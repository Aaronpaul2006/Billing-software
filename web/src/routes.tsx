import type { RouteObject } from "react-router";

import { RequireAuth } from "@/auth/RequireAuth";
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
          { index: true, element: <PlaceholderPage title="Dashboard" /> },
          { path: "documents", element: <PlaceholderPage title="Invoices & quotes" /> },
          { path: "payments", element: <PlaceholderPage title="Payments" /> },
          { path: "parties", element: <PlaceholderPage title="Parties" /> },
          { path: "projects", element: <PlaceholderPage title="Projects" /> },
          { path: "expenses", element: <PlaceholderPage title="Expenses" /> },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
