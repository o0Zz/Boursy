import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, UNAUTHORIZED_EVENT } from "./api/client";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import { ModeProvider } from "./lib/mode";
import Backtest from "./pages/Backtest";
import Journal from "./pages/Journal";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Positions from "./pages/Positions";
import Proposals from "./pages/Proposals";
import Settings from "./pages/Settings";
import StockDetail from "./pages/StockDetail";
import System from "./pages/System";
import Watchlist from "./pages/Watchlist";

export default function App() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ user: string }>("/auth/me"), retry: false });

  useEffect(() => {
    const onUnauthorized = () => qc.setQueryData(["me"], null);
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, [qc]);

  if (me.isPending) return <Loading />;
  if (!me.data) return <Login />;

  return (
    <ModeProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="proposals" element={<Proposals />} />
          <Route path="positions" element={<Positions />} />
          <Route path="watchlist" element={<Watchlist />} />
          <Route path="stocks/:symbol" element={<StockDetail />} />
          <Route path="journal" element={<Journal />} />
          <Route path="backtest" element={<Backtest />} />
          <Route path="settings" element={<Settings />} />
          <Route path="system" element={<System />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </ModeProvider>
  );
}
