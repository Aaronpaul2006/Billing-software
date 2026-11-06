import { Fragment, lazy, Suspense } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { FullPageSpinner } from "@/components/FullPageSpinner";

import { useAuth } from "./context";

// The public home page: only visitors who are not signed in download it.
const HomePage = lazy(async () => ({ default: (await import("@/pages/HomePage")).HomePage }));

/**
 * Routes behind sign-in; a visitor who is not signed in sees the public home
 * page at "/" and the sign-in page everywhere else. OWNER / ADMIN without MFA must enrol first. People
 * at a client (role CLIENT) only have the client portal (`portal` routes),
 * and the business's own people never see it.
 */
export function RequireAuth({
  enrolment = false,
  portal = false,
}: {
  enrolment?: boolean;
  portal?: boolean;
}) {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") return <FullPageSpinner />;
  if (state.status === "signed_out") {
    if (location.pathname === "/" && !portal) {
      return (
        <Suspense fallback={<FullPageSpinner />}>
          <HomePage />
        </Suspense>
      );
    }
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  const isClient = state.session.role === "CLIENT";
  if (isClient && !portal) return <Navigate to="/portal" replace />;
  if (!isClient && portal) return <Navigate to="/" replace />;
  const mustEnrol = state.session.mfa_enrollment_required;
  if (mustEnrol && !enrolment) return <Navigate to="/mfa/setup" replace />;
  if (!mustEnrol && enrolment) return <Navigate to="/" replace />;
  // Keyed by the business: after switching company every page below is built
  // again and loads that company's data. Clearing the cache alone left pages
  // that stayed on screen showing the previous company's figures.
  return (
    <Fragment key={state.session.tenant_id}>
      <Outlet />
    </Fragment>
  );
}
