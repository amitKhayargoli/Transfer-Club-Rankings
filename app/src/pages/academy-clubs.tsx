/**
 * Academy Clubs page.
 * Clubs that develop youth talent and sell high.
 * Ranked by value creation (peak MV vs buy fee).
 */

import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { motion } from "framer-motion";
import Fuse, { type IFuseOptions } from "fuse.js";
import { fetchAcademyLeaders, Club, clubLogoUrl } from "@/lib/api";

// ── Framer-motion table row variants ─────────────────────────────────────

const rowVariants = {
  hidden: { opacity: 0, x: -10 },
  visible: (i: number) => ({
    opacity: 1,
    x: 0,
    transition: { delay: i * 0.025, duration: 0.2 },
  }),
};

// ── Helpers ──────────────────────────────────────────────────────────────

function formatEuro(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${sign}€${(abs / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${sign}€${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}€${(abs / 1_000).toFixed(1)}K`;
  return `${sign}€${abs.toFixed(0)}`;
}

type SortField = "value_creation" | "total_profit" | "hit_rate" | "median_roi" | "total_transfers" | "profit_per_deal";

const SORT_OPTIONS: { value: SortField; label: string }[] = [
  { value: "value_creation", label: "Value Creation" },
  { value: "total_profit", label: "Total Profit" },
  { value: "profit_per_deal", label: "Profit/Deal" },
  { value: "hit_rate", label: "Hit Rate %" },
  { value: "median_roi", label: "Median ROI %" },
  { value: "total_transfers", label: "Deals" },
];

const FUSE_OPTIONS: IFuseOptions<Club> = {
  keys: [
    { name: "name", weight: 0.7 },
    { name: "domestic_competition_id", weight: 0.3 },
  ],
  threshold: 0.4,
  distance: 200,
};

export default function AcademyClubsPage() {
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState<SortField>("value_creation");
  const [searchQuery, setSearchQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["academy-leaders", sortBy],
    queryFn: () => fetchAcademyLeaders({ per_page: 200 }),
    placeholderData: (prev) => prev,
  });

  const fuse = useMemo(() => {
    if (!data?.clubs) return null;
    return new Fuse(data.clubs, FUSE_OPTIONS);
  }, [data?.clubs]);

  const filteredClubs = useMemo(() => {
    if (!data?.clubs) return [];
    if (!searchQuery.trim()) return data.clubs;
    if (!fuse) return data.clubs;
    return fuse.search(searchQuery.trim()).map((r) => r.item);
  }, [data?.clubs, searchQuery, fuse]);

  const sortedClubs = useMemo(() => {
    const list = [...filteredClubs];
    list.sort((a, b) => {
      const av = a[sortBy] ?? 0;
      const bv = b[sortBy] ?? 0;
      if (typeof av === "number" && typeof bv === "number") return bv - av;
      return 0;
    });
    return list;
  }, [filteredClubs, sortBy]);

  const perPage = 50;
  const totalFiltered = sortedClubs.length;
  const totalPages = Math.max(1, Math.ceil(totalFiltered / perPage));
  const safePage = Math.min(page, totalPages);
  const pagedClubs = sortedClubs.slice((safePage - 1) * perPage, safePage * perPage);

  return (
    <div className="space-y-6">
      {/* Hero */}
      <div className="hero bg-base-200 rounded-2xl p-8">
        <div className="hero-content text-center">
          <div className="max-w-2xl">
            <h1 className="text-3xl font-bold">🎓 Academy Clubs</h1>
            <p className="text-base-content/70 mt-2">
              Clubs that develop young talent and sell high. Ranked by value creation - the gap between what they paid and what players became worth.
            </p>
          </div>
        </div>
      </div>

      {/* Search + Sort */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center justify-between">
        <div className="form-control sm:max-w-xs w-full">
          <label className="input input-bordered input-sm flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path strokeLinecap="round" d="m21 21-4.3-4.3" />
            </svg>
            <input
              ref={searchInputRef}
              type="text"
              className="grow"
              placeholder="Search clubs…"
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
            />
            {searchQuery && (
              <button className="btn btn-ghost btn-xs btn-square" onClick={() => { setSearchQuery(""); setPage(1); searchInputRef.current?.focus(); }}>
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            )}
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          {SORT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => { setSortBy(opt.value); setPage(1); }}
              className={`btn btn-xs sm:btn-sm ${sortBy === opt.value ? "btn-primary" : "btn-ghost"}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-xl">
        <table className="table table-zebra table-pin-rows">
          <thead>
            <tr className="text-sm">
              <th>#</th>
              <th>Club</th>
              <th className="text-right">Value Creation</th>
              <th className="text-right">Total Profit</th>
              <th className="text-right">Profit/Deal</th>
              <th className="text-right">Hit Rate</th>
              <th className="text-right">ROI</th>
              <th className="text-right">Deals</th>
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
                  No clubs found
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
                  <td className="text-right font-mono text-sm tabular-nums text-warning font-semibold">
                    {club.value_creation ? `${club.value_creation > 0 ? "+" : ""}${club.value_creation.toFixed(0)}%` : "-"}
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums text-success">
                    {formatEuro(club.total_profit)}
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {formatEuro(club.profit_per_deal)}
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {club.hit_rate?.toFixed(1) ?? "-"}%
                  </td>
                  <td className={`text-right font-mono text-sm tabular-nums ${club.median_roi && club.median_roi > 0 ? "text-success" : "text-error"}`}>
                    {club.median_roi?.toFixed(1) ?? "-"}%
                  </td>
                  <td className="text-right font-mono text-sm tabular-nums">
                    {club.total_transfers ?? "-"}
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
          <button className="btn btn-sm" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>
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
                  className={`btn btn-sm btn-square ${pageNum === safePage ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setPage(pageNum)}
                >
                  {pageNum}
                </button>
              );
            })}
          </div>
          <button className="btn btn-sm" disabled={safePage >= totalPages} onClick={() => setPage(safePage + 1)}>
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
