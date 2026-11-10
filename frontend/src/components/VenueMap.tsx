"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useRef } from "react";

type Props = { lat: number; lon: number; onPick: (lat: number, lon: number) => void };

/**
 * Plain Leaflet instead of react-leaflet: React 19 / Next 16 can mount a
 * component twice in development, and react-leaflet then crashes with
 * "Map container is being reused by another instance". Here every mount
 * creates its own map and every unmount removes it, so double mounts are safe.
 */
export default function VenueMap({ lat, lon, onPick }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const pin = useRef<L.CircleMarker | null>(null);
  const pick = useRef(onPick);
  const start = useRef<[number, number]>([lat, lon]);

  useEffect(() => {
    pick.current = onPick;
  }, [onPick]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const m = L.map(el, { scrollWheelZoom: false }).setView(start.current, 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(m);
    pin.current = L.circleMarker(start.current, {
      radius: 11, color: "#0b1e2a", fillColor: "#f2a93b", fillOpacity: 1, weight: 3,
    }).addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => pick.current(+e.latlng.lat.toFixed(4), +e.latlng.lng.toFixed(4)));
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
      pin.current = null;
    };
  }, []);

  // Move the pin (and the view, if needed) when the venue changes
  useEffect(() => {
    pin.current?.setLatLng([lat, lon]);
    const m = map.current;
    if (m && !m.getBounds().contains([lat, lon])) m.panTo([lat, lon]);
  }, [lat, lon]);

  return <div ref={box} className="relative z-0 h-72 w-full rounded-2xl" />;
}
