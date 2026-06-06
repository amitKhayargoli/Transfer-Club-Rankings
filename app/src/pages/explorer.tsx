/**
 * Transfer Explorer page.
 * Interactive scatter plot and filterable transfers table.
 * Supports player name search, club search, position filter, league filter,
 * min ROI, and year range filters.
 */

import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  fetchTransfers,
  unifiedSearch,
  clubLogoUrl,
  SearchResult,
} from "@/lib/api";
import PositionPicker from "@/components/PositionPicker";
import LeaguePicker from "@/components/LeaguePicker";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
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

// ── Club Search Combobox ────────────────────────────────────────────────

function ClubSearch({
  value,
  onSelect,
}: {
  value: number | null;
  onSelect: (id: number | null, name: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
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

  const pick = (item: SearchResult) => {
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
    <div className="relative">
      <label className="label label-text text-xs">Club</label>
      {selectedLabel ? (
        <div className="flex items-center gap-1.5 input input-bordered input-sm w-48 pr-1">
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
          className="input input-bordered input-sm w-48"
          placeholder="Search clubs…"
          value={query}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => { if (results.length > 0) setOpen(true); }}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
        />
      )}

      {open && results.length > 0 && (
        <div className="absolute top-full left-0 mt-1 w-64 z-20 bg-base-100 border border-base-300 rounded-xl shadow-xl max-h-48 overflow-y-auto">
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
  );
}

// ── Framer-motion table row variants ─────────────────────────────────────

const rowVariants = {
  hidden: { opacity: 0, x: -10 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: i * 0.025, duration: 0.2 },
  }),
};

// ── Page component ───────────────────────────────────────────────────────

export default function ExplorerPage() {
  const [q, setQ] = useState("");
  const [clubId, setClubId] = useState<number | null>(null);
  const [clubName, setClubName] = useState<string | null>(null);
  const [positionFilter, setPositionFilter] = useState<string | null>(null);
  const [positionPickerOpen, setPositionPickerOpen] = useState(false);
  const [leagueFilter, setLeagueFilter] = useState<string | null>(null);
  const [leaguePickerOpen, setLeaguePickerOpen] = useState(false);
  const [minRoi, setMinRoi] = useState<number | undefined>(undefined);
  const [yearFrom, setYearFrom] = useState<number | undefined>(undefined);
  const [yearTo, setYearTo] = useState<number | undefined>(undefined);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const hasAnyFilter = !!(q.trim() || clubId || positionFilter || leagueFilter || minRoi || yearFrom || yearTo);

  const clearAll = () => {
    setQ("");
    setClubId(null);
    setClubName(null);
    setPositionFilter(null);
    setLeagueFilter(null);
    setMinRoi(undefined);
    setYearFrom(undefined);
    setYearTo(undefined);
  };

  const { data: transfersData, isLoading, isError } = useQuery({
    queryKey: [
      "explorer-transfers",
      q,
      clubId,
      positionFilter,
      leagueFilter,
      minRoi,
      yearFrom,
      yearTo,
    ],
    queryFn: () =>
      fetchTransfers({
        q: q.trim() || undefined,
        club_id: clubId ?? undefined,
        position: positionFilter ?? undefined,
        league: leagueFilter ?? undefined,
        min_roi: minRoi,
        year_from: yearFrom,
        year_to: yearTo,
        per_page: 200,
      }),
    placeholderData: (prev) => prev,
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
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">Transfer Explorer</h1>
        <p className="text-base-content/70 mt-1">
          Explore individual transfers by fee vs ROI - filter by player, club, position, or league
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-end">
        {/* Player name search */}
        <div className="form-control">
          <label className="label label-text text-xs">Player</label>
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search by name…"
            className="input input-bordered input-sm w-40"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>

        {/* Club search */}
        <ClubSearch value={clubId} onSelect={(id, name) => { setClubId(id); setClubName(name); }} />

        {/* Position filter button */}
        <motion.div className="form-control">
          <label className="label label-text text-xs">&nbsp;</label>
          <motion.button
            onClick={() => setPositionPickerOpen(true)}
            className={`btn btn-xs sm:btn-sm ${positionFilter ? "btn-secondary" : "btn-ghost"}`}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
            </svg>
            {positionFilter || "Position"}
          </motion.button>
        </motion.div>

        {/* League filter button */}
        <motion.div className="form-control">
          <label className="label label-text text-xs">&nbsp;</label>
          <motion.button
            onClick={() => setLeaguePickerOpen(true)}
            className={`btn btn-xs sm:btn-sm ${leagueFilter ? "btn-secondary" : "btn-ghost"}`}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <path strokeLinecap="round" d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
            </svg>
            {leagueFilter || "League"}
          </motion.button>
        </motion.div>

        {/* Min ROI */}
        <div className="form-control">
          <label className="label label-text text-xs">Min ROI %</label>
          <input
            type="number"
            placeholder="Any"
            className="input input-bordered input-sm w-20"
            value={minRoi ?? ""}
            onChange={(e) => setMinRoi(e.target.value ? Number(e.target.value) : undefined)}
          />
        </div>

        {/* Year From */}
        <div className="form-control">
          <label className="label label-text text-xs">Year From</label>
          <input
            type="number"
            placeholder="2000"
            className="input input-bordered input-sm w-20"
            value={yearFrom ?? ""}
            onChange={(e) => setYearFrom(e.target.value ? Number(e.target.value) : undefined)}
          />
        </div>

        {/* Year To */}
        <div className="form-control">
          <label className="label label-text text-xs">Year To</label>
          <input
            type="number"
            placeholder="2025"
            className="input input-bordered input-sm w-20"
            value={yearTo ?? ""}
            onChange={(e) => setYearTo(e.target.value ? Number(e.target.value) : undefined)}
          />
        </div>

        {/* Clear all */}
        {hasAnyFilter && (
          <motion.button
            className="btn btn-ghost btn-sm"
            onClick={clearAll}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            Clear All
          </motion.button>
        )}
      </div>

      {/* Active filter chips */}
      <AnimatePresence>
        {(positionFilter || leagueFilter || clubName) && (
          <motion.div
            initial={{ opacity: 0, y: -8, height: 0 }}
            animate={{ opacity: 1, y: 0, height: "auto" }}
            exit={{ opacity: 0, y: -8, height: 0 }}
            className="flex flex-wrap items-center gap-2"
          >
            <span className="text-xs text-base-content/50">Active filters:</span>

            {positionFilter && (
              <motion.span
                layout
                className="badge badge-sm gap-1.5 !p-3"
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
              >
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                </svg>
                {positionFilter}
                <button onClick={() => setPositionFilter(null)} className="ml-0.5 hover:text-error transition-colors">
                  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </motion.span>
            )}

            {leagueFilter && (
              <motion.span
                layout
                className="badge badge-sm gap-1.5 !p-3"
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
              >
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <path strokeLinecap="round" d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
                </svg>
                {leagueFilter}
                <button onClick={() => setLeagueFilter(null)} className="ml-0.5 hover:text-error transition-colors">
                  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </motion.span>
            )}

            {clubName && (
              <motion.span
                layout
                className="badge badge-sm gap-1.5 !p-3"
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
              >
                <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <path strokeLinecap="round" d="M9 2v20M15 2v20" />
                </svg>
                {clubName}
                <button onClick={() => { setClubId(null); setClubName(null); }} className="ml-0.5 hover:text-error transition-colors">
                  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </motion.span>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Results count */}
      <p className="text-sm text-base-content/50">
        Showing {transfersData?.transfers?.length ?? 0} transfer{transfersData?.transfers?.length === 1 ? "" : "s"}
        {transfersData && transfersData.total > transfersData.transfers.length && (
          <> (of {transfersData.total})</>
        )}
      </p>

      {/* Scatter Plot */}
      <div className="bg-base-200 rounded-xl p-4">
        {isError ? (
          <div className="flex justify-center items-center h-[400px] text-error">
            Failed to load transfers. Make sure the API is running.
          </div>
        ) : scatterData.length === 0 ? (
          <div className="flex justify-center items-center h-[400px] text-base-content/50">
            {isLoading ? (
              <span className="loading loading-spinner loading-md" />
            ) : (
              "No transfers match the filters. Try adjusting your criteria."
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
                      <p className="text-xs text-base-content/60">{d.club}</p>
                      <p>Fee: {formatEuro(d.x)}</p>
                      <p>ROI: {d.y.toFixed(0)}%</p>
                      {d.profit != null && <p>Profit: {formatEuro(d.profit)}</p>}
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
            {isLoading ? (
              <tr>
                <td colSpan={7} className="text-center py-12">
                  <span className="loading loading-spinner loading-md" />
                </td>
              </tr>
            ) : !transfersData?.transfers?.length ? (
              <tr>
                <td colSpan={7} className="text-center py-12 text-base-content/50">
                  No transfers match the filters
                </td>
              </tr>
            ) : (
              transfersData.transfers.map((t, i) => (
                <motion.tr
                  key={t.transfer_id}
                  className="hover"
                  custom={i}
                  variants={rowVariants}
                  initial="hidden"
                  animate="visible"
                >
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
                  <td className="text-right font-mono text-sm">
                    {formatEuro(t.transfer_fee)}
                  </td>
                  <td className={`text-right font-mono text-sm ${t.roi_pct && t.roi_pct > 0 ? "text-success" : t.roi_pct && t.roi_pct < 0 ? "text-error" : ""}`}>
                    {t.roi_pct?.toFixed(0) ?? ""}%
                  </td>
                  <td className={`text-right font-mono text-sm ${t.profit && t.profit > 0 ? "text-success" : t.profit && t.profit < 0 ? "text-error" : ""}`}>
                    {formatEuro(t.profit)}
                  </td>
                </motion.tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Position Picker Modal */}
      <PositionPicker
        isOpen={positionPickerOpen}
        onClose={() => setPositionPickerOpen(false)}
        activePosition={positionFilter}
        onSelect={(pos) => {
          setPositionFilter(pos);
          setPositionPickerOpen(false);
        }}
      />

      {/* League Picker Modal */}
      <LeaguePicker
        isOpen={leaguePickerOpen}
        onClose={() => setLeaguePickerOpen(false)}
        activeLeague={leagueFilter}
        onSelect={(league) => {
          setLeagueFilter(league);
          setLeaguePickerOpen(false);
        }}
      />
    </div>
  );
}
