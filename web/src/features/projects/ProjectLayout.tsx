import { ArrowLeft } from "lucide-react";
import { Link, NavLink, Outlet, useParams } from "react-router";

import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/StatusBadge";
import { projectStatus } from "@/features/projects/status";

import { useProject, useProjectOutlet } from "./api";
import { ProjectForm } from "./ProjectForm";

const TABS = [
  { to: "", label: "Details", end: true },
  { to: "boq", label: "BOQ", end: false },
  { to: "progress", label: "Progress", end: false },
  { to: "retention", label: "Retention", end: false },
] as const;

export function ProjectLayout() {
  const { projectId = "" } = useParams();
  const project = useProject(projectId);
  if (project.error) return <ErrorState error={project.error} />;
  if (!project.data) return <Skeleton className="h-96 w-full" />;
  const p = project.data;
  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to="/projects">
          <ArrowLeft aria-hidden /> Projects
        </Link>
      </Button>
      <PageHeader
        title={p.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{p.code}</span>·<span>{p.client_name}</span>
            <StatusBadge status={projectStatus(p.status)} />
          </span>
        }
      />
      <nav aria-label="Project" className="mb-6 flex gap-1 border-b">
        {TABS.map((t) => (
          <NavLink
            key={t.label}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              cn(
                "-mb-px border-b-2 px-3 py-2 text-sm",
                isActive
                  ? "border-primary font-medium"
                  : "text-muted-foreground hover:text-foreground border-transparent",
              )
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet context={{ project: p }} />
    </>
  );
}

export function ProjectDetailsTab() {
  const { project } = useProjectOutlet();
  return <ProjectForm project={project} />;
}

export function NewProjectPage() {
  return (
    <>
      <Button variant="ghost" size="sm" asChild className="mb-2 -ml-2">
        <Link to="/projects">
          <ArrowLeft aria-hidden /> Projects
        </Link>
      </Button>
      <PageHeader title="New project" />
      <ProjectForm />
    </>
  );
}
