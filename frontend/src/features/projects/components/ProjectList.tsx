import { Link } from "react-router-dom";
import { Spinner } from "@/shared/components/ui/Spinner";
import { Button } from "@/shared/components/ui/Button";
import { ProjectCard } from "./ProjectCard";
import { useProjects } from "../hooks/useProjects";

export function ProjectList() {
  const { data, loading, error, refetch } = useProjects();

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Spinner size="lg" className="text-brand-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-16">
        <p className="text-red-600 mb-4">{error}</p>
        <Button variant="secondary" onClick={refetch}>
          Retry
        </Button>
      </div>
    );
  }

  const projects = data?.items ?? [];

  if (projects.length === 0) {
    return (
      <div className="text-center py-24 card">
        <p className="text-4xl mb-4">⚡</p>
        <h3 className="text-lg font-semibold text-gray-900 mb-2">No projects yet</h3>
        <p className="text-gray-500 mb-6 text-sm">
          Describe your software idea and let ForgeAI build it.
        </p>
        <Link to="/projects/new">
          <Button>Create your first project</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}
