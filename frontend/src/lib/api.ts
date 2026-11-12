export type Config = {
  paypal_client_id: string | null;
  mock_paypal: boolean;
  inr_per_usd: number;
  cutoff_hours: number;
  payouts: number[];
  thresholds: number[];
  margin: number;
  platform_fee_inr: number;
  demo_replay_date: string;
  demo_dry_date: string;
  demo_replay_seconds: number;
};

export type Slot = { start: string; end: string; premium_inr: number; probability: number };
export type Suggestion = Slot & { saving_inr: number; kind: "date" | "time" };
export type Tier = { mm: number; fraction: number; probability?: number };
export type PayoutMode = "fixed" | "graduated";
export type Split = { name: string; email: string; pct: number };
export type Alert = { id: string; time: string; kind: "info" | "warn" | "trigger"; text: string };

export type Quote = {
  probability: number;
  expected_payout_fraction: number;
  payout_mode: PayoutMode;
  tiers: Tier[];
  suggestions?: Suggestion[];
  hourly_risk?: (Slot & { hour: number })[];
  premium_inr: number;
  payout_inr: number;
  threshold_mm: number;
  premium_usd: number;
  payout_usd: number;
  breakdown: { expected_loss_inr: number; margin_pct: number; margin_inr: number; platform_fee_inr: number };
  signals: {
    model: string;
    historical_probability: number;
    forecast: { probability: number; members: number; median_mm: number; lead_days: number } | null;
    forecast_weight: number;
    local_base_rate: number;
  };
  history: { base_rate: number; years: string; per_year: { year: number; rain_mm: number; rainy_days: number }[] };
  duration_h: number;
};

export type Live = {
  mode: "demo" | "live";
  started: boolean;
  finished?: boolean;
  progress?: number;
  replay_date?: string;
  scenario?: "rain" | "dry" | "live";
  forecast_hours?: number;
  clock?: string;
  rain_so_far: number;
  threshold_mm: number;
  starts_in_s?: number;
  series: { time: string; rain_mm: number; cumulative: number; forecast?: boolean }[];
  alerts?: Alert[];
};

export type Decision = {
  totals: Record<string, number>;
  threshold_mm: number;
  outcome: "PAY" | "NO_PAY" | "REVIEW";
  reason: string;
  spread_mm: number;
  tolerance_mm: number;
  window: [string, string];
  earned_fraction?: number;
  disputed_fraction?: number;
  sources?: Record<string, string>;
  checked_at: string;
  demo_replay: boolean;
};

export type Payment = { type: string; paypal_id: string | null; amount: number; currency: string; status: string; created_at: string };

export type Status = "QUOTED" | "ACTIVE" | "TRIGGERED" | "PAID" | "EXPIRED" | "FLAGGED" | "CANCELLED";

export type Policy = {
  id: number;
  status: Status;
  threshold_mm: number;
  payout_amount: number;
  premium: number;
  probability: number;
  premium_usd: number;
  payout_usd: number;
  summary: string | null;
  demo: number;
  event_name: string;
  venue: string;
  lat: number;
  lon: number;
  start_time: string;
  end_time: string;
  user_name: string;
  email: string;
  paypal_email: string;
  created_at: string;
  quote: Quote;
  decision: Decision | null;
  payments: Payment[];
  live: Live | null;
  payout_mode: PayoutMode;
  paid_fraction: number;
  splits: Split[];
  ladder: Tier[];
  can_cancel: boolean;
  refund_inr: number;
};

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data as { detail?: unknown }).detail;
    const msg = Array.isArray(d)
      ? d.map((x: { msg?: string }) => (x.msg ?? "").replace(/^Value error, /, "")).join(". ")
      : typeof d === "string"
        ? d
        : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data as T;
}

export const inr = (n: number) =>
  "₹" + Math.round(n).toLocaleString("en-IN");

export const pct = (p: number) => `${(p * 100).toFixed(p < 0.1 ? 1 : 0)}%`;

export const fmtWindow = (start: string, end: string) => {
  const s = new Date(start);
  const e = new Date(end);
  const day = s.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  const t = (d: Date) => d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  return `${day}, ${t(s)} – ${t(e)}`;
};
