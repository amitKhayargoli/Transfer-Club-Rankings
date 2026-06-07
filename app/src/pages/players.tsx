/**
 * Player Browse page.
 * Table view with search, interactive position filter, sortable by market value, pagination.
 * Position filter opens a fun interactive modal with placeholder images and framer-motion.
 */

import { useState, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { searchPlayers, playerImageUrl } from "@/lib/api";
import PositionPicker from "@/components/PositionPicker";
import LeaguePicker from "@/components/LeaguePicker";
import type { Player } from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────

function formatEuro(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${sign}€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}€${(abs / 1_000).toFixed(1)}K`;
  return `${sign}€${abs.toFixed(0)}`;
}

type SortField = "market_value_in_eur" | "name";

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "market_value_in_eur", label: "Market Value" },
  { value: "name", label: "Name" },
];

// ── Player Thumbnail with Fallback ───────────────────────────────────────

function PlayerThumb({ playerId, name, imageUrl }: { playerId: number; name: string; imageUrl?: string | null }) {
  const [imgError, setImgError] = useState(false);
  const imgUrl = playerImageUrl(playerId, "small", imageUrl);

  if (!imgError && imgUrl) {
    return (
      <img
        src={imgUrl}
        alt=""
        className="w-7 h-7 rounded-full object-cover shrink-0 bg-base-300"
        onError={() => setImgError(true)}
        loading="lazy"
      />
    );
  }

  // Fallback: initial letter
  return (
    <div className="w-7 h-7 rounded-full shrink-0 bg-primary/20 flex items-center justify-center">
      <span className="text-xs font-bold text-primary">
        {name.charAt(0).toUpperCase()}
      </span>
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

export default function PlayersPage() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<SortField>("market_value_in_eur");
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");
  const [searchQuery, setSearchQuery] = useState("");
  const [positionFilter, setPositionFilter] = useState<string | null>(null);
  const [positionPickerOpen, setPositionPickerOpen] = useState(false);
  const [leagueFilter, setLeagueFilter] = useState<string | null>(null);
  const [leaguePickerOpen, setLeaguePickerOpen] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["players-list", sortBy, sortOrder, page, searchQuery, positionFilter, leagueFilter],
    queryFn: () =>
      searchPlayers({
        q: searchQuery.trim() || undefined,
        position: positionFilter ?? undefined,
        league: leagueFilter ?? undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        page,
        per_page: 50,
      }),
    placeholderData: (previousData) => previousData,
  });

  const players = data?.players ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / 50));
  const safePage = Math.min(page, totalPages);

  const toggleSort = (field: SortField) => {
    if (sortBy === field) {
      setSortOrder(sortOrder === "desc" ? "asc" : "desc");
    } else {
      setSortBy(field);
      setSortOrder("desc");
    }
    setPage(1);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">Players</h1>
        <p className="text-base-content/70 mt-1">
          {searchQuery.trim()
            ? `${total} player${total === 1 ? "" : "s"} matching "${searchQuery}"`
            : `${total} players in database`}
        </p>
      </div>

      {/* Search + Sort + Filter controls */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        {/* Search input */}
        <div className="form-control sm:max-w-xs w-full">
          <label className="input input-bordered input-sm flex items-center gap-2">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4 shrink-0 opacity-50"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="11" cy="11" r="8" />
              <path strokeLinecap="round" d="m21 21-4.3-4.3" />
            </svg>
            <input
              ref={searchInputRef}
              type="text"
              className="grow"
              placeholder="Search players by name…"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
            />
            {searchQuery && (
              <button
                className="btn btn-ghost btn-xs btn-square"
                onClick={() => {
                  setSearchQuery("");
                  setPage(1);
                  searchInputRef.current?.focus();
                }}
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            )}
          </label>
        </div>

        {/* Sort buttons */}
        <div className="flex flex-wrap gap-2">
          {SORT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => toggleSort(opt.value)}
              className={`btn btn-xs sm:btn-sm ${
                sortBy === opt.value ? "btn-primary" : "btn-ghost"
              }`}
            >
              {opt.label}
              {sortBy === opt.value && (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-3 w-3"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  {sortOrder === "desc" ? (
                    <path
                      fillRule="evenodd"
                      d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                      clipRule="evenodd"
                    />
                  ) : (
                    <path
                      fillRule="evenodd"
                      d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z"
                      clipRule="evenodd"
                    />
                  )}
                </svg>
              )}
            </button>
          ))}

          {/* Position filter button */}
          <motion.button
            onClick={() => setPositionPickerOpen(true)}
            className={`btn btn-xs sm:btn-sm ${
              positionFilter ? "btn-secondary" : "btn-ghost"
            }`}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-3.5 w-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
            </svg>
            Position
            {positionFilter && (
              <span className="badge badge-sm badge-secondary ml-1 !p-3">
                {positionFilter.length > 12
                  ? positionFilter.slice(0, 12) + "…"
                  : positionFilter}
              </span>
            )}
          </motion.button>

          {/* League filter button */}
          <motion.button
            onClick={() => setLeaguePickerOpen(true)}
            className={`btn btn-xs sm:btn-sm ${
              leagueFilter ? "btn-secondary" : "btn-ghost"
            }`}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-3.5 w-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <circle cx="12" cy="12" r="10" />
              <path strokeLinecap="round" d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
            </svg>
            League
            {leagueFilter && (
              <span className="badge badge-sm badge-secondary ml-1 !p-3">
                {leagueFilter}
              </span>
            )}
          </motion.button>
        </div>
      </div>

      {/* Active filter chips */}
      <AnimatePresence>
        {(positionFilter || leagueFilter) && (
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
                <button
                  onClick={() => {
                    setPositionFilter(null);
                    setPage(1);
                  }}
                  className="ml-0.5 hover:text-error transition-colors"
                >
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
                <button
                  onClick={() => {
                    setLeagueFilter(null);
                    setPage(1);
                  }}
                  className="ml-0.5 hover:text-error transition-colors"
                >
                  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </motion.span>
            )}

            {searchQuery.trim() && (
              <span className="text-xs text-base-content/50">
                + search: &ldquo;{searchQuery}&rdquo;
              </span>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Results count */}
      {searchQuery.trim() && total > 0 && (
        <div className="text-sm text-base-content/50">
          Showing {players.length} of {total} results
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-xl">
        <table className="table table-zebra table-pin-rows">
          <thead>
            <tr className="text-sm">
              <th>#</th>
              <th>Player</th>
              <th>Position</th>
              <th>Club</th>
              <th className="text-right">Market Value</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={5} className="text-center py-12">
                  <span className="loading loading-spinner loading-md" />
                </td>
              </tr>
            ) : isError ? (
              <tr>
                <td colSpan={5} className="text-center py-12 text-error">
                  Failed to load. Make sure the API is running.
                </td>
              </tr>
            ) : players.length === 0 ? (
              <tr>
                <td colSpan={5} className="text-center py-12 text-base-content/50">
                  {searchQuery.trim()
                    ? `No players match "${searchQuery}"`
                    : positionFilter && leagueFilter
                      ? `No players with position "${positionFilter}" in ${leagueFilter}`
                      : positionFilter
                        ? `No players with position "${positionFilter}"`
                        : leagueFilter
                          ? `No players in league "${leagueFilter}"`
                          : "No players found"}
                </td>
              </tr>
            ) : (
              players.map((player, i) => (
                <motion.tr
                  key={player.player_id}
                  className="hover"
                  custom={i}
                  variants={rowVariants}
                  initial="hidden"
                  animate="visible"
                >
                  <td className="font-mono text-xs text-base-content/50">
                    {(safePage - 1) * 50 + i + 1}
                  </td>
                  <td>
                    <Link
                      href={`/players/${player.player_id}`}
                      className="font-medium hover:text-primary transition-colors flex items-center gap-2.5"
                    >
                      <PlayerThumb playerId={player.player_id} name={player.name} imageUrl={player.image_url} />
                      {player.name}
                    </Link>
                  </td>
                  <td className="text-sm text-base-content/70">
                    {player.position ?? "-"}
                  </td>
                  <td className="text-sm text-base-content/70">
                    {player.current_club_name ?? "-"}
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {player.market_value_in_eur != null ? (
                      <span
                        className={
                          player.market_value_in_eur > 10_000_000
                            ? "text-success font-bold"
                            : ""
                        }
                      >
                        {formatEuro(player.market_value_in_eur)}
                      </span>
                    ) : (
                      <span className="text-base-content/40">-</span>
                    )}
                  </td>
                </motion.tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <motion.div
          className="flex justify-center items-center gap-3"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          <button
            className="btn btn-sm"
            disabled={safePage <= 1}
            onClick={() => setPage(safePage - 1)}
          >
            ← Previous
          </button>

          <div className="flex gap-1">
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              let pageNum: number;
              if (totalPages <= 7) {
                pageNum = i + 1;
              } else if (safePage <= 4) {
                pageNum = i + 1;
              } else if (safePage >= totalPages - 3) {
                pageNum = totalPages - 6 + i;
              } else {
                pageNum = safePage - 3 + i;
              }
              return (
                <button
                  key={pageNum}
                  className={`btn btn-sm btn-square ${
                    pageNum === safePage ? "btn-primary" : "btn-ghost"
                  }`}
                  onClick={() => setPage(pageNum)}
                >
                  {pageNum}
                </button>
              );
            })}
          </div>

          <button
            className="btn btn-sm"
            disabled={safePage >= totalPages}
            onClick={() => setPage(safePage + 1)}
          >
            Next →
          </button>
        </motion.div>
      )}

      {/* Position Picker Modal */}
      <PositionPicker
        isOpen={positionPickerOpen}
        onClose={() => setPositionPickerOpen(false)}
        activePosition={positionFilter}
        onSelect={(pos) => {
          setPositionFilter(pos);
          setPage(1);
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
          setPage(1);
          setLeaguePickerOpen(false);
        }}
      />
    </div>
  );
}
