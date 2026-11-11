import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { post } from "../api/client";
import { Button, Input } from "../components/ui";

export default function Login() {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await post<{ user: string }>("/auth/login", { password });
      qc.setQueryData(["me"], me);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-5 p-7">
        <div className="flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 shadow-lg shadow-emerald-500/20">
            <svg viewBox="0 0 32 32" className="h-6 w-6">
              <path d="M6 22l7-7 5 4 8-10" stroke="#022c22" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white">Boursy</h1>
            <p className="text-xs text-slate-500">PEA healthcare trading assistant</p>
          </div>
        </div>
        <label className="block">
          <span className="mb-1 flex items-center gap-1.5 text-xs font-medium text-slate-400">
            <Lock className="h-3.5 w-3.5" /> Password
          </span>
          <Input type="password" autoFocus autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="text-sm text-rose-400">{error}</p>}
        <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!password}>
          Sign in
        </Button>
      </form>
    </div>
  );
}
