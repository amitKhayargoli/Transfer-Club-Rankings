/**
 * Club Rankings Leaderboard page.
 * Sortable table with Fuse.js fuzzy search, pagination, and metric toggles.
 */

import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { motion } from "framer-motion";
import Fuse, { type IFuseOptions } from "fuse.js";
import { fetchClubs, Club, clubLogoUrl } from "@/lib/api";

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

type SortField =
  | "composite_score"
  | "median_roi"
  | "total_profit"
  | "hit_rate"
  | "total_transfers"
  | "annualized_roi";

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "composite_score", label: "Composite Score" },
  { value: "median_roi", label: "Median ROI %" },
  { value: "annualized_roi", label: "Ann. ROI %" },
  { value: "total_profit", label: "Total Profit" },
  { value: "hit_rate", label: "Hit Rate %" },
  { value: "total_transfers", label: "Volume" },
];

// ── Framer-motion table row variants ─────────────────────────────────────

const rowVariants = {
  hidden: { opacity: 0, x: -10 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: i * 0.025, duration: 0.2 },
  }),
};

// ── Fuse.js fuzzy search setup ──────────────────────────────────────────

const FUSE_OPTIONS: IFuseOptions<Club> = {
  keys: [
    { name: "name", weight: 0.7 },
    { name: "domestic_competition_id", weight: 0.3 },
  ],
  threshold: 0.4,
  distance: 200,
  minMatchCharLength: 1,
};

// ── Page component ───────────────────────────────────────────────────────

export default function RankingsPage() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<SortField>("composite_score");
  const [sortOrder, setSortOrder] = useState<"desc" | "asc">("desc");
  const [searchQuery, setSearchQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Enriched leagues to show
  const enrichedLeagues = "GB1,ES1,IT1,FR1,L1,PO1,NL1,A1";

  // Fetch a large batch of clubs (2015+ era only) so Fuse.js can search across them client-side
  const { data, isLoading } = useQuery({
    queryKey: ["clubs", sortBy, sortOrder, enrichedLeagues],
    queryFn: () => fetchClubs({ sort_by: sortBy, sort_order: sortOrder, per_page: 200, leagues: enrichedLeagues, min_transfers: 8 }),
    placeholderData: (previousData) => previousData,
  });

  // Build Fuse index whenever the clubs data changes
  const fuse = useMemo(() => {
    if (!data?.clubs) return null;
    return new Fuse(data.clubs, FUSE_OPTIONS);
  }, [data?.clubs]);

  // Derive the filtered / searched list of clubs
  const filteredClubs = useMemo<Club[]>(() => {
    if (!data?.clubs) return [];

    if (!searchQuery.trim()) {
      return data.clubs;
    }

    if (!fuse) return data.clubs;

    // Fuse.js returns results with { item, refIndex, score }
    return fuse.search(searchQuery.trim()).map((r) => r.item);
  }, [data?.clubs, searchQuery, fuse]);

  // Client-side pagination of the filtered set
  const perPage = 50;
  const totalFiltered = filteredClubs.length;
  const totalPages = Math.max(1, Math.ceil(totalFiltered / perPage));
  const safePage = Math.min(page, totalPages);
  const pagedClubs = filteredClubs.slice(
    (safePage - 1) * perPage,
    safePage * perPage
  );

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
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold">Club Rankings</h1>
          <p className="text-base-content/70 mt-1">
            Top 5 Europe + European Leagues · since 2015 ·
            {searchQuery.trim()
              ? ` ${totalFiltered} club${totalFiltered === 1 ? "" : "s"} matching “${searchQuery}”`
              : ` ${data?.total ?? ""} clubs ranked`}
          </p>
        </div>
      </div>

      <div className="badge badge-outline !p-3 text-xs">📅 Since 2015</div>

      {/* Search + Sort controls */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Fuzzy search input */}
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
              placeholder="Search clubs…"
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
        </div>
      </div>

      {/* Results count badge */}
      {searchQuery.trim() && totalFiltered > 0 && (
        <div className="text-sm text-base-content/50">
          Showing {pagedClubs.length} of {totalFiltered} results
        </div>
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-xl">
        <table className="table table-zebra table-pin-rows">
          <thead>
            <tr className="text-sm">
              <th>#</th>
              <th>Club</th>
              <th className="text-right">Score</th>
              <th className="text-right">ROI %</th>
              <th className="text-right">Ann. ROI</th>
              <th className="text-right">Hit Rate</th>
              <th className="text-right">Profit</th>
              <th className="text-right">Transfers</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={8} className="text-center py-12">
                  <span className="loading loading-spinner loading-md" />
                </td>
              </tr>
            ) : pagedClubs.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-12 text-base-content/50">
                  {searchQuery.trim()
                    ? `No clubs match “${searchQuery}”`
                    : "No clubs found"}
                </td>
              </tr>
            ) : (
              pagedClubs.map((club, i) => (
                <motion.tr
                  key={club.club_id}
                  className="hover"
                  custom={i}
                  variants={rowVariants}
                  initial="hidden"
                  animate="visible"
                >
                  <td className="font-mono text-xs text-base-content/50">
                    {(safePage - 1) * perPage + i + 1}
                  </td>
                  <td>
                    <Link
                      href={`/clubs/${club.club_id}`}
                      className="font-medium hover:text-primary transition-colors flex items-center gap-2.5"
                    >
                      <img
                        src={clubLogoUrl(club.club_id) ?? ""}
                        alt=""
                        className="w-5 h-5 object-contain shrink-0"
                        onError={(e) => { e.currentTarget.style.display = "none"; }}
                      />
                      {club.name}
                    </Link>
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {club.composite_score?.toFixed(3) ?? ""}
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    <span
                      className={
                        club.median_roi && club.median_roi > 0
                          ? "text-success"
                          : "text-error"
                      }
                    >
                      {club.median_roi?.toFixed(1) ?? ""}%
                    </span>
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums text-base-content/70">
                    {club.annualized_roi
                      ? `${club.annualized_roi > 0 ? "+" : ""}${club.annualized_roi.toFixed(1)}%`
                      : ""}
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {club.hit_rate?.toFixed(1) ?? ""}%
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {formatEuro(club.total_profit)}
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {club.total_transfers ?? ""}
                  </td>
                </motion.tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-3">
          <button
            className="btn btn-sm"
            disabled={safePage <= 1}
            onClick={() => setPage(safePage - 1)}
          >
            ← Previous
          </button>

          {/* Page number buttons */}
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
        </div>
      )}
    </div>
  );
}
