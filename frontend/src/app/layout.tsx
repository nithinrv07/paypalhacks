import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Sora } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const display = Sora({ variable: "--font-display", subsets: ["latin"] });
const body = Plus_Jakarta_Sans({ variable: "--font-body", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "EventRain Cover: rain protection for small events",
  description: "Rain cover priced per event by AI, paid through PayPal, with zero claim forms.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col font-sans">
        <header className="bg-ink text-mist">
          <nav className="flex w-full items-center justify-between px-6 py-4 lg:px-12 2xl:px-20">
            <Link href="/" className="flex items-center gap-2 font-display text-xl font-semibold tracking-tight">
              <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-marigold text-ink">☂</span>
              EventRain <span className="font-normal text-rain">Cover</span>
            </Link>
            <div className="flex items-center gap-5 text-sm">
              <Link href="/admin" className="text-mist/70 hover:text-mist">Admin</Link>
              <Link href="/quote" className="rounded-full bg-marigold px-4 py-2 font-semibold text-ink hover:bg-marigold-deep">
                Get a quote
              </Link>
            </div>
          </nav>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-ink/10 py-6 text-center text-xs text-slate">
          Hackathon prototype · PayPal Sandbox · Weather data from Open-Meteo (ECMWF ERA5, NOAA GFS) · Not an insurance product
        </footer>
      </body>
    </html>
  );
}
