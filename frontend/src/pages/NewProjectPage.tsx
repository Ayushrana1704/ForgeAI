import { Link } from "react-router-dom";
import { ProjectForm } from "@/features/projects/components/ProjectForm";

export function NewProjectPage() {
  return (
    <div className="max-w-2xl">
      {/* Breadcrumb */}
      <nav className="text-sm text-gray-500 mb-6">
        <Link to="/dashboard" className="hover:text-gray-700 transition-colors">
          Dashboard
        </Link>
        <span className="mx-2 text-gray-300">/</span>
        <span className="text-gray-900 font-medium">New project</span>
      </nav>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Create a new project</h1>
        <p className="mt-1 text-sm text-gray-500">
          Describe your software requirements and ForgeAI will build it for you.
        </p>
      </div>

      <div className="card p-6">
        <ProjectForm />
      </div>
    </div>
  );
}
