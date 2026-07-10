import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Input } from "@/shared/components/ui/Input";
import { Button } from "@/shared/components/ui/Button";
import { useRegister } from "../hooks/useRegister";

export function RegisterForm() {
  const { register, loading, error } = useRegister();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    await register({ email, password, full_name: fullName || undefined });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      <Input
        label="Full name"
        type="text"
        autoComplete="name"
        value={fullName}
        onChange={(e) => setFullName(e.target.value)}
        placeholder="Jane Smith"
      />

      <Input
        label="Email address"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@company.com"
      />

      <Input
        label="Password"
        type="password"
        autoComplete="new-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Min. 8 characters with a digit"
        hint="Must be at least 8 characters and include a number."
      />

      {error && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {error}
        </p>
      )}

      <Button type="submit" fullWidth loading={loading}>
        Create account
      </Button>

      <p className="text-sm text-center text-gray-600">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700">
          Sign in
        </Link>
      </p>
    </form>
  );
}
