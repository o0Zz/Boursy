import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  Briefcase,
  FlaskConical,
  Inbox,
  LayoutDashboard,
  LogOut,
  Menu,
  Settings,
  ShieldAlert,
  Telescope,
  X,
} from "lucide-react";
import { post } from "../api/client";
import type { Mode } from "../api/types";
import { useMode } from "../lib/mode";
import { cx } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/proposals", label: "Proposals", icon: Inbox },
  { to: "/positions", label: "Positions", icon: Briefcase },
  { to: "/watchlist", label: "Watchlist", icon: Telescope },
  { to: "/journal", label: "Journal", icon: BookOpen },
  { to: "/backtest", label: "Backtest", icon: FlaskConical },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/system", label: "System", icon: Activity },
];
const MOBILE_MAIN = NAV.slice(0, 4);

function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <div className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-emerald-400 to-teal-600 shadow-lg shadow-emerald-500/20">
        <svg viewBox="0 0 32 32" className="h-5 w-5">
          <path d="M6 22l7-7 5 4 8-10" stroke="#022c22" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-white">Boursy</div>
        <div className="text-[10px] text-slate-500">v{__APP_VERSION__}</div>
      </div>
    </div>
  );
}

function ModeSwitch() {
  const { mode, setMode, portfolios } = useMode();
  if (portfolios.length === 0) return null;
  const label: Record<Mode, string> = { paper: "Paper", live: "PEA live" };
  return (
    <div className="inline-flex rounded-lg bg-slate-900 p-0.5 ring-1 ring-inset ring-slate-800">
      {portfolios.map((p) => (
        <button
          key={p.mode}
          onClick={() => setMode(p.mode)}
          className={cx(
            "flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold transition-colors",
            mode === p.mode
              ? p.mode === "live"
                ? "bg-emerald-500 text-emerald-950"
                : "bg-amber-400 text-amber-950"
              : "text-slate-400 hover:text-white",
          )}
        >
          {p.mode === "live" && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
          {label[p.mode]}
        </button>
      ))}
    </div>
  );
}

function NavItem({ to, label, icon: Icon, end, badge, onClick }: (typeof NAV)[number] & { badge?: number; onClick?: () => void }) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        cx(
          "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
          isActive ? "bg-slate-800/80 text-white" : "text-slate-400 hover:bg-slate-900 hover:text-white",
        )
      }
    >
      <Icon className="h-[18px] w-[18px]" />
      <span className="flex-1">{label}</span>
      {!!badge && <span className="rounded-full bg-emerald-500 px-1.5 text-[11px] font-bold text-emerald-950">{badge}</span>}
    </NavLink>
  );
}

export default function Layout() {
  const qc = useQueryClient();
  const { current, portfolios } = useMode();
  const [more, setMore] = useState(false);
  const location = useLocation();
  const pending = portfolios.reduce((n, p) => n + p.pending_proposals, 0);
  const logout = async () => {
    await post("/auth/logout");
    qc.setQueryData(["me"], null);
  };

  return (
    <div className="min-h-screen lg:pl-60">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-slate-800/80 bg-slate-950/80 px-3 py-5 backdrop-blur lg:flex">
        <div className="px-2">
          <Logo />
        </div>
        <nav className="mt-8 flex-1 space-y-1">
          {NAV.map((n) => (
            <NavItem key={n.to} {...n} badge={n.to === "/proposals" ? pending : undefined} />
          ))}
        </nav>
        <button onClick={logout} className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-900 hover:text-white">
          <LogOut className="h-[18px] w-[18px]" /> Sign out
        </button>
      </aside>

      {/* Top bar */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
          <div className="lg:hidden">
            <Logo />
          </div>
          <div className="flex-1" />
          {current?.kill_switch && (
            <span className="hidden items-center gap-1 rounded-md bg-rose-500/15 px-2 py-1 text-xs font-semibold text-rose-300 ring-1 ring-inset ring-rose-500/30 sm:inline-flex">
              <ShieldAlert className="h-3.5 w-3.5" /> Kill switch
            </span>
          )}
          <ModeSwitch />
        </div>
      </header>

      <main key={location.pathname} className="mx-auto max-w-6xl px-4 pb-28 pt-5 sm:pt-7 lg:pb-12">
        <Outlet />
      </main>

      {/* Mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-800 bg-slate-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
        <div className="grid grid-cols-5">
          {MOBILE_MAIN.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => cx("relative flex flex-col items-center gap-0.5 py-2.5 text-[11px]", isActive ? "text-emerald-400" : "text-slate-500")}
            >
              <Icon className="h-5 w-5" />
              {label}
              {to === "/proposals" && pending > 0 && (
                <span className="absolute right-[calc(50%-18px)] top-1.5 rounded-full bg-emerald-500 px-1 text-[10px] font-bold leading-4 text-emerald-950">{pending}</span>
              )}
            </NavLink>
          ))}
          <button onClick={() => setMore(true)} className="flex flex-col items-center gap-0.5 py-2.5 text-[11px] text-slate-500">
            <Menu className="h-5 w-5" />
            More
          </button>
        </div>
      </nav>

      {more && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-950/70 backdrop-blur-sm" onClick={() => setMore(false)} />
          <div className="absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-slate-800 bg-slate-900 p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold text-white">Menu</span>
              <button onClick={() => setMore(false)} className="rounded-lg p-1 text-slate-400">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="space-y-1">
              {NAV.slice(4).map((n) => (
                <NavItem key={n.to} {...n} onClick={() => setMore(false)} />
              ))}
              <button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-400">
                <LogOut className="h-[18px] w-[18px]" /> Sign out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
