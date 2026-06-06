/**
 * Club Detail page.
 * Shows club metrics, transfer history, and top/bottom transfers.
 */

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/router";
import Link from "next/link";
import { fetchClub, fetchClubTransfers, clubLogoUrl, leagueLogoUrl } from "@/lib/api";

function calcProfit(t: { profit?: number | null; sell_fee?: number | null; buy_fee?: number | null }): number | null {
  if (t.profit != null) return t.profit;
  if (t.sell_fee != null && t.buy_fee != null) return t.sell_fee - t.buy_fee;
  return null;
}

function calcRoi(t: { roi_pct?: number | null; profit?: number | null; sell_fee?: number | null; buy_fee?: number | null }): number | null {
  if (t.roi_pct != null) return t.roi_pct;
  if (t.sell_fee != null && t.buy_fee != null && t.buy_fee > 0) {
    return ((t.sell_fee - t.buy_fee) / t.buy_fee) * 100;
  }
  return null;
}

function badgeClass(type: string | null | undefined): string {
  switch (type) {
    case "paid": return "badge badge-success badge-xs";
    case "loan": return "badge badge-info badge-xs";
    case "youth_promotion": return "badge badge-secondary badge-xs";
    case "sent_to_reserves": return "badge badge-accent badge-xs";
    case "contract_expired": return "badge badge-warning badge-xs";
    case "retired": return "badge badge-error badge-xs";
    case "free_transfer": return "badge badge-ghost badge-xs";
    default: return "badge badge-ghost badge-xs";
  }
}

function badgeLabel(type: string | null | undefined): string {
  switch (type) {
    case "paid": return "Paid";
    case "loan": return "Loan";
    case "youth_promotion": return "Youth";
    case "sent_to_reserves": return "Reserves";
    case "contract_expired": return "Expired";
    case "retired": return "Retired";
    case "free_transfer": return "Free";
    default: return "";
  }
}

