"use client";

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, inr, pct, type Config, type Quote } from "@/lib/api";

const VenueMap = dynamic(() => import("@/components/VenueMap"), {
  ssr: false,
  loading: () => <div className="h-72 animate-pulse rounded-2xl bg-mist" />,
});

const VENUES = [
  { name: "Besant Nagar Beach", lat: 13.0002, lon: 80.2668 },
  { name: "Anna University grounds", lat: 13.0108, lon: 80.2354 },
  { name: "IIT Madras Open Air Theatre", lat: 12.9915, lon: 80.2337 },
  { name: "Island Grounds", lat: 13.0784, lon: 80.2724 },
  { name: "Tambaram MCC grounds", lat: 12.9205, lon: 80.1215 },
];
const LEVELS = [
  { mm: 5, label: "Light", hint: "5 mm: a steady drizzle" },
  { mm: 10, label: "Medium", hint: "10 mm: proper rain, people leave" },
  { mm: 20, label: "Heavy", hint: "20 mm: a downpour" },
];

const pad = (n: number) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export default function QuoteForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [cfg, setCfg] = useState<Config | null>(null);
  const [demo, setDemo] = useState(params.get("demo") === "1");
  const [picked, setPicked] = useState<"rain" | "dry" | "live">(
    params.get("weather") === "dry" ? "dry" : params.get("weather") === "live" ? "live" : "rain",
  );
  const [venue, setVenue] = useState(VENUES[0].name);
  const [lat, setLat] = useState(VENUES[0].lat);
  const [lon, setLon] = useState(VENUES[0].lon);
  const [day, setDay] = useState(() => isoDay(new Date(Date.now() + 5 * 864e5)));
  const [startH, setStartH] = useState(16);
  const [endH, setEndH] = useState(22);
  const [payout, setPayout] = useState(20000);
  const [threshold, setThreshold] = useState(10);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ event_name: "", name: "", email: "", paypal_email: "" });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api<Config>("/config").then(setCfg).catch(() => setError("Can't reach the API. Is the backend running on port 8000?"));
  }, []);

  // Events today or tomorrow always use the live weather for their real hours
  const daysAway = Math.round((new Date(`${day}T00:00`).getTime() - new Date(isoDay(new Date()) + "T00:00").getTime()) / 864e5);
  const soon = daysAway === 0 || daysAway === 1;
  const scenario = soon ? "live" : picked;
  const setScenario = setPicked;

  const body = useMemo(
    () => ({
      lat, lon, threshold_mm: threshold, payout_inr: payout, demo, demo_scenario: scenario,
      start: `${day}T${pad(startH)}:00`, end: `${day}T${pad(endH)}:00`,
    }),
    [lat, lon, threshold, payout, demo, scenario, day, startH, endH],
  );

  const rangeError = endH <= startH ? "The event must end after it starts." : null;

  useEffect(() => {
    if (rangeError) return;
    let cancelled = false;
    const t = setTimeout(() => {
      setQuoting(true);
      api<Quote>("/quote", body)
        .then((q) => !cancelled && (setQuote(q), setError(null)))
        .catch((e: Error) => !cancelled && (setError(e.message), setQuote(null)))
        .finally(() => !cancelled && setQuoting(false));
    }, 450);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [body, rangeError]);

  const pickPreset = (name: string) => {
    const v = VENUES.find((x) => x.name === name);
    setVenue(name);
    if (v) {
      setLat(v.lat);
      setLon(v.lon);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      const { id } = await api<{ id: number }>("/policies", { ...body, venue, ...form });
      router.push(`/policy/${id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  };

  const fillDemo = () => {
    setForm({ event_name: "Priya's Food Pop-up", name: "Priya", email: "priya@example.com", paypal_email: form.paypal_email || "" });
    pickPreset("Besant Nagar Beach");
    setStartH(16);
    setEndH(22);
    setThreshold(10);
    setPayout(20000);
  };

  const input = "w-full rounded-xl border border-ink/15 bg-white px-3 py-2.5 outline-none focus:border-ink-3 focus:ring-2 focus:ring-rain/40";

  return (
    <div className="grid w-full gap-8 px-6 py-10 lg:grid-cols-[1.3fr_1fr] lg:px-12 2xl:px-20">
      <form onSubmit={submit} className="space-y-8">
        <div>
          <h1 className="font-display text-4xl font-semibold">Get a quote</h1>
          <p className="mt-1 text-slate">The price updates live as you change anything.</p>
        </div>

        <div className="space-y-3 rounded-2xl border border-marigold/50 bg-marigold/10 p-4">
          <label className="flex cursor-pointer items-start gap-3">
            <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} className="mt-1 h-4 w-4 accent-marigold-deep" />
            <span className="text-sm">
              <b>Demo mode.</b> After payment, the event replays a real evening in Chennai in about a minute, so you
              can see what happens. Skips the {cfg?.cutoff_hours ?? 24}-hour purchase cut-off.
              {demo && (
                <button type="button" onClick={fillDemo} className="ml-2 font-semibold text-marigold-deep underline">
                  Fill demo story
                </button>
              )}
            </span>
          </label>
          {demo && (
            <div role="radiogroup" aria-label="Demo weather" className="grid gap-2 sm:grid-cols-3">
              {([
                ["rain", "🌧 Rainy evening", `${cfg?.demo_replay_date ?? "15 Nov 2023"}: heavy rain, payout is sent`],
                ["dry", "🌤 Dry evening", `${cfg?.demo_dry_date ?? "26 Nov 2023"}: light drizzle only, no payout`],
                ["live", "📡 Live weather", soon
                  ? `Your event is ${daysAway === 0 ? "today" : "tomorrow"}: real weather for your actual hours (forecast for hours not yet passed)`
                  : "The latest real weather at this venue for your hours (today or yesterday)"],
              ] as const).map(([value, title, hint]) => (
                <button key={value} type="button" role="radio" aria-checked={scenario === value} onClick={() => setScenario(value)}
                  disabled={soon && value !== "live"}
                  className={`rounded-xl p-3 text-left text-sm ring-1 disabled:cursor-not-allowed disabled:opacity-40 ${scenario === value ? "bg-ink text-mist ring-ink" : "bg-white ring-ink/15 hover:ring-ink/40"}`}>
                  <div className="font-semibold">{title}</div>
                  <div className={scenario === value ? "text-mist/70" : "text-slate"}>{hint}</div>
                </button>
              ))}
            </div>
          )}
        </div>

        <fieldset className="space-y-3">
          <legend className="mb-2 font-semibold">1. Where is the event?</legend>
          <div className="flex flex-wrap gap-2">
            {VENUES.map((v) => (
              <button key={v.name} type="button" onClick={() => pickPreset(v.name)}
                className={`rounded-full px-3 py-1.5 text-sm ring-1 ${venue === v.name ? "bg-ink text-mist ring-ink" : "bg-white ring-ink/15 hover:ring-ink/40"}`}>
                {v.name}
              </button>
            ))}
          </div>
          <VenueMap lat={lat} lon={lon} onPick={(a, b) => { setLat(a); setLon(b); setVenue("Custom venue"); }} />
          <div className="grid grid-cols-[1fr_auto] gap-3">
            <input className={input} value={venue} onChange={(e) => setVenue(e.target.value)} aria-label="Venue name" required minLength={2} />
            <span className="self-center text-xs text-slate">{lat.toFixed(4)}, {lon.toFixed(4)} · tap map to move</span>
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-2 font-semibold">2. When?</legend>
          <div className="grid grid-cols-3 gap-3">
            <label className="text-sm text-slate">Date
              <input type="date" className={input} value={day} onChange={(e) => setDay(e.target.value)} required />
            </label>
            <label className="text-sm text-slate">Starts
              <select className={input} value={startH} onChange={(e) => setStartH(+e.target.value)}>
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}:00</option>)}
              </select>
            </label>
            <label className="text-sm text-slate">Ends
              <select className={input} value={endH} onChange={(e) => setEndH(+e.target.value)}>
                {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{pad(h)}:00</option>)}
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-2 font-semibold">3. How much do you want protected?</legend>
          <div className="flex flex-wrap gap-2">
            {(cfg?.payouts ?? [10000, 20000, 30000, 50000, 75000, 100000]).map((p) => (
              <button key={p} type="button" onClick={() => setPayout(p)}
                className={`rounded-xl px-4 py-2 font-semibold ring-1 ${payout === p ? "bg-marigold text-ink ring-marigold" : "bg-white ring-ink/15 hover:ring-ink/40"}`}>
                {inr(p)}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="mb-2 font-semibold">4. How much rain should trigger the payout?</legend>
          <div className="grid grid-cols-3 gap-2">
            {LEVELS.map((l) => (
              <button key={l.mm} type="button" onClick={() => setThreshold(l.mm)}
                className={`rounded-2xl p-3 text-left ring-1 ${threshold === l.mm ? "bg-ink text-mist ring-ink" : "bg-white ring-ink/15 hover:ring-ink/40"}`}>
                <div className="font-semibold">{l.label}</div>
                <div className={`text-xs ${threshold === l.mm ? "text-mist/70" : "text-slate"}`}>{l.hint}</div>
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate">Lower thresholds happen more often, so they cost more.</p>
        </fieldset>

        <fieldset className="space-y-3">
          <legend className="mb-2 font-semibold">5. Your details</legend>
          <input className={input} placeholder="Event name (e.g. Priya's Food Pop-up)" value={form.event_name}
            onChange={(e) => setForm({ ...form, event_name: e.target.value })} required minLength={2} />
          <div className="grid gap-3 sm:grid-cols-2">
            <input className={input} placeholder="Your name" value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })} required minLength={2} />
            <input className={input} type="email" placeholder="Email" value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} required />
          </div>
          <input className={input} type="email" placeholder="PayPal email for the payout" value={form.paypal_email}
            onChange={(e) => setForm({ ...form, paypal_email: e.target.value })} required />
          <p className="text-xs text-slate">For the Sandbox, use your sandbox <b>personal</b> account email so you can see the payout arrive.</p>
        </fieldset>

        {(rangeError ?? error) && <p role="alert" className="rounded-xl bg-alert/10 p-3 text-sm text-alert">{rangeError ?? error}</p>}

        <button disabled={!quote || !!rangeError || submitting || quoting}
          className="w-full rounded-full bg-ink py-4 text-lg font-semibold text-mist hover:bg-ink-3 disabled:opacity-40">
          {submitting ? "Creating your policy…" : quote ? `Continue: pay ${inr(quote.premium_inr)}` : "Continue"}
        </button>
      </form>

      <aside className="lg:sticky lg:top-6 lg:self-start">
        <QuotePanel quote={rangeError ? null : quote} quoting={quoting} threshold={threshold} payout={payout} />
      </aside>
    </div>
  );
}

function QuotePanel({ quote, quoting, threshold, payout }: { quote: Quote | null; quoting: boolean; threshold: number; payout: number }) {
  if (!quote)
    return (
      <div className="rounded-3xl bg-ink p-8 text-mist">
        <p className="animate-pulse text-mist/70">{quoting ? "AI is reading 15 years of weather…" : "Fill in the event to see a price."}</p>
      </div>
    );
  const s = quote.signals;
  return (
    <div className={`space-y-5 rounded-3xl bg-ink p-7 text-mist transition-opacity ${quoting ? "opacity-60" : ""}`}>
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-widest text-mist/60">Chance of {threshold}+ mm in your window</p>
          <p className="font-display text-6xl font-semibold text-rain">{pct(quote.probability)}</p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-widest text-mist/60">Premium</p>
          <p className="font-display text-4xl font-semibold text-marigold">{inr(quote.premium_inr)}</p>
          <p className="text-xs text-mist/60">paid via PayPal</p>
        </div>
      </div>

      <p className="rounded-2xl bg-ink-2 p-4 text-sm leading-relaxed">
        Pay <b>{inr(quote.premium_inr)}</b>. If <b>{threshold} mm</b> or more rain falls, you get <b>{inr(payout)}</b>{" "}
        automatically. If the weather is fine, enjoy your event.
      </p>

      <div className="space-y-1.5 text-sm">
        <Row k={`Expected loss (${pct(quote.probability)} × ${inr(payout)})`} v={inr(quote.breakdown.expected_loss_inr)} />
        <Row k={`Safety margin (${quote.breakdown.margin_pct}%)`} v={inr(quote.breakdown.margin_inr)} />
        <Row k="Platform fee" v={inr(quote.breakdown.platform_fee_inr)} />
        <div className="border-t border-mist/15 pt-1.5"><Row k="Premium" v={inr(quote.premium_inr)} bold /></div>
      </div>

      <div className="space-y-2 rounded-2xl bg-ink-2 p-4 text-sm">
        <p className="font-semibold">How the AI got there</p>
        <Row k={`History model (${s.model.replace("_", " ")}, 15 yrs)`} v={pct(s.historical_probability)} />
        {s.forecast ? (
          <Row k={`Live forecast: ${s.forecast.members} GFS runs, ${s.forecast.lead_days} days out (weight ${Math.round(s.forecast_weight * 100)}%)`}
            v={pct(s.forecast.probability)} />
        ) : (
          <p className="text-mist/60">Live forecast kicks in within 14 days of the event.</p>
        )}
        <Row k={`Days with ${threshold}+ mm near this date (local)`} v={pct(s.local_base_rate)} />
      </div>

      <div>
        <p className="mb-2 text-sm font-semibold">Rain on this date, past years (whole day)</p>
        <div className="h-36">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={quote.history.per_year} margin={{ top: 4, right: 4, left: -28, bottom: 0 }}>
              <XAxis dataKey="year" tick={{ fill: "#e8f1f4aa", fontSize: 10 }} tickFormatter={(y) => `'${String(y).slice(2)}`} />
              <YAxis tick={{ fill: "#e8f1f4aa", fontSize: 10 }} />
              <Tooltip formatter={(v) => [`${v} mm`, "Rain"]} contentStyle={{ background: "#12303f", border: 0, borderRadius: 8 }} labelStyle={{ color: "#e8f1f4" }} />
              <ReferenceLine y={threshold} stroke="#f2a93b" strokeDasharray="4 3" />
              <Bar dataKey="rain_mm" fill="#5cc2e6" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v, bold }: { k: string; v: string; bold?: boolean }) {
  return (
    <div className={`flex justify-between gap-4 ${bold ? "font-semibold" : ""}`}>
      <span className={bold ? "" : "text-mist/70"}>{k}</span>
      <span className="tabular-nums">{v}</span>
    </div>
  );
}
