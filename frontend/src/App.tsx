import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { api, User } from "./api";
import Configure from "./pages/Configure";
import Login from "./pages/Login";
import QuoteDetail from "./pages/QuoteDetail";
import Quotes from "./pages/Quotes";

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext);

export default function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    api<{ user: User | null }>("/api/auth/me/")
      .then((r) => setUser(r.user))
      .catch(() => setUser(null));
  }, []);

  if (user === undefined) return <div className="boot">Loading…</div>;
  if (user === null) return <Login onSignedIn={setUser} />;

  const signOut = async () => {
    await api("/api/auth/logout/", { method: "POST" });
    setUser(null);
  };

  return (
    <UserContext.Provider value={user}>
      <header className="topbar">
        <div className="wrap topbar-inner">
          <span className="brand">Betewubet ERP</span>
          <nav>
            <NavLink to="/configure">Configure and quote</NavLink>
            <NavLink to="/quotes">Quotes and orders</NavLink>
            <a href="/admin/">Back office</a>
          </nav>
          <span className="who">
            {user.name}
            <button className="link" onClick={signOut}>Sign out</button>
          </span>
        </div>
      </header>
      <main className="wrap page">
        <Routes>
          <Route path="/" element={<Navigate to="/configure" replace />} />
          <Route path="/configure" element={<Configure />} />
          <Route path="/quotes" element={<Quotes />} />
          <Route path="/quotes/:id" element={<QuoteDetail />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </UserContext.Provider>
  );
}
