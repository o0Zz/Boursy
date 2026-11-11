import { NavLink, Outlet } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { post } from "../api/client";

const links = [
  { to: "/", label: "Overview", end: true },
  { to: "/watchlist", label: "Watchlist" },
  { to: "/system", label: "System" },
];

export default function Layout() {
  const qc = useQueryClient();
  const logout = async () => {
    await post("/auth/logout");
    qc.setQueryData(["me"], null);
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <span className="text-lg font-semibold tracking-tight text-emerald-400">
            Boursy <span className="hidden text-xs font-normal text-slate-500 sm:inline">v{__APP_VERSION__}</span>
          </span>
          <span className="rounded bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-300">Simulation</span>
          <nav className="flex flex-1 gap-1 overflow-x-auto">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded px-3 py-1.5 text-sm ${
                    isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white"
                  }`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
          <button onClick={logout} className="text-sm text-slate-500 hover:text-slate-200">
            Logout
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
