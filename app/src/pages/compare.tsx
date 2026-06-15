/**
 * Head-to-Head Comparison page.
 * Side-by-side comparison of two clubs.
 */

import { useState, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { compareClubs, clubLogoUrl, unifiedSearch } from "@/lib/api";
import { ResponsiveRadar } from '@nivo/radar';
import {
  ResponsiveContainer,
  Legend,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

function formatEuro(value: number | null | undefined): string {
  if (value === null || value === undefined) return "€0";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${sign}€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}€${(abs / 1_000).toFixed(1)}K`;
  return `${sign}€${abs.toFixed(0)}`;
}

function ClubSelector({
  label,
  value,
  onSelect,
}: {
  label: string;
  value: number | null;
  onSelect: (id: number | null, name: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ id: number; name: string; subtitle: string | null }[]>([]);
  const [open, setOpen] = useState(false);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const handleChange = (val: string) => {
    setQuery(val);
    setSelectedLabel(null);
    if (val.trim().length < 1) {
      setResults([]);
      setOpen(false);
      return;
    }

    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(async () => {
      try {
        const data = await unifiedSearch(val.trim(), 10);
        const clubs = data.results.filter((r) => r.type === "club");
        setResults(clubs);
        setOpen(clubs.length > 0);
      } catch {
        setResults([]);
      }
    }, 300);
  };

  const pick = (item: { id: number; name: string }) => {
    setQuery("");
    setResults([]);
    setOpen(false);
    setSelectedLabel(item.name);
    onSelect(item.id, item.name);
  };

  const clear = () => {
    setQuery("");
    setResults([]);
    setOpen(false);
    setSelectedLabel(null);
    onSelect(null, null);
  };

  return (
    <div className="form-control w-full">
      <label className="label">
        <span className="label-text">{label}</span>
      </label>
      <div className="relative">
        {selectedLabel ? (
          <div className="flex items-center gap-1.5 input input-bordered w-full pr-1">
            <span className="truncate text-sm">{selectedLabel}</span>
            <button onClick={clear} className="btn btn-ghost btn-xs btn-square shrink-0 ml-auto">
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        ) : (
          <input
            type="text"
            className="input input-bordered w-full"
            placeholder="Search clubs…"
            value={query}
            onChange={(e) => handleChange(e.target.value)}
            onFocus={() => { if (results.length > 0) setOpen(true); }}
            onBlur={() => setTimeout(() => setOpen(false), 200)}
          />
        )}

        {open && results.length > 0 && (
          <div className="absolute top-full left-0 mt-1 w-full z-20 bg-base-100 border border-base-300 rounded-xl shadow-xl max-h-48 overflow-y-auto">
            {results.map((item) => (
              <button
                key={item.id}
                className="w-full text-left px-3 py-2 text-sm hover:bg-base-200 transition-colors flex items-center gap-2"
                onMouseDown={() => pick(item)}
              >
                <img
                  src={clubLogoUrl(item.id) ?? ""}
                  alt=""
                  className="w-4 h-4 object-contain shrink-0"
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
                <span className="font-medium">{item.name}</span>
                {item.subtitle && (
                  <span className="text-xs text-base-content/50 ml-auto">{item.subtitle}</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function useResolvedColor(cssVar: string, fallback: string): string {
  const [color, setColor] = useState(fallback);
  useEffect(() => {
    function resolve() {
      if (typeof document === 'undefined') return;
      const raw = getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim();
      if (raw) setColor(`oklch(${raw})`);
    }
    resolve();
    // Re-resolve when theme changes (data-theme attribute on <html>)
    const observer = new MutationObserver(resolve);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, [cssVar]);
  return color;
}

export default function ComparePage() {
  const [club1Id, setClub1Id] = useState<number | null>(null);
  const [club2Id, setClub2Id] = useState<number | null>(null);

  const resolvedPrimary = useResolvedColor('--p', '#3b82f6');
  const resolvedSecondary = useResolvedColor('--s', '#8b5cf6');

  const { data: comparison, isLoading } = useQuery({
    queryKey: ["comparison", club1Id, club2Id],
    queryFn: () => compareClubs([club1Id!, club2Id!]),
    enabled: !!club1Id && !!club2Id,
  });

  const radarData = comparison
    ? [
        { metric: "Median ROI", [comparison.club1.name]: comparison.club1.median_roi ?? 0, [comparison.club2.name]: comparison.club2.median_roi ?? 0 },
        { metric: "Hit Rate", [comparison.club1.name]: comparison.club1.hit_rate ?? 0, [comparison.club2.name]: comparison.club2.hit_rate ?? 0 },
        { metric: "Composite", [comparison.club1.name]: (comparison.club1.composite_score ?? 0) * 100, [comparison.club2.name]: (comparison.club2.composite_score ?? 0) * 100 },
        { metric: "Value Creation", [comparison.club1.name]: comparison.club1.value_creation ?? 0, [comparison.club2.name]: comparison.club2.value_creation ?? 0 },
      ]
    : [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold">Head-to-Head Comparison</h1>
        <p className="text-base-content/70 mt-1">
          Compare two clubs across all key metrics
        </p>
      </div>

      {/* Club Selectors */}
      <div className="grid md:grid-cols-2 gap-4">
        <ClubSelector label="Club 1" value={club1Id} onSelect={(id) => setClub1Id(id)} />
        <ClubSelector label="Club 2" value={club2Id} onSelect={(id) => setClub2Id(id)} />
      </div>

      {!comparison && !isLoading && (
        <div className="text-center py-12 text-base-content/50">
          Select two clubs to compare them side by side
        </div>
      )}

      {isLoading && (
        <div className="flex justify-center py-12">
          <span className="loading loading-spinner loading-lg" />
        </div>
      )}

      {comparison && (
        <>
          {/* Radar Chart */}
          <section>
            <h2 className="text-xl font-bold mb-4">Metrics Overview</h2>
            <div className="bg-base-200 rounded-xl p-4" style={{ height: 400 }}>
              <ResponsiveRadar
                key={resolvedPrimary + resolvedSecondary}
                data={radarData}
                keys={[comparison.club1.name, comparison.club2.name]}
                indexBy="metric"
                valueFormat=" >+.0f"
                margin={{ top: 40, right: 80, bottom: 40, left: 80 }}
                colors={[resolvedPrimary, resolvedSecondary]}
                borderWidth={2}
                borderColor={{ from: 'color' }}
                fillOpacity={0.15}
                gridLevels={4}
                gridShape="linear"
                gridLabelOffset={12}
                enableDots={true}
                dotSize={8}
                dotColor={{ from: 'color' }}
                dotBorderWidth={2}
                dotBorderColor={{ from: 'color', modifiers: [['darker', 0.5]] }}
                enableDotLabel={false}
                animate={true}
                motionConfig="gentle"
                theme={{
                  background: 'transparent',
                  text: { fill: 'oklch(var(--bc) / 0.7)', fontSize: 12 },
                  axis: {
                    ticks: { text: { fill: 'oklch(var(--bc) / 0.5)', fontSize: 11 } },
                    legend: { text: { fill: 'oklch(var(--bc))', fontSize: 12 } },
                  },
                  grid: {
                    line: { stroke: 'oklch(var(--bc) / 0.25)', strokeWidth: 1 },
                  },
                  dots: {
                    text: { fill: 'oklch(var(--bc) / 0.7)' },
                  },
                  tooltip: {
                    container: {
                      background: 'oklch(var(--b1))',
                      border: '1px solid oklch(var(--bc) / 0.2)',
                      borderRadius: '8px',
                      fontSize: 13,
                      boxShadow: '0 4px 12px oklch(0 0 0 / 0.15)',
                    },
                  },
                }}
                legends={[
                  {
                    anchor: 'bottom-right',
                    direction: 'column',
                    translateX: -200,
                    translateY: -100,
                    itemWidth: 140,
                    itemHeight: 24,
                    itemTextColor: 'oklch(var(--bc) / 0.8)',
                    symbolSize: 10,
                    symbolShape: 'circle',
                    effects: [
                      {
                        on: 'hover',
                        style: { itemTextColor: 'oklch(var(--bc))' },
                      },
                    ],
                  },
                ]}
              />
            </div>
          </section>

          {/* Stat Table */}
          <section>
            <h2 className="text-xl font-bold mb-4">Stat Comparison</h2>
            <div className="overflow-x-auto rounded-xl">
              <table className="table table-zebra">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th className="text-right">{comparison.club1.name}</th>
                    <th className="text-right">{comparison.club2.name}</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: "Composite Score", v1: comparison.club1.composite_score?.toFixed(3), v2: comparison.club2.composite_score?.toFixed(3) },
                    { label: "Median ROI %", v1: comparison.club1.median_roi?.toFixed(1) + "%", v2: comparison.club2.median_roi?.toFixed(1) + "%" },
                    { label: "Total Profit", v1: formatEuro(comparison.club1.total_profit), v2: formatEuro(comparison.club2.total_profit) },
                    { label: "Hit Rate %", v1: comparison.club1.hit_rate?.toFixed(1) + "%", v2: comparison.club2.hit_rate?.toFixed(1) + "%" },
                    { label: "Value Creation %", v1: comparison.club1.value_creation?.toFixed(1) + "%", v2: comparison.club2.value_creation?.toFixed(1) + "%" },
                    { label: "Transfers", v1: String(comparison.club1.total_transfers ?? ""), v2: String(comparison.club2.total_transfers ?? "") },
                  ].map((row) => (
                    <tr key={row.label} className="hover">
                      <td className="font-medium">{row.label}</td>
                      <td className="text-right font-mono">{row.v1 ?? ""}</td>
                      <td className="text-right font-mono">{row.v2 ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Bar Chart */}
          <section>
            <h2 className="text-xl font-bold mb-4">Side-by-Side Metrics</h2>
            <div className="bg-base-200 rounded-xl p-4">
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={radarData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(var(--bc) / 0.15)" />
                  <XAxis dataKey="metric" tick={{ fontSize: 12 }} stroke="oklch(var(--bc) / 0.4)" />
                  <YAxis tick={{ fontSize: 12 }} stroke="oklch(var(--bc) / 0.4)" />
                  <Tooltip
                    contentStyle={{
                      background: "oklch(var(--b1))",
                      border: "1px solid oklch(var(--bc) / 0.2)",
                      borderRadius: "8px",
                    }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: 12, color: 'oklch(var(--bc) / 0.8)' }}
                  />
                  <Bar dataKey={comparison.club2.name} fill={resolvedSecondary} radius={[4, 4, 0, 0]} />
                  <Bar dataKey={comparison.club1.name} fill={resolvedPrimary} radius={[4, 4, 0, 0]}/>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
