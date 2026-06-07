/**
 * API client for the Transfer ROI Rankings FastAPI backend.
 *
 * All requests go through a single `apiFetch` wrapper so we can
 * handle errors, add auth headers, etc. in one place.
 */

// Use relative URLs so requests go through Next.js's API rewrite proxy.
// In production, set NEXT_PUBLIC_API_URL to your deployed FastAPI URL.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

// ── Types matching the backend Pydantic schemas ──────────────────────────

export interface Club {
  club_id: number;
  name: string;
  club_code: string | null;
  domestic_competition_id: string | null;
  total_transfers: number | null;
  median_roi: number | null;
  annualized_roi: number | null;
  total_profit: number | null;
  profit_per_deal: number | null;
  buying_club_premium: number | null;
  hit_rate: number | null;
  value_creation: number | null;
  composite_score: number | null;
  league_name?: string | null;
  league_logo_url?: string | null;
}

// Build club logo URL from club_id using Transfermarkt CDN
// Sizes: tiny, medium, head. 'head' is largest (~37KB), 'medium' (~9KB) for table logos
export function clubLogoUrl(clubId: number | null | undefined, size: 'head' | 'medium' | 'tiny' = 'medium'): string | null {
  if (!clubId) return null;
  return `https://tmssl.akamaized.net/images/wappen/${size}/${clubId}.png`;
}

// Build player image URL from player_id using Transfermarkt CDN.
// If a stored imageUrl is provided (from the Transfermarkt API), use that first.
// The CDN pattern is the fallback for players whose images haven't been scraped yet.
export function playerImageUrl(playerId: number | null | undefined, size: 'small' | 'medium' | 'big' | 'original' = 'medium', imageUrl?: string | null): string | null {
  if (imageUrl) return imageUrl;
  if (!playerId) return null;
  return `https://tmssl.akamaized.net/images/fotos/${size}/${playerId}.jpg`;
}

// Build league logo URL from competition ID
export function leagueLogoUrl(competitionId: string | null | undefined): string | null {
  if (!competitionId) return null;
  return `https://tmssl.akamaized.net/images/logo/medium/${competitionId.toLowerCase()}.png`;
}

export interface ClubListResponse {
  clubs: Club[];
  total: number;
  page: number;
  per_page: number;
}

export interface Player {
  player_id: number;
  name: string;
  position: string | null;
  date_of_birth: string | null;
  current_club_id: number | null;
  current_club_name: string | null;
  market_value_in_eur: number | null;
  image_url: string | null;
}

export interface PlayerDetail extends Player {
  foot: string | null;
  height_in_cm: number | null;
  highest_market_value_in_eur: number | null;
  citizenship: string | null;
  agent_name: string | null;
  contract_expiry_date: string | null;
}

export interface PlayerListResponse {
  players: Player[];
  total: number;
  page: number;
  per_page: number;
}

export interface Transfer {
  transfer_id: number;
  player_id: number;
  player_name: string | null;
  from_club_id: number | null;
  to_club_id: number | null;
  from_club_name: string | null;
  to_club_name: string | null;
  transfer_date: string | null;
  transfer_fee: number | null;
  buy_fee: number | null;
  sell_fee: number | null;
  profit: number | null;
  roi_pct: number | null;
  annualized_roi_pct: number | null;
  tenure_years: number | null;
  player_position: string | null;
  transfer_type: string | null;
}

export interface TransferListResponse {
  transfers: Transfer[];
  total: number;
  page: number;
  per_page: number;
}

export interface DashboardStats {
  total_transfers: number;
  total_clubs: number;
  total_profit: number;
  biggest_profit_transfer: Transfer | null;
}

export interface TopClub {
  club: Club;
  rank: number;
}

export interface SearchResult {
  type: "club" | "player";
  id: number;
  name: string;
  subtitle: string | null;
}

export interface PipelineStatus {
  data_loaded: boolean;
  last_refresh: string | null;
  total_clubs: number;
  total_players: number;
  total_transfers: number;
}

