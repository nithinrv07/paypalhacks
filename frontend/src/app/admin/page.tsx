"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api, inr, pct, type Decision } from "@/lib/api";

type Row = {
  id: number; status: string; threshold_mm: number; payout_amount: number; premium: number; probability: number;
  demo: number; payout_mode?: string; paid_fraction?: number; event_name: string; venue: string; start_time: string; user_name: string; decision: Decision | null;
};
type ModelRes = { brier: number; auc: number; calibration: { predicted: number; actual: number; n: number }[] };
type Admin = {
  policies: Row[];
  totals: { premiums_in_inr: number; payouts_out_inr: number; expected_payouts_inr: number; active: number; flagged: number };
  model: { chosen?: string; models?: Record<string, ModelRes>; climatology_brier?: number; test_years?: number[]; rows_train?: number; rows_test?: number };
  mock_paypal: boolean;
};

export default function AdminPage() {
  const [d, setD] = useState<Admin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api<Admin>("/admin").then(setD).catch((e: Error) => setError(e.message)), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const resolve = (id: number, decision: "pay" | "reject") =>
    api(`/admin/policies/${id}/resolve`, { decision }).then(load).catch((e: Error) => setError(e.message));

  if (!d) return <p className="p-10 text-center text-slate">{error ?? "Loading…"}</p>;
  const chosen = d.model.chosen ? d.model.models?.[d.model.chosen] : undefined;

  return (
    <div className="w-full space-y-8 px-6 py-10 lg:px-12 2xl:px-20">
      <div className="flex items-end justify-between">
        <h1 className="font-display text-4xl font-semibold">Admin</h1>
        <span className="text-sm text-slate">PayPal: {d.mock_paypal ? "mock mode" : "Sandbox"}</span>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {[
          ["Premiums in", inr(d.totals.premiums_in_inr)],
          ["Payouts out", inr(d.totals.payouts_out_inr)],
          ["Expected payouts (model)", inr(d.totals.expected_payouts_inr)],
          ["Active policies", String(d.totals.active)],
          ["Flagged for review", String(d.totals.flagged)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-ink/5">
            <p className="text-xs text-slate">{k}</p>
            <p className="font-display text-2xl font-semibold">{v}</p>
          </div>
        ))}
      </div>

      {chosen && (
        <section className="grid gap-6 rounded-3xl bg-ink p-7 text-mist md:grid-cols-[1fr_1.2fr]">
          <div className="space-y-3">
            <h2 className="font-display text-2xl font-semibold">Pricing model accuracy</h2>
            <p className="text-sm text-mist/70">Tested on held-out years {d.model.test_years?.join(", ")} ({d.model.rows_test?.toLocaleString()} event windows).</p>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-mist/60"><th className="py-1 font-normal">Model</th><th className="font-normal">Brier ↓</th><th className="font-normal">AUC ↑</th></tr></thead>
              <tbody>
                {Object.entries(d.model.models ?? {}).map(([name, m]) => (
                  <tr key={name} className={name === d.model.chosen ? "text-marigold" : ""}>
                    <td className="py-1">{name.replace("_", " ")}{name === d.model.chosen ? " ✓" : ""}</td><td>{m.brier.toFixed(4)}</td><td>{m.auc.toFixed(3)}</td>
                  </tr>
                ))}
                <tr className="text-mist/60"><td className="py-1">climatology only</td><td>{d.model.climatology_brier?.toFixed(4)}</td><td>-</td></tr>
              </tbody>
            </table>
            <p className="text-xs text-mist/60">A good pricing model says 12% only when it really rains about 12% of the time. Points on the diagonal = well calibrated.</p>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart margin={{ top: 8, right: 16, left: -8, bottom: 8 }}>
                <CartesianGrid stroke="#1d4557" />
                <XAxis type="number" dataKey="predicted" name="Predicted" domain={[0, 0.3]} ticks={[0, 0.1, 0.2, 0.3]} tickFormatter={(v) => pct(v)} tick={{ fill: "#e8f1f4aa", fontSize: 11 }} />
                <YAxis type="number" dataKey="actual" name="Actual" domain={[0, 0.3]} ticks={[0, 0.1, 0.2, 0.3]} tickFormatter={(v) => pct(v)} tick={{ fill: "#e8f1f4aa", fontSize: 11 }} />
                <ZAxis type="number" dataKey="n" range={[80, 400]} />
                <Tooltip formatter={(v, n) => (n === "n" ? v : pct(Number(v)))} contentStyle={{ background: "#12303f", border: 0 }} />
                <Scatter data={[{ predicted: 0, actual: 0 }, { predicted: 0.3, actual: 0.3 }]} line={{ stroke: "#5b7380", strokeDasharray: "4 4" }} shape={() => <g />} />
                <Scatter data={chosen.calibration} fill="#f2a93b" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      <section className="overflow-x-auto rounded-2xl bg-white shadow-sm ring-1 ring-ink/5">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-ink/10 text-slate">
            <tr>{["#", "Event", "Organiser", "Rule", "Premium", "Risk", "Measured", "Status", ""].map((h) => <th key={h} className="p-3 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody>
            {d.policies.map((r) => (
              <tr key={r.id} className="border-b border-ink/5 last:border-0">
                <td className="p-3"><Link className="underline" href={`/policy/${r.id}`}>{r.id}</Link></td>
                <td className="p-3">{r.event_name}{r.demo ? <span className="ml-1 rounded bg-marigold/20 px-1 text-xs">demo</span> : null}<br /><span className="text-xs text-slate">{r.venue}</span></td>
                <td className="p-3">{r.user_name}</td>
                <td className="p-3">{r.payout_mode === "graduated" ? `graduated 5/10/20 mm → ${inr(r.payout_amount)}` : `${r.threshold_mm} mm → ${inr(r.payout_amount)}`}</td>
                <td className="p-3">{inr(r.premium)}</td>
                <td className="p-3">{pct(r.probability)}</td>
                <td className="p-3 text-xs">{r.decision ? Object.entries(r.decision.totals).map(([k, v]) => <div key={k}>{k}: {v} mm</div>) : "-"}</td>
                <td className="p-3 font-medium">{r.status}{r.paid_fraction ? <span className="block text-xs text-slate">paid {inr(r.paid_fraction * r.payout_amount)}</span> : null}</td>
                <td className="p-3">
                  {r.status === "FLAGGED" && (
                    <div className="flex gap-2">
                      <button onClick={() => resolve(r.id, "pay")} className="rounded-full bg-leaf px-3 py-1 text-xs text-white">Pay</button>
                      <button onClick={() => resolve(r.id, "reject")} className="rounded-full bg-slate px-3 py-1 text-xs text-white">Reject</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {!d.policies.length && <tr><td colSpan={9} className="p-6 text-center text-slate">No policies yet.</td></tr>}
          </tbody>
        </table>
      </section>
      {error && <p className="text-sm text-alert">{error}</p>}
    </div>
  );
}
