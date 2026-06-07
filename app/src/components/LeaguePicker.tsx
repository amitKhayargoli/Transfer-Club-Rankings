/**
 * LeaguePicker - An interactive modal that displays football leagues
 * as a grid of placeholder flag images with framer-motion animations.
 *
 * Clicking a league filters the player table by that league.
 */

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { leagueLogoUrl } from "@/lib/api";

// ── League Data ──────────────────────────────────────────────────────────

export interface LeagueGroup {
  label: string;
  leagues: { value: string; label: string; color: string; country: string }[];
}

const LEAGUE_GROUPS: LeagueGroup[] = [
  {
    label: "Top 5 Europe",
    leagues: [
      { value: "GB1",  label: "Premier League",  color: "#ef4444", country: "England" },
      { value: "ES1",  label: "LaLiga",          color: "#eab308", country: "Spain" },
      { value: "L1",   label: "Bundesliga",       color: "#3b82f6", country: "Germany" },
      { value: "IT1",  label: "Serie A",          color: "#22c55e", country: "Italy" },
      { value: "FR1",  label: "Ligue 1",          color: "#06b6d4", country: "France" },
    ],
  },
  {
    label: "Europe",
    leagues: [
      { value: "PO1",  label: "Liga Portugal",    color: "#dc2626", country: "Portugal" },
      { value: "NL1",  label: "Eredivisie",       color: "#f97316", country: "Netherlands" },
      { value: "BE1",  label: "Pro League",       color: "#e11d48", country: "Belgium" },
      { value: "A1",   label: "Bundesliga",       color: "#64748b", country: "Austria" },
      { value: "SC1",  label: "Premiership",      color: "#6366f1", country: "Scotland" },
      { value: "GR1",  label: "Super League",     color: "#0ea5e9", country: "Greece" },
      { value: "TR1",  label: "Süper Lig",        color: "#8b5cf6", country: "Turkey" },
      { value: "RU1",  label: "Premier Liga",     color: "#ec4899", country: "Russia" },
      { value: "PL1",  label: "Ekstraklasa",      color: "#14b8a6", country: "Poland" },
      { value: "DK1",  label: "Superliga",        color: "#f43f5e", country: "Denmark" },
      { value: "SE1",  label: "Allsvenskan",      color: "#0284c7", country: "Sweden" },
      { value: "NO1",  label: "Eliteserien",      color: "#d97706", country: "Norway" },
      { value: "RO1",  label: "Liga I",           color: "#7c3aed", country: "Romania" },
      { value: "SER1", label: "SuperLiga",        color: "#b91c1c", country: "Serbia" },
      { value: "RSK1", label: "Premier Liga",     color: "#be185d", country: "Russia" },
      { value: "UKR1", label: "Premier Liga",     color: "#1d4ed8", country: "Ukraine" },
      { value: "C1",   label: "Championship?",    color: "#475569", country: "Europe" },
    ],
  },
  {
    label: "Americas",
    leagues: [
      { value: "BRA1", label: "Série A",          color: "#16a34a", country: "Brazil" },
      { value: "ARG1", label: "Primera División", color: "#6d28d9", country: "Argentina" },
      { value: "MEX1", label: "Liga MX",          color: "#059669", country: "Mexico" },
      { value: "MLS1", label: "MLS",              color: "#2563eb", country: "USA" },
      { value: "COL1", label: "Primera A",        color: "#ca8a04", country: "Colombia" },
    ],
  },
  {
    label: "Asia & Other",
    leagues: [
      { value: "SA1",  label: "Saudi League",     color: "#65a30d", country: "Saudi Arabia" },
      { value: "JAP1", label: "J1 League",        color: "#e11d48", country: "Japan" },
      { value: "KR1",  label: "K League",         color: "#1d4ed8", country: "South Korea" },
      { value: "AUS1", label: "A-League",         color: "#9333ea", country: "Australia" },
      { value: "TS1",  label: "Liga TSI",         color: "#78716c", country: "Other" },
    ],
  },
];

// Flatten for lookup
const ALL_LEAGUES = LEAGUE_GROUPS.flatMap((g) => g.leagues);

export function getLeagueLabel(value: string): string {
  return ALL_LEAGUES.find((l) => l.value === value)?.label ?? value;
}

// ── League Logo ───────────────────────────────────────────────────────────

