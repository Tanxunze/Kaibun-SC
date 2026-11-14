import type { Line, PerformanceSegment } from "./api";

export function segmentAt(segments: Line["performance_segments"], progress: number) {
  return (segments || []).reduce((last, seg, i) => progress >= (seg.start ?? i / segments!.length) ? i : last, 0);
}

export function performancePose(line: Line, segment: PerformanceSegment | undefined, id: string, base = {mood: "calm", bodyVariant: 0} as {mood: string; bodyVariant: number; bodyMood?: string}) {
  const speaker = (line.speakers || [line.speaker]).includes(id);
  const state = segment?.actor_states?.[id];
  if (state) return {...base, mood: state.emotion || base.mood, bodyMood: state.body_mood || state.emotion || base.mood};
  if (segment && speaker) return {...base, mood: segment.emotion, bodyMood: segment.body_mood || segment.emotion};
  return base;
}

export function timedSegments(segments: PerformanceSegment[]) {
  const length = segments.reduce((n, s) => n + s.ja.length, 0);
  let offset = 0;
  return segments.map(s => { const start = offset / Math.max(1, length); offset += s.ja.length; return {...s, start}; });
}
