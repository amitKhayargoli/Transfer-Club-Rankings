/**
 * Transfer Explorer page.
 * Interactive scatter plot and filterable transfers table.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { fetchTransfers, clubLogoUrl } from "@/lib/api";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
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

export default function ExplorerPage() {
  const [minRoi, setMinRoi] = useState<number | undefined>(undefined);
  const [yearFrom, setYearFrom] = useState<number | undefined>(undefined);
  const [yearTo, setYearTo] = useState<number | undefined>(undefined);

  const { data: transfersData, isLoading } = useQuery({
    queryKey: ["explorer-transfers", minRoi, yearFrom, yearTo],
    queryFn: () =>
      fetchTransfers({
        min_roi: minRoi,
        year_from: yearFrom,
        year_to: yearTo,
        per_page: 500,
      }),
  });

  const scatterData =
    transfersData?.transfers
      ?.filter((t) => t.transfer_fee != null && t.transfer_fee > 0 && t.roi_pct != null)
      .map((t) => ({
        x: t.transfer_fee!,
        y: t.roi_pct!,
        name: t.player_name ?? "Unknown",
        club: t.to_club_name ?? t.from_club_name ?? "",
        profit: t.profit,
        date: t.transfer_date,
        id: t.transfer_id,
        playerId: t.player_id,
      })) ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Transfer Explorer</h1>
        <p className="text-base-content/70 mt-1">
          Explore individual transfers: buy fee vs ROI
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="form-control">
          <label className="label label-text text-xs">Min ROI %</label>
          <input
            type="number"
            placeholder="Any"
            className="input input-bordered input-sm w-24"
            value={minRoi ?? ""}
            onChange={(e) => setMinRoi(e.target.value ? Number(e.target.value) : undefined)}
          />
        </div>
        <div className="form-control">
          <label className="label label-text text-xs">Year From</label>
          <input
            type="number"
            placeholder="2000"
            className="input input-bordered input-sm w-24"
            value={yearFrom ?? ""}
            onChange={(e) => setYearFrom(e.target.value ? Number(e.target.value) : undefined)}
          />
        </div>
        <div className="form-control">
          <label className="label label-text text-xs">Year To</label>
          <input
            type="number"
            placeholder="2025"
            className="input input-bordered input-sm w-24"
            value={yearTo ?? ""}
            onChange={(e) => setYearTo(e.target.value ? Number(e.target.value) : undefined)}
          />
        </div>
        {(minRoi || yearFrom || yearTo) && (
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setMinRoi(undefined);
              setYearFrom(undefined);
              setYearTo(undefined);
            }}
          >
            Clear Filters
          </button>
        )}
      </div>

      {/* Scatter Plot */}
      <div className="bg-base-200 rounded-xl p-4">
        {scatterData.length === 0 ? (
          <div className="flex justify-center items-center h-[400px] text-base-content/50">
            {isLoading ? (
              <span className="loading loading-spinner loading-md" />
            ) : (
              "No transfers match the filters"
            )}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={400}>
            <ScatterChart margin={{ top: 10, right: 20, bottom: 40, left: 60 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--bc) / 0.1)" />
              <XAxis
                dataKey="x"
                name="Buy Fee"
                tickFormatter={(v) => `€${(v / 1_000_000).toFixed(0)}M`}
                label={{ value: "Buy Fee", position: "bottom", offset: 20 }}
                stroke="hsl(var(--bc) / 0.3)"
              />
              <YAxis
                dataKey="y"
                name="ROI %"
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                label={{ value: "ROI %", angle: -90, position: "insideLeft" }}
                stroke="hsl(var(--bc) / 0.3)"
              />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const d = payload[0].payload;
                  return (
                    <div className="bg-base-100 border border-base-300 rounded-lg p-3 shadow-lg text-sm">
                      <p className="font-bold">{d.name}</p>
                      <p>Fee: {formatEuro(d.x)}</p>
                      <p>ROI: {d.y.toFixed(0)}%</p>
                      <p>Profit: {formatEuro(d.profit)}</p>
                      <p className="text-xs text-base-content/50">{d.date}</p>
                    </div>
                  );
                }}
              />
              <Scatter
                data={scatterData}
                fill="hsl(var(--p))"
                opacity={0.6}
              />
            </ScatterChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Results count */}
      <p className="text-sm text-base-content/50">
        Showing {transfersData?.transfers?.length ?? 0} transfers
      </p>

      {/* Transfers Table */}
      <div className="overflow-x-auto rounded-xl">
        <table className="table table-zebra table-pin-rows">
          <thead>
            <tr className="text-sm">
              <th>Player</th>
              <th>From</th>
              <th>To</th>
              <th>Date</th>
              <th className="text-right">Fee</th>
              <th className="text-right">ROI</th>
              <th className="text-right">Profit</th>
            </tr>
          </thead>
          <tbody>
            {transfersData?.transfers?.map((t) => (
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
                    {t.from_club_name ?? "—"}
                  </span>
                </td>
                <td className="text-sm">
                  <span className="flex items-center gap-1.5">
                    {t.to_club_id && (
                      <img src={clubLogoUrl(t.to_club_id) ?? ""} alt="" className="w-4 h-4 object-contain shrink-0" onError={(e) => { e.currentTarget.style.display = "none"; }} />
                    )}
                    {t.to_club_name ?? "—"}
                  </span>
                </td>
                <td className="text-sm">{t.transfer_date ?? "—"}</td>
                <td className="text-right font-mono text-sm">
                  {formatEuro(t.transfer_fee)}
                </td>
                <td className={`text-right font-mono text-sm ${t.roi_pct && t.roi_pct > 0 ? "text-success" : t.roi_pct && t.roi_pct < 0 ? "text-error" : ""}`}>
                  {t.roi_pct?.toFixed(0) ?? "—"}%
                </td>
                <td className={`text-right font-mono text-sm ${t.profit && t.profit > 0 ? "text-success" : t.profit && t.profit < 0 ? "text-error" : ""}`}>
                  {formatEuro(t.profit)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
