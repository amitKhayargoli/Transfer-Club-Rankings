/**
 * Head-to-Head Comparison page.
 * Side-by-side comparison of two clubs.
 */

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { compareClubs, fetchMetricsStats, clubLogoUrl, unifiedSearch } from "@/lib/api";
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
import Link from "next/link";

function formatEuro(value: number | null | undefined): string {
  if (value === null || value === undefined) return "€0";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${sign}€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}€${(abs / 1_000).toFixed(1)}K`;
  return `${sign}€${abs.toFixed(0)}`;
}

// Rescale: z in [-3, 3] → (z + 3) / 6 gives [0, 1] where 0.5 = mean
// Used by radar, stat table, and bar chart so all three show the same number.
function rescaleScore(z: number): number {
  return (z + 3) / 6;
}

function scoreColor(score: number): string {
  // score is 0-1 where 0.5 = average
  if (score >= 0.75) return "text-success font-bold";
  if (score >= 0.583) return "text-success/70";
  if (score >= 0.417) return "text-base-content/60";
  if (score >= 0.25) return "text-warning/70";
  return "text-error font-bold";
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

  // Fetch population stats for Z-score normalization of the radar chart
  const { data: metricStats } = useQuery({
    queryKey: ["metric-stats"],
    queryFn: fetchMetricsStats,
    staleTime: 5 * 60 * 1000, // Re-fetch every 5 min at most
  });

  const { data: comparison, isLoading } = useQuery({
    queryKey: ["comparison", club1Id, club2Id],
    queryFn: () => compareClubs([club1Id!, club2Id!]),
    enabled: !!club1Id && !!club2Id,
  });

  // Z-score normalize a raw value: (value - mean) / std, clipped to +/-3.
  // Falls back to raw value if stats aren't loaded yet.
  function clippedZScore(raw: number | null | undefined, metric: string, fallback: number = 0): number {
    const stats = metricStats?.[metric];
    if (stats && stats.std > 0 && raw != null) {
      const z = (raw - stats.mean) / stats.std;
      return Math.max(-3, Math.min(3, z));
    }
    return raw ?? fallback;
  }

  // Build radar chart data with values rescaled to [0, 1] where 0.5 = population mean.
  // The radar chart only supports positive values, so we rescale z-scores [-3, +3] → [0, 1].
  const radarData = useMemo(() => {
    if (!comparison) return [];
    const c1 = comparison.club1;
    const c2 = comparison.club2;
    // Rescale: z in [-3, 3] → (z + 3) / 6 gives [0, 1] where 0.5 = mean
    const rescale = (raw: number | null | undefined, metric: string) => {
      const z = clippedZScore(raw, metric);
      return (z + 3) / 6;
    };
    return [
      { metric: "Median ROI", [c1.name]: rescale(c1.median_roi, "median_roi"), [c2.name]: rescale(c2.median_roi, "median_roi") },
      { metric: "Hit Rate", [c1.name]: rescale(c1.hit_rate, "hit_rate"), [c2.name]: rescale(c2.hit_rate, "hit_rate") },
      { metric: "Value Creation", [c1.name]: rescale(c1.value_creation, "value_creation"), [c2.name]: rescale(c2.value_creation, "value_creation") },
      { metric: "Annualized ROI", [c1.name]: rescale(c1.annualized_roi, "annualized_roi"), [c2.name]: rescale(c2.annualized_roi, "annualized_roi") },
      { metric: "Composite", [c1.name]: rescale(c1.composite_score, "composite_score"), [c2.name]: rescale(c2.composite_score, "composite_score") },
    ];
  }, [comparison, metricStats]);

  type ClubDict = Record<string, any>;

  // Helper: format raw values for tooltip display
  const formatRaw = useCallback((metric: string, club: ClubDict): string => {
    const val = club[metric];
    switch (metric) {
      case "median_roi":
      case "annualized_roi":
        return val != null ? `${val.toFixed(1)}%` : "—";
      case "hit_rate":
      case "value_creation":
        return val != null ? `${val.toFixed(1)}%` : "—";
      case "total_profit":
      case "profit_per_deal":
        return formatEuro(val);
      case "composite_score":
        return val != null ? val.toFixed(3) : "—";
      default:
        return val != null ? `${val}` : "—";
    }
  }, []);

  // Build bar chart data with raw values embedded for tooltips
  const barData = useMemo(() => {
    if (!comparison) return [];
    const c1 = comparison.club1 as ClubDict;
    const c2 = comparison.club2 as ClubDict;
    const metrics = [
      { bar: "Median ROI", key: "median_roi" },
      { bar: "Hit Rate", key: "hit_rate" },
      { bar: "Value Creation", key: "value_creation" },
      { bar: "Annualized ROI", key: "annualized_roi" },
      { bar: "Composite", key: "composite_score" },
    ];
    return metrics.map((m) => {
      const z1 = clippedZScore(c1[m.key], m.key);
      const z2 = clippedZScore(c2[m.key], m.key);
      return {
        metric: m.bar,
        [c1.name]: rescaleScore(z1),
        [c2.name]: rescaleScore(z2),
        [`_raw_${c1.name}`]: formatRaw(m.key, c1),
        [`_raw_${c2.name}`]: formatRaw(m.key, c2),
      };
    });
  }, [comparison, metricStats]);

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
                valueFormat=" >.2f"
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
            <p className="text-xs text-base-content/50 mb-3">Raw values with comparison scores showing how each club compares to the <strong>2015+ population</strong> (0.50 = average, 1.00 = best, 0.00 = worst)</p>
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
                    { label: "Composite Score", raw1: comparison.club1.composite_score?.toFixed(3), raw2: comparison.club2.composite_score?.toFixed(3), s1: rescaleScore(clippedZScore(comparison.club1.composite_score, "composite_score")), s2: rescaleScore(clippedZScore(comparison.club2.composite_score, "composite_score")) },
                    { label: "Median ROI", raw1: comparison.club1.median_roi?.toFixed(1) + "%", raw2: comparison.club2.median_roi?.toFixed(1) + "%", s1: rescaleScore(clippedZScore(comparison.club1.median_roi, "median_roi")), s2: rescaleScore(clippedZScore(comparison.club2.median_roi, "median_roi")) },
                    { label: "Total Profit", raw1: formatEuro(comparison.club1.total_profit), raw2: formatEuro(comparison.club2.total_profit), s1: rescaleScore(clippedZScore(comparison.club1.total_profit, "total_profit")), s2: rescaleScore(clippedZScore(comparison.club2.total_profit, "total_profit")) },
                    { label: "Profit / Deal", raw1: formatEuro(comparison.club1.profit_per_deal), raw2: formatEuro(comparison.club2.profit_per_deal), s1: rescaleScore(clippedZScore(comparison.club1.profit_per_deal, "profit_per_deal")), s2: rescaleScore(clippedZScore(comparison.club2.profit_per_deal, "profit_per_deal")) },
                    { label: "Hit Rate", raw1: comparison.club1.hit_rate?.toFixed(1) + "%", raw2: comparison.club2.hit_rate?.toFixed(1) + "%", s1: rescaleScore(clippedZScore(comparison.club1.hit_rate, "hit_rate")), s2: rescaleScore(clippedZScore(comparison.club2.hit_rate, "hit_rate")) },
                    { label: "Value Creation", raw1: comparison.club1.value_creation?.toFixed(1) + "%", raw2: comparison.club2.value_creation?.toFixed(1) + "%", s1: rescaleScore(clippedZScore(comparison.club1.value_creation, "value_creation")), s2: rescaleScore(clippedZScore(comparison.club2.value_creation, "value_creation")) },
                    { label: "Annualized ROI", raw1: comparison.club1.annualized_roi?.toFixed(1) + "%", raw2: comparison.club2.annualized_roi?.toFixed(1) + "%", s1: rescaleScore(clippedZScore(comparison.club1.annualized_roi, "annualized_roi")), s2: rescaleScore(clippedZScore(comparison.club2.annualized_roi, "annualized_roi")) },
                    { label: "Transfers", raw1: String(comparison.club1.total_transfers ?? ""), raw2: String(comparison.club2.total_transfers ?? ""), s1: null, s2: null },
                    { label: "Buying Premium", raw1: comparison.club1.buying_club_premium?.toFixed(1) + "%", raw2: comparison.club2.buying_club_premium?.toFixed(1) + "%", s1: null, s2: null },
                  ].map((row) => (
                    <tr key={row.label} className="hover">
                      <td className="font-medium">{row.label}</td>
                      <td className={`text-right font-mono ${row.s1 != null ? scoreColor(row.s1) : ""}`}>
                        {row.raw1 ?? ""}
                        {row.s1 != null && (
                          <span className="block text-[10px] leading-none font-semibold opacity-70">
                            {row.s1.toFixed(3)}
                          </span>
                        )}
                      </td>
                      <td className={`text-right font-mono ${row.s2 != null ? scoreColor(row.s2) : ""}`}>
                        {row.raw2 ?? ""}
                        {row.s2 != null && (
                          <span className="block text-[10px] leading-none font-semibold opacity-70">
                            {row.s2.toFixed(3)}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}

                  {/* Best Sale row */}
                  {[comparison.club1, comparison.club2].some(c => c.top_sale) && (
                    <tr className="hover border-t-2 border-base-300">
                      <td className="font-medium">
                        <span className="flex items-center gap-1.5">
                          <svg className="w-4 h-4 text-warning" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
                          </svg>
                          Best Sale
                        </span>
                      </td>
                      <td className="text-right">
                        {comparison.club1.top_sale ? (
                          <>
                            <Link
                              href={`/players/${comparison.club1.top_sale.player_id}`}
                              className="link link-hover text-sm font-medium"
                            >
                              {comparison.club1.top_sale.player_name}
                            </Link>
                            <span className="block text-xs text-success font-semibold font-mono">
                              +{formatEuro(comparison.club1.top_sale.profit)}
                            </span>
                            <span className="block text-[10px] text-base-content/70 font-semibold font-mono">
                              {comparison.club1.top_sale.roi_pct?.toFixed(0)}% ROI
                            </span>
                          </>
                        ) : (
                          <span className="text-base-content/40 text-xs">—</span>
                        )}
                      </td>
                      <td className="text-right">
                        {comparison.club2.top_sale ? (
                          <>
                            <Link
                              href={`/players/${comparison.club2.top_sale.player_id}`}
                              className="link link-hover text-sm font-medium"
                            >
                              {comparison.club2.top_sale.player_name}
                            </Link>
                            <span className="block text-xs text-success font-semibold font-mono">
                              +{formatEuro(comparison.club2.top_sale.profit)}
                            </span>
                            <span className="block text-[10px] text-base-content/70 font-semibold font-mono">
                              {comparison.club2.top_sale.roi_pct?.toFixed(0)}% ROI
                            </span>
                          </>
                        ) : (
                          <span className="text-base-content/40 text-xs">—</span>
                        )}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          {/* Bar Chart (rescaled scores — matches radar chart) */}
          <section>
            <h2 className="text-xl font-bold mb-4">Side-by-Side Scores</h2>
            <div className="bg-base-200 rounded-xl p-4">
              <p className="text-xs text-base-content/50 mb-2">Rescaled comparison scores (0.50 = average, 1.00 = best, 0.00 = worst). Hover for raw values.</p>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={barData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(var(--bc) / 0.15)" />
                  <XAxis dataKey="metric" tick={{ fontSize: 12 }} stroke="oklch(var(--bc) / 0.4)" />
                  <YAxis tick={{ fontSize: 12 }} stroke="oklch(var(--bc) / 0.4)" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} />
                  <Tooltip
                    content={({ active, payload, label }) => {
                      if (!active || !payload || payload.length === 0) return null;
                      return (
                        <div className="bg-base-100 border border-base-300 rounded-lg shadow-lg px-3 py-2 text-sm">
                          <p className="font-bold mb-1">{label}</p>
                          {payload.map((entry: any) => {
                            const cName = entry.name;
                            const rawKey = `_raw_${cName}`;
                            const rawVal = entry.payload?.[rawKey];
                            return (
                              <div key={cName} className="flex items-center gap-3 py-0.5">
                                <span
                                  className="w-3 h-3 rounded-full shrink-0"
                                  style={{ background: entry.color }}
                                />
                                <span className="font-medium">{cName}</span>
                                <span className="font-mono ml-auto">
                                  {entry.value?.toFixed(3)}
                                </span>
                                {rawVal && (
                                  <span className="text-[10px] text-base-content/70 font-semibold font-mono min-w-[60px] text-right">
                                    ({rawVal})
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      );
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

          {/* How to Read Section */}
          <section className="bg-base-200 rounded-xl p-5">
            <h3 className="font-bold mb-2 text-sm">How to Read This Page</h3>
            <div className="grid md:grid-cols-3 gap-4 text-xs text-base-content/70">
              <div>
                <span className="font-semibold text-base-content block mb-1">📊 Radar Chart</span>
                Shows relative strengths across metrics. 0.50 = population average, 1.00 = best (±3σ), 0.00 = worst (−3σ). A balanced shape means no major weaknesses.
              </div>
              <div>
                <span className="font-semibold text-base-content block mb-1">📋 Stat Table</span>
                Raw values are the actual numbers. The score beneath each value uses the same 0–1 scale as the radar and bar chart — higher is better.
              </div>
              <div>
                <span className="font-semibold text-base-content block mb-1">📈 Score Guide</span>
                <span className="text-success font-bold">≥ 0.75</span> = Strong &nbsp;|&nbsp;
                <span className="text-base-content/60">≈ 0.50</span> = Average &nbsp;|&nbsp;
                <span className="text-error font-bold">≤ 0.25</span> = Weak
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
