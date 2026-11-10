"use client";

import { PayPalButtons, PayPalScriptProvider } from "@paypal/react-paypal-js";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Area, AreaChart, Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import RainGauge from "@/components/RainGauge";
import Rain from "@/components/Rain";
import { api, fmtWindow, inr, pct, type Config, type Policy } from "@/lib/api";

const BADGE: Record<string, string> = {
  QUOTED: "bg-mist text-ink",
  ACTIVE: "bg-rain text-ink",
  TRIGGERED: "bg-marigold text-ink",
  PAID: "bg-leaf text-white",
  EXPIRED: "bg-slate text-white",
  FLAGGED: "bg-alert text-white",
};
const LABEL: Record<string, string> = {
  QUOTED: "Awaiting payment", ACTIVE: "Cover active", TRIGGERED: "Payout sending",
  PAID: "Paid out", EXPIRED: "Closed: no payout", FLAGGED: "Under review",
};

export default function PolicyView() {
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<Policy | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const checking = useRef(false);

  const load = useCallback(() => api<Policy>(`/policies/${id}`).then(setP).catch((e: Error) => setError(e.message)), [id]);

  useEffect(() => {
    load();
    api<Config>("/config").then(setCfg).catch(() => {});
  }, [load]);

  // Poll fast while the replay runs, slowly otherwise
  const replaying = p?.status === "ACTIVE" && p.live?.started && !p.live.finished;
  useEffect(() => {
    if (!p || ["PAID", "EXPIRED"].includes(p.status)) return;
    const t = setInterval(load, replaying ? 700 : 5000);
    return () => clearInterval(t);
  }, [p, replaying, load]);

  // When the demo replay ends, ask the Trigger Checker right away
  useEffect(() => {
    if (p?.status === "ACTIVE" && p.demo && p.live?.finished && !checking.current) {
      checking.current = true;
      api(`/policies/${id}/check`, {}).then(load).finally(() => (checking.current = false));
    }
  }, [p, id, load]);

  if (error) return <p className="m-10 rounded-xl bg-alert/10 p-4 text-alert">{error}</p>;
  if (!p) return <div className="p-10 text-center text-slate">Loading policy…</div>;

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const createOrder = () => api<{ id: string }>(`/policies/${id}/order`, {}).then((o) => o.id);
  const capture = (orderId: string) => api<Policy>(`/policies/${id}/capture`, { order_id: orderId }).then(setP);

  return (
    <div className="w-full space-y-6 px-6 py-10 lg:px-12 2xl:px-20">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-sm text-slate">Policy #{p.id}{p.demo ? " · Demo" : ""}</p>
          <h1 className="font-display text-4xl font-semibold">{p.event_name}</h1>
          <p className="text-slate">{p.venue} · {fmtWindow(p.start_time, p.end_time)}</p>
        </div>
        <span className={`rounded-full px-4 py-1.5 text-sm font-semibold ${BADGE[p.status]}`}>{LABEL[p.status]}</span>
      </div>

      <div className="rounded-2xl border-l-4 border-marigold bg-white p-5 shadow-sm">
        <p className="text-xs uppercase tracking-widest text-slate">The rule</p>
        <p className="mt-1 text-lg">
          If <b>{p.threshold_mm} mm or more</b> rain falls at {p.venue} during your event, we pay{" "}
          <b>{inr(p.payout_amount)}</b> to <b>{p.paypal_email}</b> automatically. No claim needed.
        </p>
      </div>

      {p.status === "QUOTED" && (
        <section className="grid gap-6 md:grid-cols-[1fr_1fr]">
          <div className="space-y-3 rounded-3xl bg-ink p-7 text-mist">
            <p className="text-xs uppercase tracking-widest text-mist/60">Your premium</p>
            <p className="font-display text-5xl font-semibold text-marigold">{inr(p.premium)}</p>
            <p className="text-sm text-mist/70">
              Charged as ${p.premium_usd.toFixed(2)} USD in the PayPal Sandbox. AI risk estimate: {pct(p.probability)}.
            </p>
            <ul className="space-y-1 pt-2 text-sm text-mist/80">
              <li>✓ Cover becomes active the moment PayPal confirms</li>
              <li>✓ Certificate issued instantly</li>
              <li>✓ Payout {inr(p.payout_amount)} if the rule is met</li>
            </ul>
          </div>
          <div className="rounded-3xl bg-white p-7 shadow-sm ring-1 ring-ink/5">
            <p className="mb-4 font-semibold">Pay with PayPal</p>
            {!cfg ? (
              <div className="h-12 animate-pulse rounded-full bg-mist" />
            ) : cfg.paypal_client_id ? (
              <PayPalScriptProvider options={{ clientId: cfg.paypal_client_id, currency: "USD", intent: "capture" }}>
                <PayPalButtons
                  style={{ layout: "vertical", shape: "pill", label: "pay" }}
                  createOrder={createOrder}
                  onApprove={(data) => capture(data.orderID).catch((e: Error) => setError(e.message))}
                  onError={(e) => setError(String(e))}
                />
              </PayPalScriptProvider>
            ) : (
              <>
                <button disabled={busy} onClick={() => act(async () => capture(await createOrder()))}
                  className="w-full rounded-full bg-[#ffc439] py-3.5 text-lg font-bold text-[#003087] hover:brightness-95 disabled:opacity-50">
                  {busy ? "Processing…" : <>Pay with <i>PayPal</i></>}
                </button>
                <p className="mt-3 text-xs text-slate">
                  Mock mode: no PayPal keys configured on the backend. Add Sandbox keys to <code>backend/.env</code> for real Sandbox checkout.
                </p>
              </>
            )}
          </div>
        </section>
      )}

      {p.status === "ACTIVE" && <LiveSection p={p} busy={busy} onStart={() => act(() => api(`/policies/${id}/demo/start`, {}))} />}

      {["TRIGGERED", "PAID", "EXPIRED", "FLAGGED"].includes(p.status) && <ResultSection p={p} />}

      {p.status !== "QUOTED" && (
        <section className="grid gap-4 md:grid-cols-2">
          <a href={`/api/policies/${p.id}/certificate`} target="_blank"
            className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-ink/5 hover:ring-ink/20">
            <p className="font-semibold">📄 Policy certificate</p>
            <p className="text-sm text-slate">Open, print or save as PDF</p>
          </a>
          <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-ink/5">
            <p className="mb-2 font-semibold">PayPal activity</p>
            <ul className="space-y-1 text-sm">
              {p.payments.map((x, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>{x.type === "PREMIUM" ? "Premium received" : x.type === "PAYOUT" ? "Payout sent" : x.type}</span>
                  <span className="text-right text-slate">{inr(x.type === "PREMIUM" ? p.premium : x.type === "PAYOUT" ? p.payout_amount : x.amount * (cfg?.inr_per_usd ?? 88))} · {x.status}<br /><code className="text-xs">{x.paypal_id}</code></span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {error && <p role="alert" className="rounded-xl bg-alert/10 p-3 text-sm text-alert">{error}</p>}
    </div>
  );
}

function LiveSection({ p, busy, onStart }: { p: Policy; busy: boolean; onStart: () => void }) {
  const live = p.live!;
  return (
    <section className="relative overflow-hidden rounded-3xl bg-ink p-7 text-mist">
      {live.started && !live.finished && live.rain_so_far > 0 && <Rain drops={40} />}
      <div className="relative grid gap-8 md:grid-cols-[auto_1fr]">
        <RainGauge mm={live.rain_so_far} threshold={p.threshold_mm} />
        <div className="space-y-4">
          {live.mode === "demo" && !live.started && (
            <div className="space-y-3">
              <p className="text-mist/80">
                Your cover is active.{" "}
                {live.scenario === "live" ? (
                  <>In demo mode the event plays the <b>live weather</b> at this venue for{" "}
                    {live.replay_date ? new Date(live.replay_date).toDateString() : "today"}, sped up to about a minute. Hours that
                    haven&apos;t happened yet use the latest forecast.</>
                ) : (
                  <>In demo mode the event replays <b>real measured rainfall</b> from{" "}
                    {new Date(live.replay_date ?? "2023-11-15").toDateString()} at this venue, sped up to about a minute.</>
                )}
              </p>
              <button onClick={onStart} disabled={busy}
                className="rounded-full bg-marigold px-6 py-3 font-semibold text-ink hover:bg-marigold-deep disabled:opacity-50">
                ▶ Start the event
              </button>
            </div>
          )}
          {live.mode === "live" && !live.started && (
            <p className="text-mist/80">Your cover is active. Live tracking starts when the event begins
              {live.starts_in_s ? ` (in ${Math.ceil(live.starts_in_s / 3600)} h)` : ""}.</p>
          )}
          {live.started && (
            <>
              <div className="flex items-center justify-between text-sm text-mist/70">
                <span>
                  {live.mode === "demo" ? (live.scenario === "live" ? `📡 Live weather, ${live.replay_date}` : `Replaying ${live.replay_date}`) : "Live"}
                  {" "}· event clock <b className="text-mist">{live.clock ?? "-"}</b>
                  {live.series.at(-1)?.forecast && <span className="ml-2 rounded bg-marigold/20 px-1.5 text-xs text-marigold">forecast hour</span>}
                </span>
                {live.finished && <span className="animate-pulse text-marigold">Event over: checking two weather sources…</span>}
              </div>
              {live.progress !== undefined && (
                <div className="h-1.5 rounded-full bg-ink-3"><div className="h-full rounded-full bg-rain transition-all" style={{ width: `${live.progress * 100}%` }} /></div>
              )}
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={live.series} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
                    <XAxis dataKey="time" tick={{ fill: "#e8f1f4aa", fontSize: 11 }} />
                    <YAxis domain={[0, Math.ceil(Math.max(p.threshold_mm * 1.5, live.rain_so_far + 2) / 5) * 5]} tick={{ fill: "#e8f1f4aa", fontSize: 11 }} />
                    <Tooltip formatter={(v) => [`${v} mm`, "Total so far"]} contentStyle={{ background: "#12303f", border: 0, borderRadius: 8 }} labelStyle={{ color: "#e8f1f4" }} />
                    <ReferenceLine y={p.threshold_mm} stroke="#f2a93b" strokeDasharray="5 3" label={{ value: "payout line", fill: "#f2a93b", fontSize: 11, position: "insideTopLeft" }} />
                    <Area type="monotone" dataKey="cumulative" stroke="#5cc2e6" fill="#5cc2e655" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function ResultSection({ p }: { p: Policy }) {
  const d = p.decision;
  const paid = p.status === "PAID" || p.status === "TRIGGERED";
  const sources = d ? Object.entries(d.totals).map(([name, mm]) => ({ name, mm })) : [];
  return (
    <section className={`relative overflow-hidden rounded-3xl p-8 ${paid ? "bg-ink text-mist" : p.status === "FLAGGED" ? "bg-alert/10" : "bg-mist"}`}>
      {paid && <Rain drops={30} />}
      <div className="relative grid gap-8 md:grid-cols-[1.2fr_1fr]">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-widest opacity-60">Result</p>
          <h2 className="font-display text-4xl font-semibold">
            {paid ? <>Trigger met: <span className="text-marigold">{inr(p.payout_amount)}</span> {p.status === "PAID" ? "sent" : "sending"}</>
              : p.status === "FLAGGED" ? "A person is double-checking" : "Good weather! No payout needed"}
          </h2>
          {p.summary && <p className="text-lg leading-relaxed opacity-90">{p.summary}</p>}
          {d && <p className="text-sm opacity-60">{d.reason}. Checked {new Date(d.checked_at).toLocaleString("en-IN")}.</p>}
        </div>
        {d && (
          <div>
            <p className="mb-2 text-sm font-semibold">Data proof: rain during the event window</p>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={sources} margin={{ top: 16, right: 8, left: -20, bottom: 0 }}>
                  <XAxis dataKey="name" tick={{ fill: paid ? "#e8f1f4" : "#0b1e2a", fontSize: 12 }} />
                  <YAxis tick={{ fill: paid ? "#e8f1f4aa" : "#5b7380", fontSize: 11 }} domain={[0, Math.ceil((Math.max(d.threshold_mm, ...sources.map((x) => x.mm)) * 1.2) / 5) * 5]} />
                  <Tooltip formatter={(v) => [`${v} mm`, "Measured"]} />
                  <ReferenceLine y={d.threshold_mm} stroke="#f2a93b" strokeDasharray="5 3" label={{ value: `${d.threshold_mm} mm rule`, fill: "#d88412", fontSize: 11, position: "insideTopRight" }} />
                  <Bar dataKey="mm" fill="#5cc2e6" radius={[6, 6, 0, 0]} label={{ position: "top", fill: paid ? "#e8f1f4" : "#0b1e2a", fontSize: 12, formatter: (v: unknown) => `${v} mm` }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
