import { useState, type FormEvent } from "react";
import { Input } from "@/shared/components/ui/Input";
import { Button } from "@/shared/components/ui/Button";
import { useCreateProject } from "../hooks/useCreateProject";

export function ProjectForm() {
  const { create, loading, error } = useCreateProject();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [requirements, setRequirements] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await create({
      name,
      description: description || undefined,
      requirements,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      <Input
        label="Project name"
        type="text"
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="My SaaS App"
      />

      <div>
        <label className="form-label">Description (optional)</label>
        <textarea
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 transition-colors"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="A brief one-liner about the project"
        />
      </div>

      <div>
        <label className="form-label">
          Requirements{" "}
          <span className="text-gray-400 font-normal">(natural language — be specific)</span>
        </label>
        <textarea
          className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 transition-colors resize-y"
          rows={8}
          required
          value={requirements}
          onChange={(e) => setRequirements(e.target.value)}
          placeholder={`Example:\nBuild a REST API for a multi-tenant task management app.\n- Users can register, log in, and manage their own tasks (CRUD).\n- Tasks have title, description, priority (low/medium/high), and due date.\n- Tech stack: FastAPI, PostgreSQL, SQLAlchemy, Alembic, Pydantic v2.\n- Include JWT auth, pagination, and full test coverage.`}
        />
        <p className="text-xs text-gray-500 mt-1">
          {requirements.length} characters — aim for at least 100.
        </p>
      </div>

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <div className="flex gap-3">
        <Button type="submit" loading={loading} disabled={requirements.length < 10}>
          {loading ? "Saving…" : "Create project"}
        </Button>
      </div>
    </form>
  );
}
