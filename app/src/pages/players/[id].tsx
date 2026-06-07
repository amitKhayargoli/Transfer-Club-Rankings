/**
 * Player Detail page.
 * Shows player info, transfer history, and market value over time.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/router";
import Link from "next/link";
import {
  fetchPlayer,
  fetchPlayerTransfers,
  fetchPlayerValuations,
  clubLogoUrl,
  playerImageUrl,
} from "@/lib/api";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

function calcProfit(t: { profit?: number | null; sell_fee?: number | null; buy_fee?: number | null }): number | null {
  if (t.profit != null) return t.profit;
  if (t.sell_fee != null && t.buy_fee != null) return t.sell_fee - t.buy_fee;
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

function calcRoi(t: { roi_pct?: number | null; profit?: number | null; sell_fee?: number | null; buy_fee?: number | null }): number | null {
  if (t.roi_pct != null) return t.roi_pct;
  if (t.sell_fee != null && t.buy_fee != null && t.buy_fee > 0) {
    return ((t.sell_fee - t.buy_fee) / t.buy_fee) * 100;
  }
  return null;
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

export default function PlayerDetailPage() {
  const router = useRouter();
  const { id } = router.query;
  const playerId = Number(id);

  // Must be before any early return (React hooks rule)
  const [playerImgError, setPlayerImgError] = useState(false);

  const { data: player, isLoading } = useQuery({
    queryKey: ["player", playerId],
    queryFn: () => fetchPlayer(playerId),
    enabled: !!playerId,
  });

  const { data: transfers } = useQuery({
    queryKey: ["player-transfers", playerId],
    queryFn: () => fetchPlayerTransfers(playerId),
    enabled: !!playerId,
  });

  const { data: valuations } = useQuery({
    queryKey: ["player-valuations", playerId],
    queryFn: () => fetchPlayerValuations(playerId),
    enabled: !!playerId,
  });

  if (isLoading) {
    return (
      <div className="flex justify-center py-20">
        <span className="loading loading-spinner loading-lg" />
      </div>
    );
  }

  if (!player) {
    return (
      <div className="text-center py-20">
        <h2 className="text-2xl font-bold">Player not found</h2>
        <Link href="/" className="btn btn-primary mt-4">
          Back to Dashboard
        </Link>
      </div>
    );
  }

  const playerImgUrl = playerImageUrl(playerId, "medium", player?.image_url);

  return (
    <div className="space-y-8">
      {/* Player Header */}
      <div className="flex items-start gap-5">
        <div className="w-24 h-24 md:w-28 md:h-28 rounded-2xl shrink-0 overflow-hidden bg-base-200 flex items-center justify-center">
          {!playerImgError && playerImgUrl ? (
            <img
              src={playerImgUrl}
              alt={player.name}
              className="w-full h-full object-cover"
              onError={() => setPlayerImgError(true)}
            />
          ) : (
            <span className="text-3xl font-bold text-primary">
              {player.name.charAt(0)}
            </span>
          )}
        </div>
        <div>
          <h1 className="text-3xl font-bold">{player.name}</h1>
          <div className="flex flex-wrap gap-2 mt-2">
            {player.position && <span className="badge badge-outline !p-3">{player.position}</span>}
            {player.current_club_name && (
              <span className="badge badge-outline !p-3">{player.current_club_name}</span>
            )}
          </div>
        </div>
      </div>

      {/* Player Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {player.height_in_cm && (
          <div className="stat bg-base-200 rounded-xl">
            <div className="stat-title">Height</div>
            <div className="stat-value text-lg">{player.height_in_cm} cm</div>
          </div>
        )}
        {player.foot && (
          <div className="stat bg-base-200 rounded-xl">
            <div className="stat-title">Foot</div>
            <div className="stat-value text-lg capitalize">{player.foot}</div>
          </div>
        )}
        {player.market_value_in_eur != null && (
          <div className="stat bg-base-200 rounded-xl">
            <div className="stat-title">Market Value</div>
            <div className="stat-value text-lg">{formatEuro(player.market_value_in_eur)}</div>
          </div>
        )}
        {player.highest_market_value_in_eur != null && (
          <div className="stat bg-base-200 rounded-xl">
            <div className="stat-title">Peak Value</div>
            <div className="stat-value text-lg">{formatEuro(player.highest_market_value_in_eur)}</div>
          </div>
        )}
      </div>

      {/* Market Value Chart */}
      {valuations && valuations.length > 0 && (
        <section>
          <h2 className="text-xl font-bold mb-4">Market Value Over Time</h2>
          <div className="bg-base-200 rounded-xl p-4">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={valuations}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--bc) / 0.1)" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12, fill: '#ffffff' }}
                  stroke="#ffffff"
                />
                <YAxis
                  tickFormatter={(v) => `€${(v / 1_000_000).toFixed(0)}M`}
                  tick={{ fontSize: 12, fill: '#ffffff' }}
                  stroke="#ffffff"
                />
                <Tooltip
                  formatter={(value) => [formatEuro(Number(value)), "Market Value"]}
                  contentStyle={{
                    background: "hsl(var(--b1))",
                    border: "1px solid hsl(var(--bc) / 0.2)",
                    borderRadius: "8px",
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="market_value_in_eur"
                  stroke="hsl(var(--p))"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Transfer History */}
      <section>
        <h2 className="text-xl font-bold mb-4">Transfer History</h2>
        <div className="overflow-x-auto rounded-xl">
          <table className="table table-zebra table-pin-rows">
            <thead>
              <tr className="text-sm">
                <th>Date</th>
                <th>From</th>
                <th>To</th>
                <th>Type</th>
                <th className="text-right">Fee</th>
                <th className="text-right">Profit</th>
                <th className="text-right">ROI</th>
              </tr>
            </thead>
            <tbody>
              {transfers?.map((t) => (
                <tr key={t.transfer_id} className="hover">
                  <td className="text-sm">{t.transfer_date ?? ""}</td>
                  <td>
                    {t.from_club_id ? (
                      <Link href={`/clubs/${t.from_club_id}`} className="hover:text-primary transition-colors flex items-center gap-1.5">
                        <img
                          src={clubLogoUrl(t.from_club_id) ?? ""}
                          alt=""
                          className="w-4 h-4 object-contain shrink-0"
                          onError={(e) => { e.currentTarget.style.display = "none"; }}
                        />
                        {t.from_club_name ?? ""}
                      </Link>
                    ) : (
                      t.from_club_name ?? ""
                    )}
                  </td>
                  <td>
                    {t.to_club_id ? (
                      <Link href={`/clubs/${t.to_club_id}`} className="hover:text-primary transition-colors flex items-center gap-1.5">
                        <img
                          src={clubLogoUrl(t.to_club_id) ?? ""}
                          alt=""
                          className="w-4 h-4 object-contain shrink-0"
                          onError={(e) => { e.currentTarget.style.display = "none"; }}
                        />
                        {t.to_club_name ?? ""}
                      </Link>
                    ) : (
                      t.to_club_name ?? ""
                    )}
                  </td>
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
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
