import type { ComponentType } from "react";
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

export const routes: RouteObject[] = [
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
            path: "settings/gst-registrations",
            lazy: lazyPage(
              () => import("@/features/settings/GstRegistrationsPage"),
              (m) => m.GstRegistrationsPage,
            ),
          },
          {
            path: "settings/company",
            lazy: lazyPage(
              () => import("@/features/settings/CompanyPage"),
              (m) => m.CompanyPage,
            ),
          },
          {
            path: "settings/members",
            lazy: lazyPage(
              () => import("@/features/settings/MembersPage"),
              (m) => m.MembersPage,
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
            path: "settings/series",
            lazy: lazyPage(
              () => import("@/features/settings/SeriesPage"),
              (m) => m.SeriesPage,
            ),
          },
          { path: "*", element: <NotFoundPage /> },
        ],
      },
    ],
  },
];
