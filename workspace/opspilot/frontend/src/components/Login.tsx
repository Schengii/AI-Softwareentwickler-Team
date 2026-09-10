import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

export function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) throw new Error("Ungültige Anmeldedaten");
      const data = await response.json();
      localStorage.setItem("access_token", data.access_token);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ein Fehler ist aufgetreten");
    }
  };

  return (
    <main style={{ maxWidth: "400px", margin: "2rem auto", padding: "1rem" }}>
      <h1>Login</h1>
      {error && (
        <p id="login-error" role="alert" style={{ color: "#d32f2f", fontWeight: "bold" }}>
          {error}
        </p>
      )}
      <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
        <label htmlFor="username">Benutzername</label>
        <input
          id="username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          aria-describedby={error ? "login-error" : undefined}
        />
        <label htmlFor="password">Passwort</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          aria-describedby={error ? "login-error" : undefined}
        />
        <button type="submit">Anmelden</button>
      </form>
    </main>
  );
}
