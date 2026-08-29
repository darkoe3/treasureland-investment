"use client";

import { Eye, EyeOff, LockKeyhole } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { clientRequest } from "../lib/client-api";

function safeNext(value) {
  if (!value || !value.startsWith("/dashboard") || value.startsWith("//")) {
    return "/dashboard";
  }
  return value;
}

export default function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (!email.trim() || !password) {
      setError("Enter your email address and password.");
      return;
    }
    setLoading(true);
    try {
      await clientRequest("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.replace(safeNext(searchParams.get("next")));
      router.refresh();
    } catch (err) {
      setError(err.status === 400 || err.status === 401 ? "Invalid email or password." : "Unable to reach the secure login service.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="login-panel" onSubmit={submit}>
      <div className="login-lock" aria-hidden="true">
        <LockKeyhole size={22} />
      </div>
      <div>
        <p className="eyebrow">Secure staff access</p>
        <h1>Treasureland Investment Limited</h1>
        <p className="login-copy">Sign in with your administrator-issued account to continue.</p>
      </div>

      <div className="field-group">
        <label htmlFor="email">Email address</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={loading}
          required
        />
      </div>

      <div className="field-group">
        <label htmlFor="password">Password</label>
        <div className="password-field">
          <input
            id="password"
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={loading}
            required
          />
          <button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? "Hide password" : "Show password"}>
            {showPassword ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
          </button>
        </div>
      </div>

      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}

      <button className="primary-button full" type="submit" disabled={loading}>
        {loading ? "Signing in..." : "Sign in securely"}
      </button>
    </form>
  );
}
