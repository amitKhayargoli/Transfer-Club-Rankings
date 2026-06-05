/**
 * Dashboard / Overview page.
 * Shows high-level stats, top clubs, and quick navigation links.
 */

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  fetchDashboardStats,
  fetchTopClubs,
  fetchPipelineStatus,
} from "@/lib/api";

function formatEuro(value: number | null | undefined): string {
  if (value === null || value === undefined) return "€0";
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000_000) return `${sign}€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}€${(abs / 1_000).toFixed(1)}K`;
  return `${sign}€${abs.toFixed(0)}`;
}

export default function DashboardPage() {
  const { data: stats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: fetchDashboardStats,
  });

  const { data: topClubs } = useQuery({
    queryKey: ["top-clubs"],
    queryFn: fetchTopClubs,
  });

  const { data: pipelineStatus } = useQuery({
    queryKey: ["pipeline-status"],
    queryFn: fetchPipelineStatus,
  });

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="hero bg-base-200 rounded-2xl p-8 md:p-12">
        <div className="hero-content text-center">
          <div className="max-w-2xl">
            <h1 className="text-4xl md:text-5xl font-bold">Transfer ROI Rankings</h1>
            <p className="py-4 text-base-content/70 text-lg">
              Which football clubs are the best at buying low and selling high?
              Analyzing every European transfer from 2000–2025.
            </p>
            {pipelineStatus && (
              <div className="badge badge-outline gap-2">
                <div className={`w-2 h-2 rounded-full ${pipelineStatus.data_loaded ? "bg-success" : "bg-warning"}`} />
                {pipelineStatus.total_transfers.toLocaleString()} transfers analyzed
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Transfers</div>
          <div className="stat-value text-primary">
            {stats?.total_transfers?.toLocaleString() ?? "—"}
          </div>
          <div className="stat-desc">Total analyzed</div>
        </div>
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Clubs</div>
          <div className="stat-value text-secondary">
            {stats?.total_clubs?.toLocaleString() ?? "—"}
          </div>
          <div className="stat-desc">Across all leagues</div>
        </div>
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Total Profit</div>
          <div className="stat-value text-accent">
            {formatEuro(stats?.total_profit)}
          </div>
          <div className="stat-desc">Combined club profits</div>
        </div>
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Biggest Profit</div>
          <div className="stat-value text-lg font-bold text-success">
            {stats?.biggest_profit_transfer
              ? formatEuro(stats.biggest_profit_transfer.profit)
              : "—"}
          </div>
          <div className="stat-desc truncate">
            {stats?.biggest_profit_transfer?.player_name ?? ""}
          </div>
        </div>
      </div>

      {/* Top Clubs Spotlight */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-2xl font-bold">🏆 Top Clubs</h2>
          <Link href="/rankings" className="btn btn-outline btn-sm">
            Full Rankings →
          </Link>
        </div>
        <div className="grid md:grid-cols-3 gap-4">
          {topClubs?.top_clubs?.slice(0, 3).map((tc) => (
            <Link
              key={tc.club.club_id}
              href={`/clubs/${tc.club.club_id}`}
              className="card bg-base-200 hover:bg-base-300 transition-colors"
            >
              <div className="card-body">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-primary flex items-center justify-center text-primary-content font-bold">
                    {tc.rank}
                  </div>
                  <div>
                    <h3 className="card-title text-sm">{tc.club.name}</h3>
                    <p className="text-xs text-base-content/60">
                      Score: {tc.club.composite_score?.toFixed(3)}
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2 mt-3 text-center text-xs">
                  <div>
                    <div className="font-bold">{tc.club.median_roi?.toFixed(0) ?? "—"}%</div>
                    <div className="text-base-content/50">ROI</div>
                  </div>
                  <div>
                    <div className="font-bold">{tc.club.hit_rate?.toFixed(0) ?? "—"}%</div>
                    <div className="text-base-content/50">Hit Rate</div>
                  </div>
                  <div>
                    <div className="font-bold">{formatEuro(tc.club.total_profit)}</div>
                    <div className="text-base-content/50">Profit</div>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* Quick Links */}
      <section>
        <h2 className="text-2xl font-bold mb-4">Quick Links</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Link href="/rankings" className="card card-compact bg-base-200 hover:bg-base-300 transition-colors">
            <div className="card-body">
              <h3 className="card-title">📊 Club Rankings</h3>
              <p className="text-sm text-base-content/70">
                Sortable leaderboard of all clubs by ROI, profit, hit rate, and composite score.
              </p>
            </div>
          </Link>
          <Link href="/explorer" className="card card-compact bg-base-200 hover:bg-base-300 transition-colors">
            <div className="card-body">
              <h3 className="card-title">🔍 Transfer Explorer</h3>
              <p className="text-sm text-base-content/70">
                Interactive scatter plot and filters to explore individual transfers.
              </p>
            </div>
          </Link>
          <Link href="/compare" className="card card-compact bg-base-200 hover:bg-base-300 transition-colors">
            <div className="card-body">
              <h3 className="card-title">⚔️ Head-to-Head</h3>
              <p className="text-sm text-base-content/70">
                Side-by-side comparison of any two clubs across all metrics.
              </p>
            </div>
          </Link>
        </div>
      </section>
    </div>
  );
}
