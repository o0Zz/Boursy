import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { History, Inbox } from "lucide-react";
import { api } from "../api/client";
import type { Proposal } from "../api/types";
import ProposalCard from "../components/ProposalCard";
import { Card, Empty, ErrorBox, Loading, PageHeader, Tabs } from "../components/ui";
import { useMode } from "../lib/mode";

export default function Proposals() {
  const { mode } = useMode();
  const [params] = useSearchParams();
  const focus = Number(params.get("id")) || null;
  const [tab, setTab] = useState<"pending" | "history">("pending");
  const q = useQuery({
    queryKey: ["proposals", mode, tab],
    queryFn: () => api<Proposal[]>(`/proposals?mode=${mode}${tab === "pending" ? "&status=pending" : "&limit=200"}`),
  });
  const focused = useQuery({ queryKey: ["proposal", focus], queryFn: () => api<Proposal>(`/proposals/${focus}`), enabled: !!focus });

  useEffect(() => {
    if (focused.data && focused.data.status !== "pending") setTab("history");
  }, [focused.data]);
  useEffect(() => {
    if (focus && q.data) document.getElementById(`proposal-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus, q.data]);

  const rows = tab === "history" ? (q.data ?? []).filter((p) => p.status !== "pending") : (q.data ?? []);

  return (
    <div>
      <PageHeader
        title="Proposals"
        subtitle={mode === "live" ? "Place the order in your PEA, then record the fill here." : "Paper proposals fill automatically at the next session."}
        action={
          <Tabs
            value={tab}
            onChange={setTab}
            options={[
              { value: "pending", label: "Pending" },
              { value: "history", label: "History" },
            ]}
          />
        }
      />
      {q.error && <ErrorBox error={q.error} />}
      {q.isPending ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Card>
          <Empty icon={tab === "pending" ? <Inbox className="h-6 w-6" /> : <History className="h-6 w-6" />} title={tab === "pending" ? "No pending proposal" : "No history yet"}>
            {tab === "pending" && "The post-close run (17:45) checks every stock and proposes orders when the rules fire."}
          </Empty>
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map((p) => (
            <ProposalCard key={p.id} p={p} highlight={p.id === focus} compact={tab === "history" && p.id !== focus} />
          ))}
        </div>
      )}
    </div>
  );
}
