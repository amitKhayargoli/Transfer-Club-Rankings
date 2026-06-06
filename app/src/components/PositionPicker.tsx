/**
 * PositionPicker - An interactive modal that displays football positions
 * as a grid of large placeholder images with framer-motion animations.
 *
 * Clicking a position filters the player table by that position.
 */

import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

// ── Position Data ────────────────────────────────────────────────────────

export interface PositionGroup {
  label: string;
  positions: { value: string; label: string; color: string }[];
}

const POSITION_GROUPS: PositionGroup[] = [
  {
    label: "Goalkeeper",
    positions: [
      { value: "Goalkeeper", label: "Goalkeeper", color: "#f59e0b" },
    ],
  },
  {
    label: "Defenders",
    positions: [
      { value: "Centre-Back", label: "Centre-Back", color: "#10b981" },
      { value: "Left-Back", label: "Left-Back", color: "#34d399" },
      { value: "Right-Back", label: "Right-Back", color: "#34d399" },
      { value: "Defender", label: "Defender", color: "#6ee7b7" },
    ],
  },
  {
    label: "Midfielders",
    positions: [
      { value: "Defensive Midfield", label: "Def. Midfield", color: "#3b82f6" },
      { value: "Central Midfield", label: "Central Midfield", color: "#60a5fa" },
      { value: "Attacking Midfield", label: "Att. Midfield", color: "#93c5fd" },
      { value: "Left Midfield", label: "Left Midfield", color: "#60a5fa" },
      { value: "Right Midfield", label: "Right Midfield", color: "#60a5fa" },
      { value: "Midfield", label: "Midfield", color: "#93c5fd" },
    ],
  },
  {
    label: "Forwards",
    positions: [
      { value: "Centre-Forward", label: "Centre-Forward", color: "#ef4444" },
      { value: "Left Winger", label: "Left Winger", color: "#f87171" },
      { value: "Right Winger", label: "Right Winger", color: "#f87171" },
      { value: "Second Striker", label: "Second Striker", color: "#fca5a5" },
      { value: "Attack", label: "Attack", color: "#fca5a5" },
    ],
  },
];

// Combine all positions into a flat list for quick lookup
const ALL_POSITIONS = POSITION_GROUPS.flatMap((g) => g.positions);

export function getPositionColor(value: string): string {
  return ALL_POSITIONS.find((p) => p.value === value)?.color ?? "#6b7280";
}

export function getPositionLabel(value: string): string {
  return ALL_POSITIONS.find((p) => p.value === value)?.label ?? value;
}

// ── SVG Placeholder Silhouette ───────────────────────────────────────────

function PlayerSilhouette({ color }: { color: string }) {
  return (
    <svg
      viewBox="0 0 120 140"
      className="w-full h-full"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      {/* Head */}
      <ellipse cx="60" cy="28" rx="22" ry="24" fill={color} opacity="0.25" />
      {/* Body */}
      <path
        d="M30 70c0-12 8-20 18-22l2 2c6 4 14 4 20 0l2-2c10 2 18 10 18 22v10c0 8-4 14-10 18l-10 32c-2 6-8 10-14 10h-4c-6 0-12-4-14-10l-10-32c-6-4-10-10-10-18V70z"
        fill={color}
        opacity="0.2"
      />
      {/* Legs */}
      <rect x="36" y="118" width="10" height="18" rx="3" fill={color} opacity="0.2" />
      <rect x="74" y="118" width="10" height="18" rx="3" fill={color} opacity="0.2" />
    </svg>
  );
}

// ── Position Card ────────────────────────────────────────────────────────

function PositionCard({
  value,
  label,
  color,
  isActive,
  onClick,
}: {
  value: string;
  label: string;
  color: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <motion.button
      layout
      onClick={onClick}
      className={`
        relative flex flex-col items-center justify-center gap-2
        rounded-2xl p-4 cursor-pointer border-2
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
      {/* Placeholder image area */}
      <div className="w-16 h-20 flex items-center justify-center">
        <PlayerSilhouette color={color} />
      </div>

      {/* Position name */}
      <span
        className={`text-xs font-semibold text-center leading-tight ${
          isActive ? "text-primary" : "text-base-content/80"
        }`}
      >
        {label}
      </span>

      {/* Active indicator */}
      {isActive && (
        <motion.div
          layoutId="activePosition"
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

function PositionGroup({
  group,
  activePosition,
  onSelect,
  index,
}: {
  group: PositionGroup;
  activePosition: string | null;
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
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {group.positions.map((pos) => (
          <motion.div
            key={pos.value}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: index * 0.08 + 0.05, duration: 0.25 }}
          >
            <PositionCard
              value={pos.value}
              label={pos.label}
              color={pos.color}
              isActive={activePosition === pos.value}
              onClick={() => onSelect(activePosition === pos.value ? null : pos.value)}
            />
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}

// ── Main PositionPicker Component ────────────────────────────────────────

interface PositionPickerProps {
  isOpen: boolean;
  onClose: () => void;
  activePosition: string | null;
  onSelect: (position: string | null) => void;
}

export default function PositionPicker({
  isOpen,
  onClose,
  activePosition,
  onSelect,
}: PositionPickerProps) {
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
            className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-base-100 border border-base-300 shadow-2xl"
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", stiffness: 300, damping: 25 }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="sticky top-0 z-10 bg-base-100/95 backdrop-blur-sm border-b border-base-300 rounded-t-2xl px-6 py-4 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold">Filter by Position</h2>
                <p className="text-xs text-base-content/50 mt-0.5">
                  Click a position to filter the table
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
              {POSITION_GROUPS.map((group, i) => (
                <PositionGroup
                  key={group.label}
                  group={group}
                  activePosition={activePosition}
                  onSelect={onSelect}
                  index={i}
                />
              ))}
            </div>

            {/* Footer */}
            <div className="sticky bottom-0 bg-base-100/95 backdrop-blur-sm border-t border-base-300 rounded-b-2xl px-6 py-3 flex items-center justify-between">
              <span className="text-xs text-base-content/40">
                {activePosition
                  ? `Filtering by: ${getPositionLabel(activePosition)}`
                  : "Showing all positions"}
              </span>
              {activePosition && (
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
