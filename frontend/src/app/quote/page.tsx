import { Suspense } from "react";
import QuoteForm from "./QuoteForm";

export default function QuotePage() {
  return (
    <Suspense fallback={<div className="p-10 text-center text-slate">Loading…</div>}>
      <QuoteForm />
    </Suspense>
  );
}
