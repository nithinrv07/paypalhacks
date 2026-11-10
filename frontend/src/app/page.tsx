import Link from "next/link";
import Rain from "@/components/Rain";

const steps = [
  ["Tell us the event", "Pin the venue, pick the date and hours, choose how much to protect."],
  ["AI prices the risk", "15 years of local rain history plus a 31-member live forecast give a fair price in seconds."],
  ["Pay with PayPal", "One click. Your cover is active and a certificate is issued instantly."],
  ["Weather decides", "Two independent weather sources measure rain at your venue during your hours."],
  ["Money arrives", "Rule met? The payout goes to your PayPal automatically. No forms, no inspector."],
];

const compare = [
  ["Who it's for", "Big concerts, corporates", "College fests, pop-ups, lawn weddings"],
  ["Buying", "Broker, forms, days", "2 minutes online"],
  ["Claim", "Bills, photos, proof of loss", "None. Data triggers the payout"],
  ["Payout speed", "Weeks to months", "Same day"],
  ["Pricing", "Fixed tables", "AI, per location and hour"],
];

export default function Home() {
  return (
    <>
      <section className="relative overflow-hidden bg-ink text-mist">
        <Rain />
        <div className="relative grid min-h-[calc(100svh-4.5rem)] w-full items-center gap-10 px-6 py-16 md:grid-cols-[1.2fr_1fr] lg:px-12 2xl:px-20">
          <div>
            <p className="mb-4 text-sm font-medium uppercase tracking-[0.2em] text-rain">Chennai · NE monsoon season</p>
            <h1 className="font-display text-5xl leading-[1.05] font-bold tracking-tight md:text-7xl 2xl:text-8xl">
              Rain shouldn&apos;t ruin <span className="text-marigold">your event.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg 2xl:text-xl text-mist/80">
              Protect one evening for the price of a few plates. If it really pours during your event, the
              money lands in your PayPal automatically, with no claim forms at all.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/quote" className="rounded-full bg-marigold px-7 py-3.5 text-lg font-semibold text-ink hover:bg-marigold-deep">
                Get a quote in 2 minutes
              </Link>
              <Link href="/quote?demo=1" className="rounded-full border border-mist/30 px-7 py-3.5 text-lg hover:border-mist">
                Try the live demo
              </Link>
            </div>
          </div>
          <div className="rounded-3xl border border-mist/15 bg-ink-2/80 p-6 backdrop-blur">
            <p className="text-xs uppercase tracking-widest text-mist/60">Example rule, agreed upfront</p>
            <p className="mt-3 font-display text-2xl leading-snug">
              If <span className="text-rain">10 mm or more</span> rain falls at Besant Nagar between 4 PM and 10 PM on 14 Dec,
              pay <span className="text-marigold">₹20,000</span>.
            </p>
            <div className="mt-6 grid grid-cols-3 gap-3 text-center">
              {[["Premium", "from ₹560"], ["Claim forms", "0"], ["Payout", "same day"]].map(([k, v]) => (
                <div key={k} className="rounded-2xl bg-ink-3/60 p-3">
                  <div className="font-display text-xl text-mist">{v}</div>
                  <div className="text-xs text-mist/60">{k}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="w-full px-6 py-20 lg:px-12 2xl:px-20">
        <h2 className="font-display text-3xl font-semibold md:text-4xl">How it works</h2>
        <ol className="mt-10 grid gap-5 md:grid-cols-5">
          {steps.map(([t, d], i) => (
            <li key={t} className="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-ink/5">
              <span className="font-display text-3xl text-marigold-deep">{i + 1}</span>
              <h3 className="mt-2 font-semibold">{t}</h3>
              <p className="mt-1 text-sm text-slate">{d}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="bg-mist">
        <div className="w-full px-6 py-20 lg:px-12 2xl:px-20">
          <h2 className="font-display text-3xl font-semibold md:text-4xl">Not your usual event insurance</h2>
          <div className="mt-8 overflow-x-auto rounded-2xl bg-white ring-1 ring-ink/5">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-ink/10 text-slate">
                  <th className="p-4 font-medium"></th>
                  <th className="p-4 font-medium">Traditional event insurance</th>
                  <th className="p-4 font-semibold text-ink">EventRain Cover</th>
                </tr>
              </thead>
              <tbody>
                {compare.map(([k, a, b]) => (
                  <tr key={k} className="border-b border-ink/5 last:border-0">
                    <td className="p-4 font-medium">{k}</td>
                    <td className="p-4 text-slate">{a}</td>
                    <td className="p-4 font-medium text-ink-3">{b}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </>
  );
}
