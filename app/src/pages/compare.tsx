/**
 * Head-to-Head Comparison page.
 * Side-by-side comparison of two clubs.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchClubs, compareClubs } from "@/lib/api";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
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
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `€${(abs / 1_000).toFixed(1)}K`;
  return `€${abs.toFixed(0)}`;
}

function ClubSelector({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const { data: searchResults } = useQuery({
    queryKey: ["club-search", value],
    queryFn: () => fetchClubs({ sort_by: "composite_score", sort_order: "desc", per_page: 20 }),
    enabled: value.length > 0,
  });

  return (
    <div className="form-control w-full">
      <label className="label">
        <span className="label-text">{label}</span>
      </label>
      <input
        type="text"
        placeholder="Type a club name..."
        className="input input-bordered w-full"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        list={`clubs-${label}`}
      />
      <datalist id={`clubs-${label}`}>
        {searchResults?.clubs.map((c) => (
          <option key={c.club_id} value={c.name}>
            {c.name}
          </option>
        ))}
      </datalist>
    </div>
  );
}

export default function ComparePage() {
  const [club1Name, setClub1Name] = useState("");
  const [club2Name, setClub2Name] = useState("");
  const [club1Id, setClub1Id] = useState<number | null>(null);
  const [club2Id, setClub2Id] = useState<number | null>(null);

  const { data: clubs } = useQuery({
    queryKey: ["compare-clubs"],
    queryFn: () => fetchClubs({ sort_by: "composite_score", per_page: 200 }),
  });

  const handleSelect = (name: string, setter: (id: number | null) => void) => {
    const match = clubs?.clubs.find(
      (c) => c.name.toLowerCase() === name.toLowerCase()
    );
    if (match) setter(match.club_id);
  };

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
        <ClubSelector label="Club 1" value={club1Name} onChange={(v) => { setClub1Name(v); handleSelect(v, setClub1Id); }} />
        <ClubSelector label="Club 2" value={club2Name} onChange={(v) => { setClub2Name(v); handleSelect(v, setClub2Id); }} />
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
            <div className="bg-base-200 rounded-xl p-4">
              <ResponsiveContainer width="100%" height={350}>
                <RadarChart data={radarData}>
                  <PolarGrid stroke="hsl(var(--bc) / 0.15)" />
                  <PolarAngleAxis dataKey="metric" tick={{ fontSize: 12 }} />
                  <PolarRadiusAxis angle={30} domain={[0, "auto"]} tick={false} />
                  <Radar
                    name={comparison.club1.name}
                    dataKey={comparison.club1.name}
                    stroke="hsl(var(--p))"
                    fill="hsl(var(--p))"
                    fillOpacity={0.2}
                  />
                  <Radar
                    name={comparison.club2.name}
                    dataKey={comparison.club2.name}
                    stroke="hsl(var(--s))"
                    fill="hsl(var(--s))"
                    fillOpacity={0.2}
                  />
                  <Legend />
                </RadarChart>
              </ResponsiveContainer>
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
                    { label: "Transfers", v1: String(comparison.club1.total_transfers ?? "—"), v2: String(comparison.club2.total_transfers ?? "—") },
                  ].map((row) => (
                    <tr key={row.label} className="hover">
                      <td className="font-medium">{row.label}</td>
                      <td className="text-right font-mono">{row.v1 ?? "—"}</td>
                      <td className="text-right font-mono">{row.v2 ?? "—"}</td>
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
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--bc) / 0.1)" />
                  <XAxis dataKey="metric" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{
                      background: "hsl(var(--b1))",
                      border: "1px solid hsl(var(--bc) / 0.2)",
                      borderRadius: "8px",
                    }}
                  />
                  <Legend />
                  <Bar dataKey={comparison.club1.name} fill="hsl(var(--p))" radius={[4, 4, 0, 0]} />
                  <Bar dataKey={comparison.club2.name} fill="hsl(var(--s))" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
