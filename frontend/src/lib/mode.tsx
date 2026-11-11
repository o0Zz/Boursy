import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Mode, PortfolioOverview } from "../api/types";

interface ModeContext {
  mode: Mode;
  setMode: (m: Mode) => void;
  portfolios: PortfolioOverview[];
  current: PortfolioOverview | undefined;
  loading: boolean;
}

const Ctx = createContext<ModeContext | null>(null);
const KEY = "boursy.mode";

function stored(): Mode | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "paper" || v === "live" ? v : null;
  } catch {
    return null;
  }
}

export function usePortfolios() {
  return useQuery({ queryKey: ["portfolios"], queryFn: () => api<PortfolioOverview[]>("/portfolios"), refetchInterval: 60_000 });
}

export function ModeProvider({ children }: { children: ReactNode }) {
  const q = usePortfolios();
  const [mode, setModeState] = useState<Mode>(stored() ?? "paper");
  const portfolios = q.data ?? [];

  useEffect(() => {
    if (portfolios.length && !portfolios.some((p) => p.mode === mode)) setModeState(portfolios[0].mode);
  }, [portfolios, mode]);

  const setMode = (m: Mode) => {
    setModeState(m);
    try {
      localStorage.setItem(KEY, m);
    } catch {
      /* private mode */
    }
  };

  return (
    <Ctx.Provider value={{ mode, setMode, portfolios, current: portfolios.find((p) => p.mode === mode), loading: q.isPending }}>
      {children}
    </Ctx.Provider>
  );
}

export function useMode(): ModeContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useMode outside ModeProvider");
  return ctx;
}
