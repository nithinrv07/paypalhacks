import { Suspense } from "react";
import PolicyView from "./PolicyView";

export default function PolicyPage() {
  return (
    <Suspense fallback={<div className="p-10 text-center text-slate">Loading policy…</div>}>
      <PolicyView />
    </Suspense>
  );
}
