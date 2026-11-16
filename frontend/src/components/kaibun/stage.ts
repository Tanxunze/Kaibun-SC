type Turn = { listener_state_persist?: boolean; performance_segments?: {emotion?: string; body_mood?: string | null; actor_states?: Record<string, {emotion?: string; body_mood?: string | null}>}[]; speaker: string; speakers?: string[]; onstage?: string[]; focus?: string[]; id?: string; emotion?: string; body_mood?: string | null; screen_cast?: string[]; actor_states?: Record<string, { emotion?: string; body_mood?: string | null }> };
export type StandBounds = { width: number; height: number };

/** Keep the chosen shot membership, arranging it by the saved left-to-right order. */
export function orderedStageCast(visible: readonly string[], order: readonly string[] = []): string[] {
  return [...new Set([...order.filter(id => visible.includes(id)), ...visible])];
}

/** The people in this exchange; being in the room does not put everyone in the shot. */
export function stageCast(lines: readonly Turn[], index: number, cast: readonly string[], limit = 5): string[] {
  const current = lines[index];
  if (!current) return [];
  if (current.screen_cast) return current.screen_cast.filter(id => cast.includes(id)).slice(0, 7);
  const known = new Set(cast);
  const present = new Set(current.onstage ?? cast);
  if (known.has(current.speaker)) present.add(current.speaker);
  const chosen: string[] = [];
  const add = (id: string) => {
    if (known.has(id) && present.has(id) && !chosen.includes(id) && chosen.length < limit) chosen.push(id);
  };
  add(current.speaker);
  if (current.focus?.length) {
    let anchor = index;
    while (anchor > 0 && lines[anchor - 1].speaker === current.speaker) anchor--;
    (lines[anchor].focus ?? current.focus).forEach(add);
  } else {
    // Keep the immediate partner while they answer; replace them as the exchange moves on.
    for (let i = index - 1; i >= Math.max(0, index - 5) && chosen.length < limit; i--) add(lines[i].speaker);
    for (let i = index + 1; i < Math.min(lines.length, index + 5) && chosen.length < limit; i++) add(lines[i].speaker);
  }
  return cast.filter(id => chosen.includes(id));
}

/** Restore each visible actor's latest pose in this uninterrupted shot, including when seeking. */
export function stagePoses(lines: readonly Turn[], index: number, cast: readonly string[], limit = 5): Record<string, { mood: string; bodyVariant: number; bodyMood?: string }> {
  const visible = (i: number) => lines[i]?.screen_cast ? stageCast(lines, i, cast, limit) : lines[i]?.speakers?.length
    ? cast.filter(id => lines[i].speakers?.includes(id)).slice(0, 7)
    : stageCast(lines, i, cast, limit);
  const result: Record<string, { mood: string; bodyVariant: number; bodyMood?: string }> = {};
  for (const actor of visible(index)) {
    let carry: {emotion?: string; body_mood?: string | null} = {};
    let variant = 0;
    for (let i = 0; i <= index; i++) {
      const turn = lines[i], speaker = (turn.speakers || [turn.speaker]).includes(actor);
      if (!visible(i).includes(actor)) { carry = {}; if (speaker) variant++; continue; }
      if (speaker) { carry = {emotion:turn.emotion || "calm",body_mood:turn.body_mood}; variant++; }
      const current = {...carry, ...turn.actor_states?.[actor]};
      if (i < index) for (const segment of turn.performance_segments || []) {
        if (speaker) {current.emotion = segment.emotion || current.emotion || "calm"; current.body_mood = segment.body_mood;}
        Object.assign(current, segment.actor_states?.[actor]);
      }
      const mood = current.emotion || "calm";
      result[actor] = {mood,bodyVariant:Math.max(0,variant-1),...(current.body_mood ? {bodyMood:current.body_mood} : {})};
      if (speaker || turn.listener_state_persist !== false) carry = current;
    }
  }
  return result;
}

/** One world scale for every actor, with enough horizontal space for the widest outfit. */
export function stageFrameHeight(bounds: readonly StandBounds[], width: number, height: number, count: number): number | undefined {
  if (!bounds.length || width <= 0 || height <= 0 || count <= 0) return undefined;
  const aspect = width / count / height;
  return Math.max(...bounds.map(b => Math.max(b.height, b.width / aspect))) * 1.08;
}

/** Adjacent beats by one speaker form one continuous subtitle passage. */
export function speechPassage<T extends {speaker:string; kind?:string; speakers?:string[]; zh:string; ja:string}>(lines:readonly T[], index:number) {
  const current=lines[index];
  if(!current)return {zh:"",ja:""};
  const same=(line:T)=>line.speaker===current.speaker && line.kind===current.kind && JSON.stringify(line.speakers||[])===JSON.stringify(current.speakers||[]);
  let start=index,end=index;
  while(start>0&&same(lines[start-1]))start--;
  while(end+1<lines.length&&same(lines[end+1]))end++;
  return {zh:lines.slice(start,end+1).map(line=>line.zh).join(""),ja:lines.slice(start,end+1).map(line=>line.ja).join("")};
}
