import { Link } from "react-router-dom";
import { Badge } from "@/shared/components/ui/Badge";
import { formatDate } from "@/shared/lib/utils";
import type { Project } from "@/shared/types";

interface ProjectCardProps {
  project: Project;
}

export function ProjectCard({ project }: ProjectCardProps) {
  return (
    <Link
      to={`/projects/${project.id}`}
      className="card p-5 hover:shadow-md transition-shadow duration-150 block group"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold text-gray-900 group-hover:text-brand-600 truncate transition-colors">
            {project.name}
          </h3>
          {project.description && (
            <p className="text-sm text-gray-500 mt-1 line-clamp-2">{project.description}</p>
          )}
        </div>
        <Badge label={project.status} variant="status" />
      </div>

      <p className="text-xs text-gray-400 mt-3 line-clamp-2">{project.requirements}</p>

      <div className="mt-4 flex items-center justify-between text-xs text-gray-400">
        <span>Created {formatDate(project.created_at)}</span>
        <span className="text-brand-500 font-medium group-hover:underline">View →</span>
      </div>
    </Link>
  );
}