function formatEuro(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${sign}€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}€${(abs / 1_000).toFixed(1)}K`;
  return `${sign}€${abs.toFixed(0)}`;
}

const TYPE_OPTIONS = [
  { key: "paid", label: "Paid", cls: "badge-success" },
  { key: "loan", label: "Loan", cls: "badge-info" },
  { key: "free_transfer", label: "Free", cls: "badge-ghost" },
  { key: "youth_promotion", label: "Youth", cls: "badge-secondary" },
  { key: "sent_to_reserves", label: "Reserves", cls: "badge-accent" },
  { key: "contract_expired", label: "Expired", cls: "badge-warning" },
  { key: "retired", label: "Retired", cls: "badge-error" },
] as const;

export default function ClubDetailPage() {
  const router = useRouter();
  const { id } = router.query;
  const clubId = Number(id);

  const [sortBy, setSortBy] = useState<"date" | "fee_desc" | "fee_asc">("date");
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set());

  const toggleType = (type: string) => {
    setActiveTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const { data: club, isLoading: clubLoading } = useQuery({
    queryKey: ["club", clubId],
    queryFn: () => fetchClub(clubId),
    enabled: !!clubId,
  });

  const { data: transfers } = useQuery({
    queryKey: ["club-transfers", clubId],
    queryFn: () => fetchClubTransfers(clubId, 1, 100),
    enabled: !!clubId,
  });

  const filteredTransfers = useMemo(() => {
    if (!transfers?.transfers) return [];
    const list = activeTypes.size === 0
      ? [...transfers.transfers]
      : transfers.transfers.filter((t) => activeTypes.has(t.transfer_type ?? ""));

    if (sortBy === "fee_desc") {
      list.sort((a, b) => (b.transfer_fee ?? 0) - (a.transfer_fee ?? 0));
    } else if (sortBy === "fee_asc") {
      list.sort((a, b) => (a.transfer_fee ?? 0) - (b.transfer_fee ?? 0));
    } else {
      list.sort((a, b) => {
        const da = a.transfer_date ?? "";
        const db = b.transfer_date ?? "";
        return db.localeCompare(da);
      });
    }
    return list;
  }, [transfers?.transfers, sortBy, activeTypes]);

  if (clubLoading) {
    return (
      <div className="flex justify-center py-20">
        <span className="loading loading-spinner loading-lg" />
      </div>
    );
  }

  if (!club) {
    return (
      <div className="text-center py-20">
        <h2 className="text-2xl font-bold">Club not found</h2>
        <Link href="/rankings" className="btn btn-primary mt-4">
          Back to Rankings
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Club Header */}
      <div className="flex items-start gap-5">
        <div className="w-20 h-20 rounded-2xl bg-base-200 flex items-center justify-center shrink-0 overflow-hidden p-2">
          <img
            src={clubLogoUrl(club.club_id, 'head') ?? ""}
            alt={club.name}
            className="w-full h-full object-contain"
            onError={(e) => {
              // Fallback to first letter if logo fails to load
              const target = e.currentTarget;
              target.style.display = "none";
              target.parentElement!.classList.add("bg-primary", "text-primary-content", "text-2xl", "font-bold");
              target.parentElement!.textContent = club.name.charAt(0);
            }}
          />
        </div>
        <div>
          <h1 className="text-3xl font-bold">{club.name}</h1>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <span className="badge badge-outline !p-3">
              Score: {club.composite_score?.toFixed(3) ?? ""}
            </span>
            {club.domestic_competition_id && (
              <span className="badge badge-outline flex items-center gap-1.5 !p-3">
                {club.league_name && (
                  <img
                    src={leagueLogoUrl(club.domestic_competition_id) ?? ""}
                    alt=""
                    className="w-4 h-4 object-contain"
                    onError={(e) => { e.currentTarget.style.display = "none"; }}
                  />
                )}
                {club.league_name ?? club.domestic_competition_id}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Median ROI</div>
          <div className={`stat-value text-lg ${club.median_roi && club.median_roi > 0 ? "text-success" : "text-error"}`}>
            {club.median_roi?.toFixed(1) ?? ""}%
          </div>
        </div>
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Total Profit</div>
          <div className="stat-value text-lg">{formatEuro(club.total_profit)}</div>
        </div>
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Hit Rate</div>
          <div className="stat-value text-lg">{club.hit_rate?.toFixed(1) ?? ""}%</div>
        </div>
        <div className="stat bg-base-200 rounded-xl">
          <div className="stat-title">Transfers</div>
          <div className="stat-value text-lg">{club.total_transfers ?? ""}</div>
        </div>
      </div>

      {/* Transfers Table */}
      <section>
        <h2 className="text-xl font-bold mb-4">Transfer History</h2>

        {/* Sort controls */}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-xs font-medium text-base-content/60 mr-1">Sort:</span>
          <button
            className={`btn btn-xs ${sortBy === "date" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setSortBy("date")}
          >
            Date
          </button>
          <button
            className={`btn btn-xs ${sortBy === "fee_desc" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setSortBy("fee_desc")}
          >
            Fee ↓
          </button>
          <button
            className={`btn btn-xs ${sortBy === "fee_asc" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setSortBy("fee_asc")}
          >
            Fee ↑
          </button>
        </div>

        {/* Type filter chips */}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-xs font-medium text-base-content/60 mr-1">Filter:</span>
          {TYPE_OPTIONS.map((opt) => {
            const active = activeTypes.has(opt.key);
            return (
              <button
                key={opt.key}
                className={`badge badge-sm cursor-pointer transition-all !p-3 ${
                  active ? opt.cls + " badge-outline scale-110" : "badge-ghost opacity-60"
                }`}
                onClick={() => toggleType(opt.key)}
              >
                {opt.label}
                {active && (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3 ml-0.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                )}
              </button>
            );
          })}
          {activeTypes.size > 0 && (
            <button className="btn btn-ghost btn-xs" onClick={() => setActiveTypes(new Set())}>
              Clear
            </button>
          )}
        </div>

        <div className="text-xs text-base-content/50 mb-2">
          Showing {filteredTransfers.length} of {transfers?.transfers?.length ?? 0} transfers
        </div>

        <div className="overflow-x-auto rounded-xl">
          <table className="table table-zebra table-pin-rows">
            <thead>
              <tr className="text-sm">
                <th>Player</th>
                <th>From</th>
                <th>To</th>
                <th>Date</th>
                <th>Type</th>
                <th className="text-right">Fee</th>
                <th className="text-right">Profit</th>
                <th className="text-right">ROI</th>
              </tr>
            </thead>
            <tbody>
              {filteredTransfers.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-8 text-base-content/50">
                    No transfers match the selected filters
                  </td>
                </tr>
              ) : (
                filteredTransfers.map((t) => (
                  <tr key={t.transfer_id} className="hover">
                    <td>
                      <Link
                        href={`/players/${t.player_id}`}
                        className="font-medium hover:text-primary transition-colors"
                      >
                        {t.player_name ?? "Unknown"}
                      </Link>
                    </td>
                    <td className="text-sm">
                      <span className="flex items-center gap-1.5">
                        {t.from_club_id && (
                          <img src={clubLogoUrl(t.from_club_id) ?? ""} alt="" className="w-4 h-4 object-contain shrink-0" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                        )}
                        {t.from_club_name ?? ""}
                      </span>
                    </td>
                    <td className="text-sm">
                      <span className="flex items-center gap-1.5">
                        {t.to_club_id && (
                          <img src={clubLogoUrl(t.to_club_id) ?? ""} alt="" className="w-4 h-4 object-contain shrink-0" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                        )}
                        {t.to_club_name ?? ""}
                      </span>
                    </td>
                    <td className="text-sm">{t.transfer_date ?? ""}</td>
                    <td>
                      <span className={badgeClass(t.transfer_type)}>{badgeLabel(t.transfer_type)}</span>
                    </td>
                    <td className="text-right font-mono text-sm">
                      {formatEuro(t.transfer_fee)}
                    </td>
                    <td className={`text-right font-mono text-sm ${calcProfit(t) && calcProfit(t)! > 0 ? "text-success" : calcProfit(t) && calcProfit(t)! < 0 ? "text-error" : ""}`}>
                      {calcProfit(t) != null ? formatEuro(calcProfit(t)!) : ""}
                    </td>
                    <td className={`text-right font-mono text-sm ${calcRoi(t) && calcRoi(t)! > 0 ? "text-success" : calcRoi(t) && calcRoi(t)! < 0 ? "text-error" : ""}`}>
                      {calcRoi(t)?.toFixed(0) ?? ""}%
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
