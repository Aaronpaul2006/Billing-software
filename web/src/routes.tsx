import type { ComponentType } from "react";
import { Navigate } from "react-router";
import type { RouteObject } from "react-router";

import { RequireAuth } from "@/auth/RequireAuth";
import { AppShell } from "@/layout/AppShell";
import { NotFoundPage } from "@/pages/PlaceholderPage";

/** Load a page's code when it is first opened (keeps the first download small). */
function lazyPage<M>(load: () => Promise<M>, pick: (module: M) => ComponentType) {
  return async () => ({ Component: pick(await load()) });
}

const projects = () => import("@/features/projects/ProjectLayout");
const documents = () => import("@/features/documents/DocumentPage");
const portalShell = () => import("@/features/portal/PortalShell");
const portalPages = () => import("@/features/portal/PortalPages");

/** The living style guide (D.3): development builds, or builds made with VITE_DESIGN_PAGE=true. */
const designPage: RouteObject[] =
  import.meta.env.DEV || import.meta.env.VITE_DESIGN_PAGE === "true"
    ? [
        {
          path: "/design",
          lazy: lazyPage(
            () => import("@/pages/DesignPage"),
            (m) => m.DesignPage,
          ),
        },
      ]
    : [];

export const routes: RouteObject[] = [
  ...designPage,
  {
    path: "/login",
    lazy: lazyPage(
      () => import("@/pages/LoginPage"),
      (m) => m.LoginPage,
    ),
  },
  {
    path: "/signup",
    lazy: lazyPage(
      () => import("@/pages/SignupPage"),
      (m) => m.SignupPage,
    ),
  },
  {
    path: "/forgot-password",
    lazy: lazyPage(
      () => import("@/pages/ForgotPasswordPage"),
      (m) => m.ForgotPasswordPage,
    ),
  },
  {
    path: "/reset-password",
    lazy: lazyPage(
      () => import("@/pages/ResetPasswordPage"),
      (m) => m.ResetPasswordPage,
    ),
  },
  {
    path: "/join",
    lazy: lazyPage(
      () => import("@/pages/JoinPage"),
      (m) => m.JoinPage,
    ),
  },
  {
    path: "/confirm-email",
    lazy: lazyPage(
      () => import("@/pages/ConfirmEmailPage"),
      (m) => m.ConfirmEmailPage,
    ),
  },
  {
    path: "/verify-email",
    lazy: lazyPage(
      () => import("@/pages/VerifyEmailPage"),
      (m) => m.VerifyEmailPage,
    ),
  },
  {
    element: <RequireAuth enrolment />,
    children: [
      {
        path: "/mfa/setup",
        lazy: lazyPage(
          () => import("@/pages/MfaSetupPage"),
          (m) => m.MfaSetupPage,
        ),
      },
    ],
  },
  {
    // The client portal (W.5): people at a client, signed in with role CLIENT.
    path: "/portal",
    element: <RequireAuth portal />,
    children: [
      {
        lazy: lazyPage(portalShell, (m) => m.PortalShell),
        children: [
          { index: true, lazy: lazyPage(portalPages, (m) => m.PortalHomePage) },
          { path: "bills", lazy: lazyPage(portalPages, (m) => m.PortalDocumentsPage) },
          {
            path: "bills/:documentId",
            lazy: lazyPage(
              () => import("@/features/portal/PortalDocumentPage"),
              (m) => m.PortalDocumentPage,
            ),
          },
          { path: "payments", lazy: lazyPage(portalPages, (m) => m.PortalPaymentsPage) },
          { path: "statement", lazy: lazyPage(portalPages, (m) => m.PortalStatementPage) },
          { path: "projects", lazy: lazyPage(portalPages, (m) => m.PortalProjectsPage) },
          { path: "projects/:projectId", lazy: lazyPage(portalPages, (m) => m.PortalProjectPage) },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          {
            index: true,
            lazy: lazyPage(
              () => import("@/features/dashboard/DashboardPage"),
              (m) => m.DashboardPage,
            ),
          },
          {
            path: "documents",
            lazy: lazyPage(
              () => import("@/features/documents/DocumentsPage"),
              (m) => m.DocumentsPage,
            ),
          },
          {
            path: "documents/new",
            lazy: lazyPage(
              () => import("@/features/documents/DocumentEditor"),
              (m) => m.NewDocumentPage,
            ),
          },
          { path: "documents/:documentId", lazy: lazyPage(documents, (m) => m.DocumentPage) },
          {
            path: "catalog",
            lazy: lazyPage(
              () => import("@/features/catalog/CatalogPage"),
              (m) => m.CatalogPage,
            ),
          },
          {
            path: "templates",
            lazy: lazyPage(
              () => import("@/features/templates/TemplatesPage"),
              (m) => m.TemplatesPage,
            ),
          },
          {
            path: "documents/:documentId/edit",
            lazy: lazyPage(
              () => import("@/features/documents/DocumentEditor"),
              (m) => m.EditDocumentPage,
            ),
          },
          {
            path: "payments",
            lazy: lazyPage(
              () => import("@/features/payments/PaymentsPage"),
              (m) => m.PaymentsPage,
            ),
          },
          {
            path: "payments/new",
            lazy: lazyPage(
              () => import("@/features/payments/NewPaymentPage"),
              (m) => m.NewPaymentPage,
            ),
          },
          {
            path: "payments/:paymentId",
            lazy: lazyPage(
              () => import("@/features/payments/PaymentPage"),
              (m) => m.PaymentPage,
            ),
          },
          {
            path: "parties",
            lazy: lazyPage(
              () => import("@/features/parties/PartiesPage"),
              (m) => m.PartiesPage,
            ),
          },
          {
            path: "parties/new",
            lazy: lazyPage(
              () => import("@/features/parties/PartyFormPage"),
              (m) => m.PartyFormPage,
            ),
          },
          {
            path: "parties/:partyId",
            lazy: lazyPage(
              () => import("@/features/parties/PartyFormPage"),
              (m) => m.PartyFormPage,
            ),
          },
          {
            path: "parties/:partyId/statement",
            lazy: lazyPage(
              () => import("@/features/parties/StatementPage"),
              (m) => m.StatementPage,
            ),
          },
          {
            path: "projects",
            lazy: lazyPage(
              () => import("@/features/projects/ProjectsPage"),
              (m) => m.ProjectsPage,
            ),
          },
          { path: "projects/new", lazy: lazyPage(projects, (m) => m.NewProjectPage) },
          {
            path: "projects/:projectId",
            lazy: lazyPage(projects, (m) => m.ProjectLayout),
            children: [
              { index: true, lazy: lazyPage(projects, (m) => m.ProjectDetailsTab) },
              {
                path: "boq",
                lazy: lazyPage(
                  () => import("@/features/projects/BoqTab"),
                  (m) => m.BoqTab,
                ),
              },
              {
                path: "progress",
                lazy: lazyPage(
                  () => import("@/features/projects/ProgressTab"),
                  (m) => m.ProgressTab,
                ),
              },
              {
                path: "retention",
                lazy: lazyPage(
                  () => import("@/features/projects/RetentionTab"),
                  (m) => m.RetentionTab,
                ),
              },
            ],
          },
          {
            path: "expenses",
            lazy: lazyPage(
              () => import("@/features/expenses/ExpensesPage"),
              (m) => m.ExpensesPage,
            ),
          },
          {
            path: "expenses/new",
            lazy: lazyPage(
              () => import("@/features/expenses/ExpenseFormPage"),
              (m) => m.ExpenseFormPage,
            ),
          },
          {
            path: "expenses/:expenseId",
            lazy: lazyPage(
              () => import("@/features/expenses/ExpenseFormPage"),
              (m) => m.ExpenseFormPage,
            ),
          },
          {
            path: "reports",
            lazy: lazyPage(
              () => import("@/features/reports/ReportsPage"),
              (m) => m.ReportsPage,
            ),
          },
          {
            path: "account",
            lazy: lazyPage(
              () => import("@/features/account/AccountPage"),
              (m) => m.AccountPage,
            ),
          },
          {
            path: "exports",
            lazy: lazyPage(
              () => import("@/features/exports/ExportsPage"),
              (m) => m.ExportsPage,
            ),
          },
          {
            path: "tds-certificates",
            lazy: lazyPage(
              () => import("@/features/tds/TdsCertificatesPage"),
              (m) => m.TdsCertificatesPage,
            ),
          },
          {
            path: "settings",
            lazy: lazyPage(
              () => import("@/features/settings/SettingsLayout"),
              (m) => m.SettingsLayout,
            ),
            children: [
              { index: true, element: <Navigate to="company" replace /> },
              {
                path: "company",
                lazy: lazyPage(
                  () => import("@/features/settings/CompanyPage"),
                  (m) => m.CompanyPage,
                ),
              },
              {
                path: "members",
                lazy: lazyPage(
                  () => import("@/features/settings/MembersPage"),
                  (m) => m.MembersPage,
                ),
              },
              {
                path: "gst-registrations",
                lazy: lazyPage(
                  () => import("@/features/settings/GstRegistrationsPage"),
                  (m) => m.GstRegistrationsPage,
                ),
              },
              {
                path: "series",
                lazy: lazyPage(
                  () => import("@/features/settings/SeriesPage"),
                  (m) => m.SeriesPage,
                ),
              },
              {
                path: "print",
                lazy: lazyPage(
                  () => import("@/features/settings/PrintSettingsPage"),
                  (m) => m.PrintSettingsPage,
                ),
              },
              {
                path: "activity",
                lazy: lazyPage(
                  () => import("@/features/settings/ActivityLogPage"),
                  (m) => m.ActivityLogPage,
                ),
              },
              {
                path: "tally",
                lazy: lazyPage(
                  () => import("@/features/settings/TallySettingsPage"),
                  (m) => m.TallySettingsPage,
                ),
              },
            ],
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
