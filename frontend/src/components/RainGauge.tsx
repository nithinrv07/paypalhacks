// A rain-gauge tube: water level rises toward the payout line.
export default function RainGauge({ mm, threshold }: { mm: number; threshold: number }) {
  const max = Math.max(threshold * 1.6, mm * 1.1);
  const H = 260;
  const level = Math.min(1, mm / max) * H;
  const lineY = H - (threshold / max) * H;
  const crossed = mm >= threshold;
  return (
    <div className="flex items-center gap-6">
      <svg viewBox={`0 0 90 ${H + 20}`} className="h-72 w-24" role="img" aria-label={`${mm.toFixed(1)} of ${threshold} millimetres`}>
        <defs>
          <clipPath id="tube"><rect x="20" y="10" width="50" height={H} rx="25" /></clipPath>
        </defs>
        <rect x="20" y="10" width="50" height={H} rx="25" fill="#12303f" stroke="#1d4557" strokeWidth="2" />
        <g clipPath="url(#tube)">
          <rect x="20" y={10 + H - level} width="50" height={level} fill={crossed ? "#f2a93b" : "#5cc2e6"}
            style={{ transition: "y 0.9s ease, height 0.9s ease, fill 0.4s" }} />
        </g>
        <line x1="10" x2="80" y1={10 + lineY} y2={10 + lineY} stroke="#f2a93b" strokeWidth="2" strokeDasharray="5 3" />
        <text x="84" y={14 + lineY} fill="#f2a93b" fontSize="9" textAnchor="end" dy="-6">{threshold} mm</text>
      </svg>
      <div>
        <p className="font-display text-6xl font-semibold tabular-nums text-mist">
          {mm.toFixed(1)}<span className="text-2xl text-mist/50"> / {threshold} mm</span>
        </p>
        <p className={`mt-2 text-lg font-semibold ${crossed ? "text-marigold" : "text-rain"}`}>
          {crossed ? "Threshold crossed: payout rule met" : `${(threshold - mm).toFixed(1)} mm to go`}
        </p>
      </div>
    </div>
  );
}
