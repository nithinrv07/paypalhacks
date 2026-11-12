"use client";

import { PayPalButtons, PayPalScriptProvider } from "@paypal/react-paypal-js";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Area, AreaChart, Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import RainGauge from "@/components/RainGauge";
import Rain from "@/components/Rain";
import { api, fmtWindow, inr, pct, type Alert, type Config, type Policy } from "@/lib/api";

const BADGE: Record<string, string> = {
  QUOTED: "bg-mist text-ink",
  ACTIVE: "bg-rain text-ink",
  TRIGGERED: "bg-marigold text-ink",
  PAID: "bg-leaf text-white",
  EXPIRED: "bg-slate text-white",
  FLAGGED: "bg-alert text-white",
  CANCELLED: "bg-slate/20 text-ink",
};
const LABEL: Record<string, string> = {
  QUOTED: "Awaiting payment", ACTIVE: "Cover active", TRIGGERED: "Payout sending",
  PAID: "Paid out", EXPIRED: "Closed: no payout", FLAGGED: "Under review", CANCELLED: "Cancelled & refunded",
};

export default function PolicyView() {
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<Policy | null>(null);
  const [cfg, setCfg] = useState<Config | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const checking = useRef(false);
  const seen = useRef<Set<string> | null>(null);
  const notifyRef = useRef(false);
  const [notify, setNotify] = useState(false);
  const [toasts, setToasts] = useState<Alert[]>([]);

  const load = useCallback(
    () =>
      api<Policy>(`/policies/${id}`)
        .then((np) => {
          const alerts = np.live?.alerts ?? [];
          if (seen.current === null) {
            seen.current = new Set(alerts.map((a) => a.id)); // don't replay old alerts after a refresh
          } else {
            const fresh = alerts.filter((a) => !seen.current!.has(a.id));
            fresh.forEach((a) => {
              seen.current!.add(a.id);
              setTimeout(() => setToasts((t) => t.filter((x) => x.id !== a.id)), 6500);
              if (notifyRef.current && typeof Notification !== "undefined" && Notification.permission === "granted")
                new Notification("EventRain Cover", { body: a.text });
            });
            if (fresh.length) setToasts((t) => [...t, ...fresh].slice(-4));
          }
          setP(np);
        })
        .catch((e: Error) => setError(e.message)),
    [id],
  );

  const enableNotify = async () => {
    if (typeof Notification === "undefined") return setError("This browser doesn't support notifications.");
    const perm = await Notification.requestPermission();
    notifyRef.current = perm === "granted";
    setNotify(perm === "granted");
  };

  useEffect(() => {
    load();
    api<Config>("/config").then(setCfg).catch(() => {});
  }, [load]);

  // Poll fast while the replay runs, slowly otherwise
  const replaying = p?.status === "ACTIVE" && p.live?.started && !p.live.finished;
  useEffect(() => {
    if (!p || ["PAID", "EXPIRED", "CANCELLED"].includes(p.status)) return;
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
          {p.payout_mode === "graduated" ? (
            <>The more it rains at {p.venue} during your event, the more we pay:{" "}
              <b>{p.ladder.map((t) => `${inr(p.payout_amount * t.fraction)} at ${t.mm} mm`).join(", ")}</b>.</>
          ) : (
            <>If <b>{p.threshold_mm} mm or more</b> rain falls at {p.venue} during your event, we pay{" "}
              <b>{inr(p.payout_amount)}</b>.</>
          )}{" "}
          Paid automatically to{" "}
          {p.splits.length > 1 ? (
            <b>{p.splits.map((x) => `${x.name} (${x.pct}%)`).join(", ")}</b>
          ) : (
            <b>{p.paypal_email}</b>
          )}. No claim needed.
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

      <div aria-live="polite" className="pointer-events-none fixed right-4 top-20 z-[1000] flex w-80 flex-col gap-2">
        {toasts.map((a) => (
          <div key={a.id} className={`pointer-events-auto rounded-2xl p-4 text-sm shadow-lg ring-1 ${
            a.kind === "trigger" ? "bg-marigold text-ink ring-marigold-deep" : a.kind === "warn" ? "bg-ink text-mist ring-rain" : "bg-white text-ink ring-ink/10"}`}>
            <p className="text-xs font-semibold uppercase tracking-wider opacity-70">🔔 Rain alert · {a.time}</p>
            <p className="mt-1 font-medium">{a.text}</p>
          </div>
        ))}
      </div>

      {p.status === "ACTIVE" && <LiveSection p={p} busy={busy} notify={notify} onNotify={enableNotify}
        onStart={() => act(() => api(`/policies/${id}/demo/start`, {}))} />}

      {["TRIGGERED", "PAID", "EXPIRED", "FLAGGED"].includes(p.status) && <ResultSection p={p} />}

      {p.status === "CANCELLED" && p.summary && (
        <section className="rounded-3xl bg-mist p-8">
          <h2 className="font-display text-3xl font-semibold">Cover cancelled</h2>
          <p className="mt-2 text-lg">{p.summary}</p>
        </section>
      )}

      {p.status !== "QUOTED" && (
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <a href={`/api/policies/${p.id}/certificate`} target="_blank"
            className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-ink/5 hover:ring-ink/20">
            <p className="font-semibold">📄 Policy certificate</p>
            <p className="text-sm text-slate">Open, print or save as PDF</p>
          </a>
          {p.decision ? (
            <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-ink/5">
              <p className="font-semibold">🧾 Proof pack</p>
              <p className="text-sm text-slate">Every hourly reading from both sources, links to re-check them, and a SHA-256 fingerprint.</p>
              <div className="mt-2 flex gap-3 text-sm font-semibold">
                <a className="text-ink-3 underline" href={`/api/policies/${p.id}/proof`} target="_blank">Open</a>
                <a className="text-ink-3 underline" href={`/api/policies/${p.id}/proof.json`}>Download JSON</a>
              </div>
            </div>
          ) : (
            <div className="rounded-2xl bg-white p-5 text-slate shadow-sm ring-1 ring-ink/5">
              <p className="font-semibold text-ink">🧾 Proof pack</p>
              <p className="text-sm">Ready once the weather has been checked after the event.</p>
            </div>
          )}
          <button type="button" onClick={() => share(p)}
            className="rounded-2xl bg-white p-5 text-left shadow-sm ring-1 ring-ink/5 hover:ring-ink/20">
            <p className="font-semibold">💬 Share on WhatsApp</p>
            <p className="text-sm text-slate">Send the cover{p.decision ? " and the result" : ""} to your team or suppliers.</p>
          </button>
          {p.can_cancel ? (
            <button type="button" disabled={busy}
              onClick={() => confirm(`Cancel this cover? ${inr(p.refund_inr)} (premium minus the ₹99 fee) will be refunded to your PayPal.`)
                && act(() => api(`/policies/${id}/cancel`, {}))}
              className="rounded-2xl bg-white p-5 text-left shadow-sm ring-1 ring-ink/5 hover:ring-alert/40 disabled:opacity-50">
              <p className="font-semibold">↩️ Cancel & refund</p>
              <p className="text-sm text-slate">Plans changed? Get {inr(p.refund_inr)} back via PayPal.</p>
            </button>
          ) : null}
          <div className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-ink/5 md:col-span-2 xl:col-span-4">
            <p className="mb-2 font-semibold">PayPal activity</p>
            <ul className="space-y-1 text-sm">
              {p.payments.map((x, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>
                    {x.type === "PREMIUM" ? "Premium received" : x.type === "PAYOUT" ? "Payout sent" : x.type === "REFUND" ? "Refund sent" : x.type}
                    {x.type === "PAYOUT" && p.splits.length > 1 && (
                      <span className="block text-xs text-slate">split: {p.splits.map((s) => `${s.name} ${s.pct}%`).join(" · ")}</span>
                    )}
                  </span>
                  <span className="text-right text-slate">{inr(x.type === "PREMIUM" ? p.premium : x.amount * (cfg?.inr_per_usd ?? 88))} · {x.status}<br /><code className="text-xs">{x.paypal_id}</code></span>
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

function share(p: Policy) {
  const url = window.location.href;
  const rule = p.payout_mode === "graduated"
    ? p.ladder.map((t) => `${inr(p.payout_amount * t.fraction)} at ${t.mm} mm`).join(", ")
    : `${inr(p.payout_amount)} if ${p.threshold_mm} mm+ rain`;
  const text = p.summary && p.decision
    ? `☂ EventRain Cover update for ${p.event_name}: ${p.summary} ${url}`
    : `☂ ${p.event_name} at ${p.venue} is rain-covered by EventRain: ${rule}, paid automatically via PayPal. Live status: ${url}`;
  window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener");
}

function LiveSection({ p, busy, onStart, notify, onNotify }: {
  p: Policy; busy: boolean; onStart: () => void; notify: boolean; onNotify: () => void;
}) {
  const live = p.live!;
  // Graduated cover: the gauge aims at the next level not yet reached
  const next = p.ladder.find((t) => live.rain_so_far < t.mm) ?? p.ladder[p.ladder.length - 1];
  const alerts = live.alerts ?? [];
  return (
    <section className="relative overflow-hidden rounded-3xl bg-ink p-7 text-mist">
      {live.started && !live.finished && live.rain_so_far > 0 && <Rain drops={40} />}
      <div className="relative grid gap-8 md:grid-cols-[auto_1fr]">
        <RainGauge mm={live.rain_so_far} threshold={next.mm} />
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
                    <YAxis domain={[0, Math.ceil(Math.max(next.mm * 1.3, live.rain_so_far + 2) / 5) * 5]} tick={{ fill: "#e8f1f4aa", fontSize: 11 }} />
                    <Tooltip formatter={(v) => [`${v} mm`, "Total so far"]} contentStyle={{ background: "#12303f", border: 0, borderRadius: 8 }} labelStyle={{ color: "#e8f1f4" }} />
                    {p.ladder.map((t) => (
                      <ReferenceLine key={t.mm} y={t.mm} stroke="#f2a93b" strokeDasharray="5 3"
                        label={{ value: p.ladder.length > 1 ? `${t.fraction * 100}% at ${t.mm} mm` : "payout line", fill: "#f2a93b", fontSize: 11, position: "insideTopLeft" }} />
                    ))}
                    <Area type="monotone" dataKey="cumulative" stroke="#5cc2e6" fill="#5cc2e655" isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </>
          )}
          <div className="rounded-2xl bg-ink-2 p-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <p className="text-sm font-semibold">🔔 Live rain alerts</p>
              <button type="button" onClick={onNotify} disabled={notify}
                className="rounded-full px-3 py-1 text-xs ring-1 ring-mist/30 hover:ring-mist disabled:opacity-60">
                {notify ? "Browser alerts on" : "Get browser alerts"}
              </button>
            </div>
            {alerts.length ? (
              <ol className="max-h-40 space-y-1.5 overflow-y-auto text-sm">
                {[...alerts].reverse().map((a) => (
                  <li key={a.id} className="flex gap-3">
                    <span className="w-12 shrink-0 tabular-nums text-mist/50">{a.time}</span>
                    <span className={a.kind === "trigger" ? "font-semibold text-marigold" : a.kind === "warn" ? "text-rain" : "text-mist/80"}>{a.text}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-sm text-mist/60">{live.started ? "No alerts yet: dry so far." : "Alerts appear here as rain builds up during the event."}</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function ResultSection({ p }: { p: Policy }) {
  const d = p.decision;
  const paid = p.status === "PAID" || p.status === "TRIGGERED";
  const paidInr = (p.paid_fraction || (paid ? 1 : 0)) * p.payout_amount;
  const sources = d ? Object.entries(d.totals).map(([name, mm]) => ({ name, mm })) : [];
  return (
    <section className={`relative overflow-hidden rounded-3xl p-8 ${paid ? "bg-ink text-mist" : p.status === "FLAGGED" ? "bg-alert/10" : "bg-mist"}`}>
      {paid && <Rain drops={30} />}
      <div className="relative grid gap-8 md:grid-cols-[1.2fr_1fr]">
        <div className="space-y-3">
          <p className="text-xs uppercase tracking-widest opacity-60">Result</p>
          <h2 className="font-display text-4xl font-semibold">
            {paid ? <>Trigger met: <span className="text-marigold">{inr(paidInr)}</span> {p.status === "PAID" ? "sent" : "sending"}</>
              : p.status === "FLAGGED" ? (paidInr > 0 ? <>{inr(paidInr)} sent, the rest under review</> : "A person is double-checking")
              : "Good weather! No payout needed"}
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
                  <YAxis tick={{ fill: paid ? "#e8f1f4aa" : "#5b7380", fontSize: 11 }} domain={[0, Math.ceil((Math.max(...p.ladder.map((t) => t.mm), ...sources.map((x) => x.mm)) * 1.2) / 5) * 5]} />
                  <Tooltip formatter={(v) => [`${v} mm`, "Measured"]} />
                  {p.ladder.map((t) => (
                    <ReferenceLine key={t.mm} y={t.mm} stroke="#f2a93b" strokeDasharray="5 3"
                      label={{ value: p.ladder.length > 1 ? `${t.fraction * 100}% at ${t.mm} mm` : `${t.mm} mm rule`, fill: "#d88412", fontSize: 11, position: "insideTopRight" }} />
                  ))}
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
