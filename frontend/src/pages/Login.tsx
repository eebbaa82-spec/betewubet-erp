import { FormEvent, useState } from "react";

import { api, ApiError, User } from "../api";
import Logo from "../Logo";

export default function Login({ onSignedIn }: { onSignedIn: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/me/"); // make sure the CSRF cookie is set
      const r = await api<{ user: User }>("/api/auth/login/", { method: "POST", body: { username, password } });
      onSignedIn(r.user);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Check the connection and try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login">
      <form className="panel stack" onSubmit={submit}>
        <div className="login-head">
          <Logo height={96} />
          <h1 className="brand">Betewubet</h1>
          <p className="muted">Home and Office Furniture Manufacturing PLC</p>
        </div>
        <label className="field">
          <span>Username</span>
          <input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label className="field">
          <span>Password</span>
          <input id="password" type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
