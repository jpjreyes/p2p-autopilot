"use client";

import { useCallback, useEffect, useState } from "react";
import { api, VERDICT_LABEL, type ReviewItem } from "@/lib/api";

const FILTERS: Record<string, string> = {
  needs_human: "Needs a human",
  proposed: "Proposed for payment",
  approved_for_payment: "Approved",
  rejected: "Rejected",
};

export default function ReviewPage() {
  const [status, setStatus] = useState("needs_human");
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(
    () => api<ReviewItem[]>(`/api/review?status=${status}`).then(setItems).catch((e) => setError(e.message)),
    [status],
  );
  useEffect(() => { load(); }, [load]);

  async function decide(item: ReviewItem, decision: "approve" | "reject") {
    setError("");
    try {
      await api(`/api/review/${item.item_id}`, { method: "POST", body: JSON.stringify({ decision }) });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Review queue</h1>
      <p className="max-w-3xl text-sm text-muted">
        The agent proposes; a person decides. Approving marks an invoice as approved for payment in the AP
        system. Nothing here moves money.
      </p>
      <div className="flex flex-wrap gap-2 text-sm">
        {Object.entries(FILTERS).map(([k, v]) => (
          <button key={k} onClick={() => setStatus(k)}
            className={`rounded-full border px-3 py-1 ${status === k ? "border-accent text-accent" : "border-line text-muted"}`}>
            {v}
          </button>
        ))}
      </div>
      {error && <p className="text-sm text-bad">{error}</p>}
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead className="bg-card text-left text-muted">
            <tr><th className="p-2">Document</th><th className="p-2">Verdict</th><th className="p-2 text-right">Proposed pay</th>
              <th className="p-2">Evidence</th><th className="p-2">Decision</th></tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.item_id} className="border-t border-line align-top">
                <td className="p-2 font-mono">{i.number}<span className="block text-xs text-muted">{i.run_id}</span></td>
                <td className="p-2">{VERDICT_LABEL[i.verdict] ?? i.verdict}</td>
                <td className="p-2 text-right font-mono">{i.payable ?? "—"}</td>
                <td className="p-2 text-xs text-muted">{i.evidence.join(" ")}</td>
                <td className="p-2">
                  {i.decided_at ? (
                    <span className="text-xs text-muted">{i.status.replaceAll("_", " ")} by {i.decided_by}</span>
                  ) : (
                    <span className="flex gap-2">
                      <button onClick={() => decide(i, "approve")} disabled={i.payable == null}
                        title={i.payable == null ? "No amount to approve: resolve with the supplier first" : ""}
                        className="rounded border border-ok px-2 py-0.5 text-ok disabled:opacity-40">Approve</button>
                      <button onClick={() => decide(i, "reject")}
                        className="rounded border border-bad px-2 py-0.5 text-bad">Reject</button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {items.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-muted">Nothing here.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
