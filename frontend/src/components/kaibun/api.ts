import type { Emotion } from "@/lib/standAnimations";
import type { Outfit } from "@/lib/api";

export type GuestCasting = { voice_id: string; outfit_owner: string; outfit: string; portrait: string };
export type Actor = { voice_id?: string; portrait?: string; id: string; name: string; short_name: string | null; avatar_url: string; background_url: string | null; stand: Outfit | null; stand_bounds?: { width: number; height: number } | null; retired_default_outfits?: string[] };

export function migrateOutfitDefaults(outfits: Record<string, string>, actors: readonly Actor[]): Record<string, string> {
  return Object.fromEntries(Object.entries(outfits).filter(([cid, oid]) => !actors.find(actor => actor.id === cid)?.retired_default_outfits?.includes(oid)));
}
export type Wardrobe = Outfit & { label: string; thumbnail?: string | null; bounds?: { width: number; height: number } | null };
export type Background = { id: string; url: string; thumbnail: string; label: string; description: string; tags: string[]; indexed: boolean; time_of_day?: string };
export type ActorState = { emotion?: Emotion; body_mood?: Emotion | null };
export type PerformanceSegment = { ja: string; zh: string; start?: number; emotion: Emotion; body_mood?: Emotion | null; actor_states?: Record<string, ActorState> };
export type Line = { voice_tracks?: string[]; nichika_voice_style?: "natural" | "idol"; listener_state_persist?: boolean; audio_revision?: string; performance_invalidated?: boolean; audio_status?: string; imported_untranslated?: boolean; performance_segments?: PerformanceSegment[]; id: string; speaker: string; speakers?: string[]; ja: string; zh: string; emotion: Emotion; body_mood?: Emotion | null; screen_cast?: string[]; actor_order?: string[]; actor_states?: Record<string, { emotion?: Emotion; body_mood?: Emotion | null }>; voice_style?: "natural" | "idol"; kind?: "dialogue" | "thought"; onstage?: string[]; focus?: string[] };
export type Scene = { transition_length?: "short" | "medium" | "long"; line_transition_lengths?: Record<string, "short" | "medium" | "long">; line_transitions?: Record<string, "cut" | "pause" | "fade">; transition?: "cut" | "pause" | "fade"; index: number; title: string; place: string; lines: Line[]; memory: string; outfits?: Record<string, string>; wardrobe?: Record<string, Wardrobe>; wardrobe_changes?: Record<string, Record<string, Wardrobe>>; background_asset?: Background | null; background_change_assets?: Record<string, Background | null> };
export type StoryLength = "short" | "standard" | "half_hour" | "hour_plus";
export type Outline = { title: string; direction: string; opening?: string; cast: string[]; guests: { id: string; name: string }[]; scenes: { title: string; place: string; direction: string; transition?: "cut" | "pause" | "fade"; transition_length?: "short" | "medium" | "long" }[] };
export type StoryBrief = { id: string; premise: string; title: string; pinned?: boolean; length: StoryLength; status: "queued" | "generating" | "preparing" | "ready" | "failed" | "interrupted" | "tuning"; phase: string; error: string | null; created_at: string };
export type Story = StoryBrief & { guest_cast?: Record<string, GuestCasting>; guest_actors?: Actor[]; voice_revision?: string; base_fingerprint?: string; revision_history_count?: number; imported_script?: {filename: string; unparsed_lines: number}; revision_proposal?: {id: string; completed: number[]; outline?: Outline; scenes: Record<string,Scene>}; revision_undo?: unknown; revision_changes?: {scene:number; changes:{id:string; before:string; after:string; before_ja?:string; after_ja?:string; fields?:string[]; voice_changed?:boolean; performance_reset?:boolean}[]}[]; revision_progress?: {status: string; message: string; completed?: number; total?: number; scene?: number}; outline: Outline | null; scenes: Scene[]; model: string | null; tuning?: "outline" | "script" | "production" };

export class RequestError extends Error {
  constructor(message: string, public status: number, public savedFingerprint?: string) { super(message); }
}

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch("/api/kaibun/" + path, body === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new RequestError(typeof data.detail === "string" ? data.detail : "请求失败，请稍后重试", response.status, typeof data.saved_fingerprint === 'string' ? data.saved_fingerprint : undefined);
  }
  return response.json();
}
