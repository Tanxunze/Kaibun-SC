import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { StoryCastOrder } from "./StoryCastOrder";
import { stageCast, stagePoses } from "./stage";
import { timedSegments } from "./performance";
import { request, RequestError, type Actor, type Line, type PerformanceSegment, type Scene, type Story } from "./api";
import type { Emotion } from "@/lib/standAnimations";

const moods: Emotion[] = ["calm", "happy", "shy", "surprised", "sad", "angry", "thinking"];
const labels = {calm:"平静",happy:"开心",shy:"害羞",surprised:"惊讶",sad:"难过",angry:"生气",thinking:"思考"};

export function StoryFineTune({story, scene, line, actors, names, onPreview, onUpdated, onDeleted}: {
  story: Story; scene: Scene; line: Line; actors: Actor[]; names: Record<string,string>;
  onPreview: (preview: {line: Line; segment: number}) => void; onUpdated: (story: Story) => void; onDeleted: (story: Story) => void;
}) {
  const guests = story.guest_actors ?? [];
  const cast = [...(story.outline?.cast ?? []), ...guests.map(g => g.id)];
  const [draft, setDraft] = useState<Line>(() => ({...line, screen_cast: line.screen_cast ?? stageCast(scene.lines, scene.lines.indexOf(line), cast)}));
  const [segments, setSegments] = useState<PerformanceSegment[]>(() => line.performance_segments?.length && line.performance_segments.every(s => typeof s.ja === "string") ? structuredClone(line.performance_segments) : [{ja:line.ja, zh:line.zh, emotion:line.emotion, body_mood:line.body_mood, actor_states:structuredClone(line.actor_states || {})}]);
  const [active, setActive] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const token = useRef(crypto.randomUUID());
  const editBase = useRef(story.base_fingerprint);
  const cursors = useRef<Record<string, number>>({});

  const order = draft.actor_order || cast;
  const speakers = draft.speakers?.length ? draft.speakers : [draft.speaker];
  const inherited = stagePoses(scene.lines, scene.lines.findIndex(l=>l.id===line.id),cast);
  function resolvedSegments() {
    return timedSegments(segments.map(seg => ({...seg, actor_states:Object.fromEntries((draft.screen_cast || []).flatMap(id => {
      const state = {...draft.actor_states?.[id],...seg.actor_states?.[id]};
      return Object.keys(state).length ? [[id,state]] : [];
    }))})));
  }
  useEffect(() => { onPreview({line: {...draft, ja:segments.map(s => s.ja).join(""), zh:segments.map(s => s.zh).join(""), performance_segments:resolvedSegments()}, segment:active}); }, [draft, segments, active, onPreview]);
  function change(index: number, patch: Partial<PerformanceSegment>) { setActive(index); setSegments(v => v.map((s,i) => i === index ? {...s,...patch} : s)); }
  function split(index: number) {
    const seg = segments[index], ja = cursors.current[`${index}-ja`], zh = cursors.current[`${index}-zh`];
    if (!ja || ja >= seg.ja.length || !zh || zh >= seg.zh.length) { setError("请先在这个区间的日文、中文中分别点击要划分的位置。"); return; }
    setError(""); setSegments(v => v.flatMap((s,i) => i === index ? [{...s,ja:s.ja.slice(0,ja),zh:s.zh.slice(0,zh)},{...structuredClone(s),ja:s.ja.slice(ja),zh:s.zh.slice(zh)}] : [s])); setActive(index + 1);
  }
  async function save(regenerate: boolean) {
    setBusy(true); setError("");
    try {
      const updated = await request<Story>(`stories/${story.id}/lines/${line.id}/fine-tune`, {...draft, base_fingerprint:editBase.current, ja:segments.map(s => s.ja).join(""), zh:segments.map(s => s.zh).join(""), performance_segments:resolvedSegments(), speakers, edit_token:token.current, regenerate});
      token.current = crypto.randomUUID(); editBase.current = updated.base_fingerprint; onUpdated(updated);
    } catch(e) {
      // The text was committed before synthesis failed. Retry against that exact saved version.
      if (e instanceof RequestError && e.savedFingerprint) editBase.current = e.savedFingerprint;
      setError(e instanceof Error ? e.message : "保存失败"); token.current = crypto.randomUUID();
    }
    finally { setBusy(false); }
  }
  return <div className="flex flex-col gap-4 rounded-lg border p-4">
    <fieldset className="flex flex-wrap gap-2"><legend>出场人物与站位</legend><StoryCastOrder actors={[...actors, ...guests].filter(a => cast.includes(a.id))} order={order} selected={draft.screen_cast || []} onOrder={actor_order => setDraft(v => ({...v,actor_order}))} onSelected={screen_cast => setDraft(v => ({...v,screen_cast}))} /></fieldset>
    <fieldset className="flex flex-wrap gap-2"><legend>发言配音</legend>{[...(story.outline?.cast ?? []), ...(story.outline?.guests ?? []).map(g => g.id), "producer"].map(id => <label key={id} className="flex items-center gap-1 rounded-lg border px-3 py-2 text-sm"><input type="checkbox" checked={speakers.includes(id)} onChange={e => {
      const people = e.target.checked ? id === "producer" ? [id] : [...speakers.filter(s => s !== "producer"),id] : speakers.filter(s => s !== id);
      if (people.length) setDraft(v => ({...v,speaker:people[0],speakers:people.length > 1 ? people : undefined}));
    }} />{names[id]}</label>)}</fieldset>
    {speakers.includes("fuyuko") && <label>声线 <select aria-label="声线" value={draft.voice_style || "natural"} onChange={e => setDraft(v => ({...v,voice_style:e.target.value as "natural" | "idol"}))}><option value="natural">本音</option><option value="idol">夹子音</option></select></label>}
    {speakers.includes('nichika') && <label>日花声线 <select aria-label="日花声线" value={draft.nichika_voice_style || 'natural'} onChange={e=>setDraft(v=>({...v,nichika_voice_style:e.target.value as 'natural' | 'idol'}))}><option value="natural">本音</option><option value="idol">偶像声线</option></select></label>}
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.listener_state_persist !== false} onChange={e=>setDraft(v=>({...v,listener_state_persist:e.target.checked}))} />将非发言角色的表情与动作延续到后续台词（同场景内，直到本人发言、离开画面或被新设置覆盖）</label>
    <div className="flex flex-col gap-3"><p>句内演出区间</p><p className="text-sm text-muted-foreground">整句只播放一次。分别在日文、中文中点击划分位置，再划分区间。点击预览即可检查人物演出，无需生成语音。播放切换位置按日文长度估算。</p>
      {segments.map((seg,i) => <div key={i} className="flex flex-col gap-3 rounded-lg border p-3" data-performance-segment={i}>
        <div className="flex flex-wrap items-center gap-2"><span>区间 {i+1}</span><Button variant={active === i ? "secondary" : "outline"} onClick={() => setActive(i)}>预览区间 {i+1}</Button><Button variant="outline" disabled={busy || segments.length >= 20} onClick={() => split(i)}>在光标处划分</Button>{i > 0 && <Button variant="ghost" disabled={busy} onClick={() => {setSegments(v => v.flatMap((s,j) => j === i-1 ? [{...s,ja:s.ja+v[i].ja,zh:s.zh+v[i].zh}] : j === i ? [] : [s]));setActive(i-1);}}>并入上一区间</Button>}</div>
        {(["ja","zh"] as const).map(lang => <label key={lang} className="flex flex-col gap-1 text-sm">{lang === "ja" ? "日文" : "中文"}<Textarea aria-label={`区间${i+1}${lang === "ja" ? "日文" : "中文"}`} value={seg[lang]} onSelect={e => {cursors.current[`${i}-${lang}`] = e.currentTarget.selectionStart;}} onChange={e => change(i,{[lang]:e.target.value})} /></label>)}
        {(draft.screen_cast || []).map(id => {
          const state = {emotion:(inherited[id]?.mood || "calm") as Emotion,body_mood:inherited[id]?.bodyMood as Emotion | undefined,...(speakers.includes(id) ? {emotion:seg.emotion,body_mood:seg.body_mood} : {}),...draft.actor_states?.[id],...seg.actor_states?.[id]};
          const update = (patch: Partial<typeof state>) => change(i,{actor_states:{...seg.actor_states,[id]:{...seg.actor_states?.[id],...patch}}});
          return <div key={id} className="flex flex-wrap items-center gap-3 text-sm"><span>{names[id]}{speakers.includes(id) ? " · 发言" : ""}</span><label>表情 <select aria-label={`区间${i+1}${names[id]}表情`} value={state.emotion || "calm"} onChange={e => update({emotion:e.target.value as Emotion})}>{moods.map(m => <option key={m} value={m}>{labels[m]}</option>)}</select></label><label>动作 <select aria-label={`区间${i+1}${names[id]}动作`} value={state.body_mood || ""} onChange={e => update({body_mood:e.target.value as Emotion || null})}><option value="">随表情</option>{moods.map(m => <option key={m} value={m}>{m === "calm" ? "待机" : labels[m]}</option>)}</select></label></div>;
        })}
      </div>)}
    </div>
    <p className="text-sm text-muted-foreground">仅调整演出会保留原配音。修改台词、发言人物或声线后，请生成语音。</p>
    {error && <p role="alert">{error}</p>}
    <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void save(false)}>保存</Button><Button disabled={busy} onClick={() => void save(true)}>保存并生成语音</Button><Button variant="outline" disabled={busy} onClick={async () => { if (!window.confirm("删除这句台词及其演出设置？")) return; setBusy(true); try {onDeleted(await request<Story>(`stories/${story.id}/lines/${line.id}/delete`,{}));} catch(e) {setError(e instanceof Error ? e.message : "删除失败");} finally {setBusy(false);} }}>删除本句</Button></div>
  </div>;
}
