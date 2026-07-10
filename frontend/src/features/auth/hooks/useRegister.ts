import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { authApi } from "../api/authApi";
import { useAuthStore } from "../store/authStore";
import { extractErrorMessage } from "@/shared/lib/axios";

interface RegisterForm {
  email: string;
  password: string;
  full_name?: string;
}

export function useRegister() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { setSession } = useAuthStore();
  const navigate = useNavigate();

  const register = async (form: RegisterForm) => {
    setLoading(true);
    setError(null);
    try {
      await authApi.register(form);
      // Auto-login after successful registration
      const tokens = await authApi.login({ email: form.email, password: form.password });
      useAuthStore.setState({ accessToken: tokens.access_token });
      const user = await authApi.me();
      setSession(user, tokens.access_token, tokens.refresh_token);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return { register, loading, error };
}
