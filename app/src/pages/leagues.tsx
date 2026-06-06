/**
 * Leagues page.
 * Shows league-level spending comparison and per-league club rankings.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { fetchClubs, clubLogoUrl } from "@/lib/api";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";

// ── Helpers ──────────────────────────────────────────────────────────────

function formatEuro(value: number | null | undefined): string {
  if (value === null || value === undefined) return "€0";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${sign}€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}€${(abs / 1_000).toFixed(1)}K`;
  return `${sign}€${abs.toFixed(0)}`;
}

// ── API response types (not exported from api lib yet) ───────────────────

interface LeagueStats {
  id: string;
  name: string;
  total_clubs: number;
  total_transfers: number;
  total_profit: number;
  avg_profit_per_club: number;
}

interface LeagueSpendingResponse {
  leagues: LeagueStats[];
}

async function fetchLeagueSpending() {
  const res = await fetch(`/api/leagues/spending`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json() as Promise<LeagueSpendingResponse>;
}

// ── Page component ───────────────────────────────────────────────────────

export default function LeaguesPage() {
  const [selectedLeague, setSelectedLeague] = useState<string | null>(null);

  // Fetch league-level spending data
  const { data: spendingData, isLoading: spendingLoading } = useQuery({
    queryKey: ["league-spending"],
    queryFn: fetchLeagueSpending,
  });

  // Fetch clubs for the selected league
  const { data: clubsData, isLoading: clubsLoading } = useQuery({
    queryKey: ["league-clubs", selectedLeague],
    queryFn: () =>
      fetchClubs({
        league: selectedLeague!,
        sort_by: "total_profit",
        sort_order: "desc",
        min_transfers: 1,
        per_page: 50,
      }),
    enabled: !!selectedLeague,
  });

  const spending = spendingData?.leagues ?? [];

  // Color gradient from most negative (red) to most positive (green)
  const minProfit = Math.min(...spending.map((l) => l.total_profit), 0);
  const maxProfit = Math.max(...spending.map((l) => l.total_profit), 0);
  const range = maxProfit - minProfit || 1;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">League Spending</h1>
        <p className="text-base-content/70 mt-1">
          Compare net transfer spending across leagues - and see which clubs do
          the best business within each league
        </p>
      </div>

      {/* League Spending Chart */}
      <section>
        <h2 className="text-xl font-bold mb-4">
          Net Transfer Profit/Loss by League
        </h2>
        <p className="text-sm text-base-content/50 mb-4">
          Negative values = net spending (clubs spent more than they earned).
          Positive values = net profit (developed and sold talent).
        </p>
        <div className="bg-base-200 rounded-xl p-4">
          {spendingLoading ? (
            <div className="flex justify-center py-20">
              <span className="loading loading-spinner loading-lg" />
            </div>
          ) : spending.length === 0 ? (
            <div className="text-center py-12 text-base-content/50">
              No league data available
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(300, spending.length * 32)}>
              <BarChart
                data={spending}
                layout="vertical"
                margin={{ top: 5, right: 40, bottom: 5, left: 120 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="oklch(var(--bc) / 0.1)"
                  horizontal={false}
                />
                <XAxis
                  type="number"
                  tickFormatter={(v) => formatEuro(v)}
                  tick={{ fontSize: 11, fill: "oklch(var(--bc) / 0.6)" }}
                  stroke="oklch(var(--bc) / 0.2)"
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "oklch(var(--bc) / 0.7)" }}
                  stroke="oklch(var(--bc) / 0.2)"
                  width={115}
                />
                <Tooltip
                  formatter={(value) => [
                    formatEuro(Number(value)),
                    "Net Profit/Loss",
                  ]}
                  labelFormatter={(label) => String(label)}
                  contentStyle={{
                    background: "oklch(var(--b1))",
                    border: "1px solid oklch(var(--bc) / 0.2)",
                    borderRadius: "8px",
                    fontSize: 13,
                  }}
                />
                <Bar
                  dataKey="total_profit"
                  radius={[0, 4, 4, 0]}
                  onClick={(entry: { id?: string }) =>
                    entry?.id && setSelectedLeague(entry.id)
                  }
                  style={{ cursor: "pointer" }}
                >
                  {spending.map((entry, index) => {
                    const ratio = (entry.total_profit - minProfit) / range;
                    // Red (spending) -> gray (break-even) -> green (profit)
                    const r = Math.round(255 * (1 - ratio));
                    const g = Math.round(255 * ratio);
                    return (
                      <Cell
                        key={entry.id}
                        fill={`oklch(
                          ${0.5 + ratio * 0.2}
                          ${0.15 + Math.abs(ratio - 0.5) * 0.15}
                          ${entry.total_profit < 0 ? 25 : 145}
                        )`}
                      />
                    );
                  })}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        <p className="text-xs text-base-content/40 mt-2 text-center">
          Click a bar to see club-level breakdown for that league
        </p>
      </section>

      {/* Per-League Club Rankings */}
      {selectedLeague && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold">
              {spending.find((l) => l.id === selectedLeague)?.name ??
                selectedLeague}{" "}
              - Clubs Ranked by Net Business
            </h2>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setSelectedLeague(null)}
            >
              Close
            </button>
          </div>
          <p className="text-sm text-base-content/50 mb-4">
            Clubs ranked by total profit from transfers (highest profit = best
            business; most negative = biggest spenders)
          </p>
          <div className="overflow-x-auto rounded-xl">
            <table className="table table-zebra table-pin-rows">
              <thead>
                <tr className="text-sm">
                  <th>#</th>
                  <th>Club</th>
                  <th className="text-right">Transfers</th>
                  <th className="text-right">Total Profit</th>
                  <th className="text-right">Avg Profit / Deal</th>
                  <th className="text-right">Hit Rate</th>
                </tr>
              </thead>
              <tbody>
                {clubsLoading ? (
                  <tr>
                    <td colSpan={6} className="text-center py-12">
                      <span className="loading loading-spinner loading-md" />
                    </td>
                  </tr>
                ) : !clubsData?.clubs?.length ? (
                  <tr>
                    <td colSpan={6} className="text-center py-12 text-base-content/50">
                      No club data for this league
                    </td>
                  </tr>
                ) : (
                  clubsData.clubs.map((club, i) => (
                    <tr key={club.club_id} className="hover">
                      <td className="font-mono text-xs text-base-content/50">{i + 1}</td>
                      <td>
                        <Link
                          href={`/clubs/${club.club_id}`}
                          className="flex items-center gap-2 font-medium hover:text-primary transition-colors"
                        >
                          <img
                            src={clubLogoUrl(club.club_id) ?? ""}
                            alt=""
                            className="w-5 h-5 object-contain shrink-0"
                            onError={(e) => {
                              e.currentTarget.style.display = "none";
                            }}
                          />
                          {club.name}
                        </Link>
                      </td>
                      <td className="text-right font-mono text-sm">
                        {club.total_transfers ?? ""}
                      </td>
                      <td
                        className={`text-right font-mono text-sm ${
                          club.total_profit && club.total_profit > 0
                            ? "text-success"
                            : club.total_profit && club.total_profit < 0
                              ? "text-error"
                              : ""
                        }`}
                      >
                        {formatEuro(club.total_profit)}
                      </td>
                      <td className="text-right font-mono text-sm text-base-content/70">
                        {club.profit_per_deal != null
                          ? formatEuro(club.profit_per_deal)
                          : club.total_profit != null && club.total_transfers
                            ? formatEuro(club.total_profit / club.total_transfers)
                            : ""}
                      </td>
                      <td className="text-right font-mono text-sm">
                        {club.hit_rate?.toFixed(1) ?? ""}%
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
