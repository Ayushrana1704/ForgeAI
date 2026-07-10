import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { authApi } from "../api/authApi";
import { useAuthStore } from "../store/authStore";
import { extractErrorMessage } from "@/shared/lib/axios";

interface LoginForm {
  email: string;
  password: string;
}

export function useLogin() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { setSession } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? "/dashboard";

  const login = async (form: LoginForm) => {
    setLoading(true);
    setError(null);
    try {
      const tokens = await authApi.login(form);
      // Fetch the full user profile using the new token
      // Temporarily set the token so the /me call is authorised
      useAuthStore.setState({ accessToken: tokens.access_token });
      const user = await authApi.me();
      setSession(user, tokens.access_token, tokens.refresh_token);
      navigate(from, { replace: true });
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return { login, loading, error };
}
