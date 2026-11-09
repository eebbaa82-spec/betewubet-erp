import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { api, url, User } from "./api";
import Configure from "./pages/Configure";
import CutList from "./pages/CutList";
import Dispatch, { DeliveryNote } from "./pages/Dispatch";
import Inventory from "./pages/Inventory";
import Login from "./pages/Login";
import Maintenance from "./pages/Maintenance";
import Purchasing, { PurchaseOrderDetail } from "./pages/Purchasing";
import Finance from "./pages/Finance";
import InvoiceView from "./pages/InvoiceView";
import Quality from "./pages/Quality";
import QuoteDetail from "./pages/QuoteDetail";
import Quotes from "./pages/Quotes";
import Station from "./pages/Station";
import { WorkOrderDetail, WorkOrders } from "./pages/WorkOrders";

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
            <NavLink to="/work-orders">Work orders</NavLink>
            <NavLink to="/inventory">Inventory</NavLink>
            <NavLink to="/purchasing">Purchasing</NavLink>
            <NavLink to="/station">Station</NavLink>
            <NavLink to="/quality">Quality</NavLink>
            <NavLink to="/dispatch">Dispatch</NavLink>
            <NavLink to="/maintenance">Maintenance</NavLink>
            <NavLink to="/finance">Finance</NavLink>
            {user.is_staff && <a href={url("/admin/")}>Back office</a>}
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
          <Route path="/work-orders" element={<WorkOrders />} />
          <Route path="/work-orders/:id" element={<WorkOrderDetail />} />
          <Route path="/work-orders/:id/cut-list" element={<CutList />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/purchasing" element={<Purchasing />} />
          <Route path="/purchasing/:id" element={<PurchaseOrderDetail />} />
          <Route path="/quality" element={<Quality />} />
          <Route path="/dispatch" element={<Dispatch />} />
          <Route path="/dispatch/:id" element={<DeliveryNote />} />
          <Route path="/finance" element={<Finance />} />
          <Route path="/finance/invoices/:id" element={<InvoiceView />} />
          <Route path="/maintenance" element={<Maintenance />} />
          <Route path="/station" element={<Station />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </UserContext.Provider>
  );
}
