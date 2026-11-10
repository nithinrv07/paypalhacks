// Deterministic raindrops (no Math.random) so server and client markup match.
export default function Rain({ drops = 60 }: { drops?: number }) {
  return (
    <div className="rain" aria-hidden>
      {Array.from({ length: drops }, (_, i) => {
        const left = (i * 37) % 100;
        const delay = ((i * 53) % 100) / 40;
        const dur = 0.7 + ((i * 29) % 10) / 12;
        return <i key={i} style={{ left: `${left}%`, animationDelay: `${delay}s`, animationDuration: `${dur}s` }} />;
      })}
    </div>
  );
}
