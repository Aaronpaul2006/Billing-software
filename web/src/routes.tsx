import type { ComponentType } from "react";
import type { RouteObject } from "react-router";

import { RequireAuth } from "@/auth/RequireAuth";
import { AppShell } from "@/layout/AppShell";
import { NotFoundPage, PlaceholderPage } from "@/pages/PlaceholderPage";

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
          { path: "payments", element: <PlaceholderPage title="Payments" /> },
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
            ],
          },
          { path: "expenses", element: <PlaceholderPage title="Expenses" /> },
          {
            path: "settings/gst-registrations",
            lazy: lazyPage(
              () => import("@/features/settings/GstRegistrationsPage"),
              (m) => m.GstRegistrationsPage,
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
