import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { RegisterForm } from "@/features/auth/components/RegisterForm";
import { useAuthStore } from "@/features/auth/store/authStore";

export function RegisterPage() {
  const { isAuthenticated } = useAuthStore();
  const navigate = useNavigate();

  useEffect(() => {
    if (isAuthenticated) navigate("/dashboard", { replace: true });
  }, [isAuthenticated, navigate]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-brand-50 to-white flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <span className="text-5xl">⚡</span>
          <h1 className="mt-3 text-2xl font-bold text-gray-900">Create your ForgeAI account</h1>
          <p className="mt-1 text-sm text-gray-500">Start forging production-ready software</p>
        </div>
        <div className="card p-8">
          <RegisterForm />
        </div>
      </div>
    </div>
  );
}