// ── Generic fetch wrapper ───────────────────────────────────────────────

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}/api${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Club endpoints ──────────────────────────────────────────────────────

export function fetchClubs(params?: {
  league?: string;
  leagues?: string;
  min_transfers?: number;
  sort_by?: string;
  sort_order?: string;
  window?: string;
  page?: number;
  per_page?: number;
}) {
  const search = new URLSearchParams();
  if (params?.league) search.set("league", params.league);
  if (params?.leagues) search.set("leagues", params.leagues);
  if (params?.min_transfers) search.set("min_transfers", String(params.min_transfers));
  if (params?.sort_by) search.set("sort_by", params.sort_by);
  if (params?.sort_order) search.set("sort_order", params.sort_order);
  if (params?.window) search.set("window", params.window);
  if (params?.page) search.set("page", String(params.page));
  if (params?.per_page) search.set("per_page", String(params.per_page));
  const qs = search.toString();
  return apiFetch<ClubListResponse>(`/clubs${qs ? `?${qs}` : ""}`);
}

export function fetchSellLeaders(params?: {
  league?: string;
  window?: string;
  min_transfers?: number;
  page?: number;
  per_page?: number;
}) {
  const search = new URLSearchParams();
  if (params?.league) search.set("league", params.league);
  if (params?.window) search.set("window", params.window);
  if (params?.min_transfers) search.set("min_transfers", String(params.min_transfers));
  if (params?.page) search.set("page", String(params.page));
  if (params?.per_page) search.set("per_page", String(params.per_page));
  return apiFetch<ClubListResponse>(`/clubs/sell-leaders?${search.toString()}`);
}

export function fetchAcademyLeaders(params?: {
  league?: string;
  leagues?: string;
  window?: string;
  min_transfers?: number;
  page?: number;
  per_page?: number;
}) {
  const search = new URLSearchParams();
  if (params?.league) search.set("league", params.league);
  if (params?.leagues) search.set("leagues", params.leagues);
  if (params?.window) search.set("window", params.window);
  if (params?.min_transfers) search.set("min_transfers", String(params.min_transfers));
  if (params?.page) search.set("page", String(params.page));
  if (params?.per_page) search.set("per_page", String(params.per_page));
  return apiFetch<ClubListResponse>(`/clubs/academy-leaders?${search.toString()}`);
}

export function fetchClub(id: number) {
  return apiFetch<Club>(`/clubs/${id}`);
}

export function fetchClubTransfers(id: number, page = 1, perPage = 50) {
  return apiFetch<TransferListResponse>(
    `/clubs/${id}/transfers?page=${page}&per_page=${perPage}`
  );
}

export function compareClubs(ids: [number, number]) {
  return apiFetch<{ club1: Club; club2: Club }>(
    `/clubs/compare?ids=${ids.join(",")}`
  );
}

// ── Player endpoints ────────────────────────────────────────────────────

export function searchPlayers(params?: {
  q?: string;
  position?: string;
  club_id?: number;
  league?: string;
  sort_by?: string;
  sort_order?: string;
  page?: number;
  per_page?: number;
}) {
  const search = new URLSearchParams();
  if (params?.q) search.set("q", params.q);
  if (params?.position) search.set("position", params.position);
  if (params?.club_id) search.set("club_id", String(params.club_id));
  if (params?.league) search.set("league", params.league);
  if (params?.sort_by) search.set("sort_by", params.sort_by);
  if (params?.sort_order) search.set("sort_order", params.sort_order);
  if (params?.page) search.set("page", String(params.page));
  if (params?.per_page) search.set("per_page", String(params.per_page));
  const qs = search.toString();
  return apiFetch<PlayerListResponse>(`/players${qs ? `?${qs}` : ""}`);
}

export function fetchPlayer(id: number) {
  return apiFetch<PlayerDetail>(`/players/${id}`);
}

export function fetchPlayerTransfers(id: number) {
  return apiFetch<Transfer[]>(`/players/${id}/transfers`);
}

export function fetchPlayerValuations(id: number) {
  return apiFetch<{ date: string; market_value_in_eur: number | null }[]>(
    `/players/${id}/valuations`
  );
}

// ── Transfer endpoints ──────────────────────────────────────────────────

export function fetchTransfers(params?: {
  q?: string;
  club_id?: number;
  position?: string;
  league?: string;
  min_roi?: number;
  year_from?: number;
  year_to?: number;
  page?: number;
  per_page?: number;
}) {
  const search = new URLSearchParams();
  if (params?.q) search.set("q", params.q);
  if (params?.club_id) search.set("club_id", String(params.club_id));
  if (params?.position) search.set("position", params.position);
  if (params?.league) search.set("league", params.league);
  if (params?.min_roi !== undefined) search.set("min_roi", String(params.min_roi));
  if (params?.year_from) search.set("year_from", String(params.year_from));
  if (params?.year_to) search.set("year_to", String(params.year_to));
  if (params?.page) search.set("page", String(params.page));
  if (params?.per_page) search.set("per_page", String(params.per_page));
  const qs = search.toString();
  return apiFetch<TransferListResponse>(`/transfers${qs ? `?${qs}` : ""}`);
}

// ── Dashboard endpoints ─────────────────────────────────────────────────

export function fetchDashboardStats() {
  return apiFetch<DashboardStats>("/dashboard/stats");
}

export function fetchTopClubs() {
  return apiFetch<{ top_clubs: TopClub[] }>("/dashboard/top-clubs");
}

// ── Search endpoint ─────────────────────────────────────────────────────

export function unifiedSearch(q: string, limit = 10) {
  return apiFetch<{ results: SearchResult[] }>(
    `/search?q=${encodeURIComponent(q)}&limit=${limit}`
  );
}

// ── Pipeline endpoints ──────────────────────────────────────────────────

export function fetchPipelineStatus() {
  return apiFetch<PipelineStatus>("/pipeline/status");
}

export function triggerPipeline() {
  return apiFetch<{ status: string; message: string }>("/pipeline/run", {
    method: "POST",
  });
}