function LeagueLogo({ value, color }: { value: string; color: string }) {
  const [imgError, setImgError] = useState(false);
  const url = leagueLogoUrl(value);

  if (!imgError && url) {
    return (
      <div className="w-full h-full rounded-xl flex items-center justify-center bg-base-300/20">
        <div className="w-10 h-10 flex items-center justify-center">
          <img
            src={url}
            alt=""
            className="max-w-full max-h-full object-contain"
            onError={() => setImgError(true)}
            loading="lazy"
          />
        </div>
      </div>
    );
  }

  // Fallback: gradient with league abbreviation (or football icon for TR)
  if (value === "TR1") {
    return (
      <div
        className="w-full h-full rounded-xl flex items-center justify-center"
        style={{ background: `linear-gradient(135deg, ${color}88, ${color}44)` }}
      >
        <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 2v20M2 12h20" />
          <path d="M5.5 5.5l13 13M18.5 5.5l-13 13" />
        </svg>
      </div>
    );
  }

  // Fallback: gradient placeholder with league abbreviation
  return (
    <div
      className="w-full h-full rounded-xl flex items-center justify-center"
      style={{ background: `linear-gradient(135deg, ${color}88, ${color}44)` }}
    >
      <span className="text-xs font-bold uppercase" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

// ── League Card ──────────────────────────────────────────────────────────

function LeagueCard({
  value,
  label,
  color,
  country,
  isActive,
  onClick,
}: {
  value: string;
  label: string;
  color: string;
  country: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <motion.button
      layout
      onClick={onClick}
      className={`
        relative flex flex-col items-center justify-center gap-2
        rounded-2xl p-3.5 cursor-pointer border-2
        transition-colors duration-200
        ${
          isActive
            ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
            : "border-base-300 bg-base-200 hover:border-base-content/30 hover:bg-base-300"
        }
      `}
      whileHover={{ scale: 1.03, y: -2 }}
      whileTap={{ scale: 0.97 }}
    >
      {/* League logo */}
      <div className="w-14 h-10 flex items-center justify-center rounded-xl overflow-hidden shadow-sm bg-base-300/30">
        <LeagueLogo value={value} color={color} />
      </div>

      {/* League name */}
      <div className="text-center">
        <span
          className={`text-xs font-semibold leading-tight block ${
            isActive ? "text-primary" : "text-base-content/80"
          }`}
        >
          {label}
        </span>
        <span className="text-[10px] text-base-content/40 mt-0.5 block">
          {country}
        </span>
      </div>

      {/* League code badge */}
      <span className="absolute top-1.5 left-1.5 text-[9px] font-mono text-base-content/60 bg-base-300/80 rounded px-1 font-semibold">
        {value}
      </span>

      {/* Active indicator */}
      {isActive && (
        <motion.div
          layoutId="activeLeague"
          className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-primary rounded-full flex items-center justify-center"
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 500, damping: 20 }}
        >
          <svg className="w-3 h-3 text-primary-content" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
            <path strokeLinecap="round" d="M20 6L9 17l-5-5" />
          </svg>
        </motion.div>
      )}
    </motion.button>
  );
}

// ── Group Section ────────────────────────────────────────────────────────

function LeagueGroupSection({
  group,
  activeLeague,
  onSelect,
  index,
}: {
  group: LeagueGroup;
  activeLeague: string | null;
  onSelect: (value: string | null) => void;
  index: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, duration: 0.3 }}
    >
      <h3 className="text-xs font-bold uppercase tracking-wider text-base-content/40 mb-3 px-1">
        {group.label}
      </h3>
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2.5">
        {group.leagues.map((league) => (
          <motion.div
            key={league.value}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: index * 0.08 + 0.04, duration: 0.25 }}
          >
            <LeagueCard
              value={league.value}
              label={league.label}
              color={league.color}
              country={league.country}
              isActive={activeLeague === league.value}
              onClick={() => onSelect(activeLeague === league.value ? null : league.value)}
            />
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}

// ── Main LeaguePicker Component ──────────────────────────────────────────

interface LeaguePickerProps {
  isOpen: boolean;
  onClose: () => void;
  activeLeague: string | null;
  onSelect: (league: string | null) => void;
}

export default function LeaguePicker({
  isOpen,
  onClose,
  activeLeague,
  onSelect,
}: LeaguePickerProps) {
  // Close on Escape key + lock body scroll when open
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      document.addEventListener("keydown", handleKey);
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = "";
    };
  }, [isOpen, onClose]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          {/* Backdrop */}
          <motion.div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />

          {/* Modal */}
          <motion.div
            className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-2xl bg-base-100 border border-base-300 shadow-2xl"
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="sticky top-0 z-10 bg-base-100/95 backdrop-blur-sm border-b border-base-300 rounded-t-2xl px-6 py-4 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold">Filter by League</h2>
                <p className="text-xs text-base-content/50 mt-0.5">
                  Click a league to see players from that competition
                </p>
              </div>
              <button
                onClick={onClose}
                className="btn btn-ghost btn-sm btn-square rounded-xl"
              >
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path strokeLinecap="round" d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Grid */}
            <div className="p-6 space-y-6">
              {LEAGUE_GROUPS.map((group, i) => (
                <LeagueGroupSection
                  key={group.label}
                  group={group}
                  activeLeague={activeLeague}
                  onSelect={onSelect}
                  index={i}
                />
              ))}
            </div>

            {/* Footer */}
            <div className="sticky bottom-0 bg-base-100/95 backdrop-blur-sm border-t border-base-300 rounded-b-2xl px-6 py-3 flex items-center justify-between">
              <span className="text-xs text-base-content/40">
                {activeLeague
                  ? `Filtering by: ${getLeagueLabel(activeLeague)} (${activeLeague})`
                  : "Showing all leagues"}
              </span>
              {activeLeague && (
                <button
                  onClick={() => {
                    onSelect(null);
                    onClose();
                  }}
                  className="btn btn-ghost btn-xs"
                >
                  Clear filter
                </button>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
