"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { StoryFineTune } from "./StoryFineTune";
import { performancePose, segmentAt } from "./performance";
import { StoryStage } from "./StoryStage";
import { stageCast, stagePoses, speechPassage, orderedStageCast } from "./stage";
import { StoryLibrary } from "./StoryLibrary";
import { StoryOutfits } from "./StoryOutfits";
import { SceneOutfits } from "./SceneOutfits";
import { StoryBackgrounds } from "./StoryBackgrounds";
import { StoryVoiceControls } from "./StoryVoiceControls";
import { StoryImport } from "./StoryImport";
import { StoryTune } from "./StoryTune";
import { scenePresentation } from "./presentation";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { copy } from "@/i18n";
import { cn } from "@/lib/utils";
import { BackIcon, StoryIcon, StoryNewIcon, StoryPlayIcon, StoryPauseIcon, StoryPreviousIcon, StoryNextIcon, LetterSoundIcon, LetterMutedIcon } from "@/theme/icons";
import { Ja } from "@/theme/Ja";
import { request, migrateOutfitDefaults, type Actor, type Story, type StoryBrief, type StoryLength, type Line } from "./api";

const t = copy.kaibun;

function pruneDeletedStoryDrafts(stories: StoryBrief[]) {
  const ids = new Set(stories.map(story => story.id));
  try {
    for (const key of Object.keys(localStorage)) {
      const match = /^(?:kaibun-position-|kaibun-tune-draft-)([a-f0-9]{32})$/.exec(key);
      if (match && !ids.has(match[1])) localStorage.removeItem(key);
    }
    const composer = JSON.parse(localStorage.getItem("kaibun-composer-draft") || "null");
    if (composer?.continuing && !ids.has(composer.continuing)) localStorage.removeItem("kaibun-composer-draft");
  } catch {}
}

export function KaibunPage() {
  const [actors, setActors] = useState<Actor[]>([]);
  const [stories, setStories] = useState<StoryBrief[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [story, setStory] = useState<Story | null>(null);
  const [premise, setPremise] = useState("");
  const [cast, setCast] = useState<string[]>([]);
  const [details, setDetails] = useState("");
  const [outfits, setOutfits] = useState<Record<string, string>>({});
  const [outfitMode, setOutfitMode] = useState<"story" | "fixed">("story");
  const [continuing, setContinuing] = useState<string | null>(null);
  const [length, setLength] = useState<StoryLength>("short");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hasModel, setHasModel] = useState<boolean | null>(null);
  const [voice, setVoice] = useState(false);
  const deleted = useRef(new Set<string>());
  const draftLoaded = useRef(false);
  const draftNeedsOutfitMigration = useRef(false);
  useEffect(() => {
    try {
      const draft = JSON.parse(localStorage.getItem("kaibun-composer-draft") || "null");
      if (draft) { draftNeedsOutfitMigration.current = draft.outfitPolicyVersion !== 1; setPremise(draft.premise || ""); setDetails(draft.details || ""); setCast(draft.cast || []); setOutfits(draft.outfits || {}); setOutfitMode(draft.outfitMode || "story"); setLength(draft.length || "short"); setContinuing(draft.continuing || null); }
    } catch {} finally { setTimeout(() => { draftLoaded.current = true; }, 0); }
  }, []);
  useEffect(() => {
    if (selected || !draftLoaded.current || !actors.length) return;
    try { localStorage.setItem("kaibun-composer-draft", JSON.stringify({ premise, details, cast, outfits, outfitMode, length, continuing, outfitPolicyVersion:1 })); } catch {}
  }, [selected, premise, details, cast, outfits, outfitMode, length, continuing, actors.length]);
  const readLibrary = useCallback(() => request<StoryBrief[]>("stories").then(items => { pruneDeletedStoryDrafts(items); setStories(items.filter(item => !deleted.current.has(item.id))); }), []);
  useEffect(() => {
    let active = true;
    Promise.all([request<Actor[]>("characters"), request<StoryBrief[]>("stories"), request<{ voice: boolean; model: string | null }>("health")])
      .then(([actors, stories, health]) => { if (active) { if (draftNeedsOutfitMigration.current) {setOutfits(current => migrateOutfitDefaults(current,actors));draftNeedsOutfitMigration.current=false;} setActors(actors); setStories(stories); setVoice(health.voice); setHasModel(Boolean(health.model)); pruneDeletedStoryDrafts(stories); } })
      .catch((e) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!selected) { setStory(null); return; }
    let active = true;
    const read = () => request<Story>("stories/" + selected).then((doc) => {
      if (active && !deleted.current.has(selected)) { setStory(doc); setError(""); }
    }).catch((e) => { if (active && !deleted.current.has(selected)) setError(e.message); });
    setStory(null); void read();
    const timer = setInterval(() => { void read(); void readLibrary().catch(() => {}); }, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [selected, readLibrary]);

  async function create(tuning = false) {
    if (!premise.trim() || busy) return;
    setBusy(true); setError("");
    try {
      if (continuing) {
        await request("stories/" + continuing + "/continue", { instruction: details || premise, cast, outfits: Object.fromEntries(cast.filter(id => outfits[id]).map(id => [id, outfits[id]])), length, outfit_mode: outfitMode, tuning });
        setSelected(continuing); setContinuing(null); await readLibrary(); return;
      }
      const doc = await request<Story>("stories", { premise, cast, length, details, tuning, outfit_mode: outfitMode, outfits: Object.fromEntries(cast.filter(id => outfits[id]).map(id => [id, outfits[id]])) });
      setSelected(doc.id); setStory(doc); await readLibrary();
    } catch (e) { setError(e instanceof Error ? e.message : t.unavailable); }
    finally { setBusy(false); }
  }
  async function pin(item: StoryBrief) {
    try { await request("stories/" + item.id + "/pin", { pinned: !item.pinned }); await readLibrary(); }
    catch (e) { setError(e instanceof Error ? e.message : t.unavailable); }
  }
  async function remove(item: StoryBrief) {
    if (!window.confirm(`删除“${item.title || item.premise}”？这会一并清除该故事的配音、导出视频、演出缓存和备份。`)) return;
    try {
      await request("stories/" + item.id + "/delete", {});
      try {
        localStorage.removeItem("kaibun-position-" + item.id);
        localStorage.removeItem("kaibun-tune-draft-" + item.id);
        const composer = JSON.parse(localStorage.getItem("kaibun-composer-draft") || "null");
        if (composer?.continuing === item.id) localStorage.removeItem("kaibun-composer-draft");
      } catch {}
      deleted.current.add(item.id);
      setSelected(current => current === item.id ? null : current);
      setStory(current => current?.id === item.id ? null : current);
      setStories(current => current.filter(story => story.id !== item.id));
      await readLibrary();
    } catch (e) { setError(e instanceof Error ? e.message : t.unavailable); }
  }
  async function rename(item: StoryBrief) {
    const title = window.prompt("重命名", item.title || item.premise);
    if (!title?.trim()) return;
    try { await request("stories/" + item.id + "/rename", { title: title.trim() }); await readLibrary(); if (selected === item.id) setStory(await request<Story>("stories/" + item.id)); }
    catch (e) { setError(e instanceof Error ? e.message : t.unavailable); }
  }
  async function revise(item: Story) {
    try { const copy = await request<Story>("stories/" + item.id + "/revise", {}); setSelected(copy.id); setStory(copy); await readLibrary(); }
    catch (e) { setError(e instanceof Error ? e.message : t.unavailable); }
  }
  const library = <StoryLibrary stories={stories} selected={selected} onSelect={setSelected} onPin={item => { void pin(item); }} onDelete={item => { void remove(item); }} onRename={item => { void rename(item); }} />;

  return <div className="flex min-h-dvh flex-col bg-background text-foreground">
    <header className="flex min-h-16 items-center justify-between gap-4 border-b px-4 md:px-6">
      <div className="flex items-center gap-3"><StoryIcon className="size-5" /><span className="text-header">{t.title}</span></div>
      <a href="/about" className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"><BackIcon className="size-4" />使用说明与来源</a>
    </header>
    <div className="flex min-h-0 flex-1">
      <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 overflow-y-auto border-r lg:block">
        <div className="flex items-center justify-between px-4 pt-5 pb-3"><h2 className="text-row-name">{t.library}</h2><Button variant="ghost" size="icon-lg" aria-label={t.newStory} onClick={() => { setContinuing(null); setSelected(null); }}><StoryNewIcon /></Button></div>
        {library}
      </aside>
      <main className="min-w-0 flex-1">
        <div className="flex items-center justify-between border-b px-4 py-2 lg:hidden"><details className="relative"><summary className="cursor-pointer py-1 text-sm">{t.library} · {stories.length}</summary><div className="absolute left-0 z-20 max-h-96 w-72 overflow-y-auto rounded-lg border bg-background">{library}</div></details><Button variant="ghost" onClick={() => { setContinuing(null); setSelected(null); }}><StoryNewIcon />{t.newStory}</Button></div>
        {error && <div role="alert" className="mx-auto mt-4 flex max-w-4xl items-center gap-3 rounded-lg border px-4 py-3 text-sm"><span className="min-w-0 flex-1">{error}</span><Button variant="outline" onClick={() => window.location.reload()}>{t.retry}</Button></div>}
        {selected ? story ? story.tuning && story.tuning !== "production" ? <StoryTune key={story.id} story={story} actors={actors} onUpdated={setStory} /> : <StoryView key={story.id} story={story} actors={actors} voice={voice} onUpdated={setStory} onRevise={() => { void revise(story); }} onContinue={() => { void request<Story>("stories/" + story.id + "/pause-for-edit", {}).then(() => { setContinuing(story.id); setCast(story.outline?.cast ?? []); setOutfits(migrateOutfitDefaults(story.scenes.at(-1)?.outfits ?? {}, actors)); setLength(story.length); setPremise(story.premise); setDetails(""); setSelected(null); }).catch(e => setError(e.message)); }} onResume={() => { void request("stories/" + story.id + "/resume", {}).catch((e) => setError(e.message)); }} /> : <p role="status" className="p-8 text-sm text-muted-foreground">{t.loading}</p> :
          <div className="mx-auto flex max-w-3xl flex-col gap-8 px-5 py-12 md:px-10 md:py-20">
            <div className="flex flex-col gap-3"><h1 className="text-3xl font-semibold tracking-tight md:text-4xl">{continuing ? "续写" : t.newStory}</h1></div>
            <StoryImport expanded={hasModel === false} cast={cast} onImported={doc => {setSelected(doc.id);setStory(doc);void readLibrary();}} />
            <form className="flex flex-col gap-5" onSubmit={(event) => { event.preventDefault(); void create(); }}>
              <Textarea rows={4} value={premise} maxLength={2000} aria-label={t.placeholder} placeholder={t.placeholder} onChange={(e) => setPremise(e.target.value)} />
              <div className="flex flex-wrap items-center gap-2"><span className="mr-2 text-sm text-muted-foreground">{t.length}</span>{(["short", "standard", "half_hour", "hour_plus"] as const).map((value) => <Button type="button" variant={length === value ? "secondary" : "ghost"} key={value} aria-pressed={length === value} onClick={() => setLength(value)}>{t[value]}</Button>)}</div>
              <details><summary className="cursor-pointer text-sm">{t.cast}{cast.length ? " · " + cast.length : ""}</summary><div className="mt-3 flex flex-wrap gap-2">{actors.map((actor) => <button type="button" key={actor.id} aria-pressed={cast.includes(actor.id)} onClick={() => setCast((list) => list.includes(actor.id) ? list.filter((id) => id !== actor.id) : [...list, actor.id])} className={cn("flex items-center gap-2 rounded-full border px-3 py-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-40", cast.includes(actor.id) ? "bg-muted" : "hover:bg-muted/60")}><MarkedAvatar name={actor.name} src={actor.avatar_url} size="sm" />{actor.short_name ?? actor.name}</button>)}</div></details>
              {cast.length > 0 && <StoryOutfits actors={actors} cast={cast} outfits={outfits} onChange={(id, value) => setOutfits(current => ({ ...current, [id]: value }))} />}
              <div className="flex flex-wrap items-center gap-2 text-sm"><span>服装安排</span><Button type="button" variant={outfitMode === "story" ? "secondary" : "ghost"} aria-pressed={outfitMode === "story"} onClick={() => setOutfitMode("story")}>随剧情换装</Button><Button type="button" variant={outfitMode === "fixed" ? "secondary" : "ghost"} aria-pressed={outfitMode === "fixed"} onClick={() => setOutfitMode("fixed")}>全篇固定</Button></div>
              <label className="flex flex-col gap-2 text-sm">{t.details}<Textarea rows={3} value={details} maxLength={12000} placeholder={t.detailsPlaceholder} onChange={event => setDetails(event.target.value)} /></label>
              {hasModel === false && <p className="text-sm text-muted-foreground">导入自写剧本可直接开始。使用 AI 创作时，请在 .env 配置文字模型后重启。</p>}
              <div className="flex items-center gap-4 border-t pt-5"><Button type="submit" size="lg" disabled={!hasModel || busy || premise.trim().length < 2 || !actors.length}>{busy ? <Spinner /> : <StoryIcon />}{busy ? t.generating : continuing ? "开始续写" : t.generate}</Button><Button type="button" variant="outline" disabled={!hasModel || busy || premise.trim().length < 2 || !actors.length} onClick={() => { void create(true); }}>剧本精调</Button></div>
            </form>
          </div>}
      </main>
    </div>
  </div>;
}

function StoryView({ story, actors, voice, onResume, onUpdated, onContinue, onRevise }: { story: Story; actors: Actor[]; voice: boolean; onResume: () => void; onUpdated: (story: Story) => void; onContinue: () => void; onRevise: () => void }) {
  const [watching, setWatching] = useState(false);
  const [script, setScript] = useState(false);
  const [fine, setFine] = useState(false);
  const [fineLine, setFineLine] = useState<string | null>(null);
  const [preview, setPreview] = useState<{line: Line; segment: number} | null>(null);
  const [jump, setJump] = useState<{id: string; token: number} | null>(null);
  const [actionError, setActionError] = useState("");
  const playerTop = useRef<HTMLDivElement>(null);
  const scriptPanel = useRef<HTMLDivElement>(null);
  const [currentLine, setCurrentLine] = useState<string | null>(null);
  const [locate, setLocate] = useState<{id: string; token: number} | null>(null);
  function openScript(edit: boolean) {
    const entries = story.scenes.flatMap(scene => scene.lines.filter(line => line.speaker !== "narrator").map(line => ({line,scene})));
    let id = currentLine;
    if (!id) {
      let position = 0;
      try { position = Number(localStorage.getItem("kaibun-position-" + story.id)) || 0; } catch {}
      id = entries[Math.min(position, entries.length - 1)]?.line.id ?? null;
    }
    setScript(true);
    if (!id) return;
    setLocate({id, token: Date.now()});
    if (edit) {
      const entry = entries.find(entry => entry.line.id === id);
      if (!entry) return;
      setFineLine(id); setPreview(null);
      setJump({id, token: Date.now()});
    }
  }
  useEffect(() => {
    if (!script || !locate || !scriptPanel.current) return;
    const panel = scriptPanel.current;
    const timer = requestAnimationFrame(() => {
      const target = Array.from(panel.querySelectorAll<HTMLElement>("[data-script-line]")).find(node => node.dataset.scriptLine === locate.id);
      if (target) panel.scrollTop += target.getBoundingClientRect().top - panel.getBoundingClientRect().top;
    });
    return () => cancelAnimationFrame(timer);
  }, [script, locate]);
  const unfinished = story.status !== "ready";
  const names = Object.fromEntries(actors.map((actor) => [actor.id, actor.name]));
  names.producer = t.producer; names.narrator = t.narrator;
  for (const guest of story.outline?.guests ?? []) names[guest.id] = guest.name;
  return <div className={cn("mx-auto flex max-w-7xl flex-col gap-5 px-4 py-6 md:px-8 md:py-8", script && watching && "h-dvh overflow-hidden")}>
    <div className="flex flex-wrap items-start justify-between gap-4"><div className="flex min-w-0 flex-1 flex-col gap-2"><p className="text-meta text-muted-foreground">{t.title} · {t.status[story.status]}</p><h1 className="text-2xl font-semibold tracking-tight">{story.title || story.premise}</h1></div><Button variant="ghost" onClick={() => { if (script) setScript(false); else openScript(false); }}>{script ? t.closeScript : t.read}</Button></div>
    {unfinished && <div role="status" className="flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 text-sm">{story.status === "generating" || story.status === "preparing" || story.status === "queued" ? <Spinner /> : null}<span className="flex-1">{story.phase}{story.outline ? " · " + t.scene(story.scenes.length, story.outline.scenes.length) : ""}</span>{story.status === "generating" || story.status === "preparing" || story.status === "queued" ? <Button variant="outline" onClick={() => { void request("stories/" + story.id + "/stop", {}).catch((e) => setActionError(e.message)); }}>停止</Button> : null}{story.status === "failed" || story.status === "interrupted" ? <Button variant="outline" onClick={onResume}>{t.resume}</Button> : null}</div>}
    {story.error && <p role="alert" className="text-sm text-muted-foreground">{story.error}</p>}
    <div ref={playerTop} className={cn(script && watching && "sticky top-0 z-30 bg-background")} />{actionError && <p role="alert">{actionError}</p>}{story.scenes.length ? <div className={cn(script && watching && "sticky top-0 z-30 bg-background")} >{!watching ? <div className="flex min-h-72 flex-col items-center justify-center gap-5 rounded-2xl bg-muted/50"><div className="flex -space-x-2">{(story.outline?.cast ?? []).map((id) => { const actor = actors.find((a) => a.id === id); return actor ? <MarkedAvatar key={id} name={actor.name} src={actor.avatar_url} size="list" /> : null; })}</div><p className="text-sm text-muted-foreground">{t.scene(story.scenes.length, story.outline?.scenes.length ?? 0)}</p><Button size="lg" onClick={() => setWatching(true)}><StoryPlayIcon />{unfinished ? t.watchFirst : t.watch}</Button></div> : <StoryPlayer story={story} actors={actors} names={names} voice={voice} jump={jump} compact={script} editing={fine} onUpdated={onUpdated} preview={fine ? preview : null} onPosition={setCurrentLine} />}</div> : <div className="flex min-h-72 items-center justify-center rounded-2xl bg-muted/50"><StoryIcon className="size-10 text-muted-foreground" /></div>}
    {story.scenes.length > 0 && !["generating", "preparing", "queued"].includes(story.status) && <Button variant="outline" onClick={() => { if (fine) setFine(false); else { setFine(true); setWatching(true); openScript(true); } }}>微调</Button>}
    {!script && story.outline && <details className="rounded-lg border px-4 py-3"><summary className="cursor-pointer text-sm">{t.outline}</summary><p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-muted-foreground">{story.outline.opening?.trim() || story.premise}</p></details>}
    {!script && story.scenes.length > 0 && ["ready", "failed", "interrupted"].includes(story.status) && <StoryBackgrounds story={story} onUpdated={onUpdated} />}
    {!script && story.outline && story.scenes.length > 0 && ["ready", "failed", "interrupted"].includes(story.status) && <SceneOutfits story={story} actors={actors} onUpdated={onUpdated} />}
    {!script && story.outline && story.scenes.length >= story.outline.scenes.length && <div className="flex flex-wrap items-center gap-2"><Button variant="outline" onClick={onContinue}>续写</Button><Button variant="outline" onClick={onRevise}>调整剧本</Button>{story.status === "ready" && <StoryExport storyId={story.id} scenes={story.scenes} />}</div>}
    {script && <div ref={scriptPanel} className="min-h-0 flex-1 overflow-y-auto">{story.scenes.map(scene => <section key={scene.index} className="flex flex-col gap-4 border-t pt-5">
      <h2 className="text-header">第{scene.index + 1}幕 · {scene.place}</h2>
      {scene.lines.filter(line => line.speaker !== "narrator").map(line => <div key={line.id} data-script-line={line.id}>
        <button type="button" className="flex w-full gap-3 rounded-lg p-2 text-left hover:bg-muted" onClick={() => { setWatching(true); setJump({id: line.id, token: Date.now()}); if (fine) { setFineLine(line.id); setPreview(null); } }}>
          <span className="w-24 shrink-0 text-subtitle text-muted-foreground">{line.speakers?.length ? "多人" : names[line.speaker] ?? line.speaker}</span>
          <div><p className="text-japanese-line"><Ja>{line.ja}</Ja></p><p className="text-subtitle text-muted-foreground">{line.zh}</p></div>
        </button>
        {fine && fineLine === line.id && <StoryFineTune key={line.id} story={story} scene={scene} line={line} actors={actors} names={names} onPreview={setPreview} onUpdated={onUpdated} onDeleted={updated => { setPreview(null); const next = updated.scenes.flatMap(s => s.lines).find(l => l.speaker !== "narrator"); setFineLine(next?.id ?? null); if (next) setJump({id: next.id, token: Date.now()}); onUpdated(updated); }} />}
      </div>)}
    </section>)}</div>}
  </div>;
}

function StoryExport({ storyId, scenes }: { storyId: string; scenes: Story["scenes"] }) {
  const [scope, setScope] = useState("");
  const suffix = scope ? `?scene=${scope}` : "";
  const [job, setJob] = useState<{status: string; message: string; progress: number}>({status: "idle", message: "", progress: 0});
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const update = () => request<typeof job>(`stories/${storyId}/export${suffix}`).then(value => { if (active) setJob(value); }).catch(() => {});
    void update();
    const timer = setInterval(update, 2500);
    return () => { active = false; clearInterval(timer); };
  }, [storyId, suffix]);
  async function start() {
    setError("");
    try {
      const check = await request<{missing_audio:string[];performance_review:string[];untranslated:string[];ready:boolean}>(`stories/${storyId}/export-check${suffix}`);
      if (check.untranslated.length) throw new Error("导入剧本还有未整理的日文和中文台词，请先完成剧本整理。");
      if (check.performance_review.length) throw new Error("有台词文字变化后尚未重新划分演出区间；视频将使用第一区间动作。");
      setJob(await request<typeof job>(`stories/${storyId}/export${suffix}`, {}));
    }
    catch (e) { setError(e instanceof Error ? e.message : "导出失败，请重试"); }
  }
  async function stop() { try { setJob(await request<typeof job>(`stories/${storyId}/export/stop${suffix}`, {})); } catch (e) { setError(e instanceof Error ? e.message : "暂停失败，请重试"); } }
  return <><select aria-label="导出范围" disabled={job.status === "working"} value={scope} onChange={e => {setScope(e.target.value); setJob({status:"idle",message:"",progress:0});}}><option value="">全部导出</option>{scenes.map((scene,i) => <option key={i} value={String(i)}>第{i+1}幕 · {scene.place}</option>)}</select><Button variant="outline" disabled={job.status === "working"} onClick={() => { void start(); }}>导出视频</Button>{job.status === "working" && <><span role="status" className="text-sm text-muted-foreground">{job.message} · {job.progress}%</span><Button variant="ghost" onClick={() => { void stop(); }}>暂停</Button></>}{job.status === "ready" && <a className="text-sm underline" download href={`/api/kaibun/stories/${storyId}/export/download${suffix}`}>下载视频</a>}{job.status === "interrupted" && <span className="text-sm text-muted-foreground">{job.message}</span>}{(error || job.status === "failed") && <span role="alert" className="text-sm text-destructive">{error || job.message}</span>}</>;
}

function StoryPlayer({ story, actors, names, voice, jump, compact, editing, preview, onPosition, onUpdated }: { story: Story; actors: Actor[]; names: Record<string, string>; voice: boolean; jump: { id: string; token: number } | null; compact: boolean; editing: boolean; preview: {line: Line; segment: number} | null; onPosition: (id: string) => void; onUpdated:(story:Story)=>void }) {
  const [index, setIndex] = useState(() => {
    const position = jump ? story.scenes.flatMap((scene) => scene.lines.filter((line) => line.speaker !== "narrator")).findIndex((line) => line.id === jump.id) : 0;
    if (jump) return Math.max(0, position);
    try { return Math.max(0, Number(localStorage.getItem("kaibun-position-" + story.id)) || 0); } catch { return 0; }
  });
  const [playing, setPlaying] = useState(!jump);
  useEffect(() => { if (editing && preview) setPlaying(false); }, [editing, preview]);
  const [sound, setSound] = useState(voice);
  const [speaking, setSpeaking] = useState(false);
  const [segmentIndex, setSegmentIndex] = useState(0);
  const [notice, setNotice] = useState("");
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const lines = story.scenes.flatMap((scene) => scene.lines.filter((line) => line.speaker !== "narrator").map((line) => ({ ...line, scene })));
  const savedLine = lines[index];
  const line = editing && preview && preview.line.id === savedLine?.id ? {...preview.line, scene: savedLine.scene} : savedLine;
  const voiceKey = savedLine ? JSON.stringify([savedLine.id, savedLine.ja, savedLine.emotion, savedLine.voice_style, savedLine.nichika_voice_style, savedLine.speakers, savedLine.audio_revision]) : "";
  useEffect(() => { if (line) onPosition(line.id); }, [line?.id, onPosition]);
  useEffect(() => { try { if (lines.length) localStorage.setItem("kaibun-position-" + story.id, String(Math.min(index, lines.length - 1))); } catch {} }, [index, story.id, lines.length]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input,textarea,select,[contenteditable=true]")) return;
      if ((event.code === "Space" || event.key === " " || event.key === "Spacebar") && !event.ctrlKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        event.stopPropagation();
        if (!event.repeat) setPlaying(value => !value);
      }
      else if (event.key === "ArrowLeft") { event.preventDefault(); setIndex(value => Math.max(0, value - 1)); }
      else if (event.key === "ArrowRight" || event.key === "Enter") { event.preventDefault(); setIndex(value => Math.min(lines.length, value + 1)); }
    };
    window.addEventListener("keydown", key, { capture: true });
    return () => window.removeEventListener("keydown", key, { capture: true });
  }, [lines.length]);
  useEffect(() => {
    setSegmentIndex(0);
    if (jump) { const position = lines.findIndex((l) => l.id === jump.id); if (position >= 0) { setIndex(position); setPlaying(false); } }
  }, [jump]);
  const cache = useRef(new Map<string, string>());
  const requests = useRef(new Map<string, Promise<string>>());
  const audioLifecycle = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    audioLifecycle.current = controller;
    return () => {
      controller.abort();
      for (const url of cache.current.values()) URL.revokeObjectURL(url);
      cache.current.clear();
      requests.current.clear();
    };
  }, []);
  const next = useCallback(() => setIndex((value) => value + 1), []);
  const storyRef = useRef(story); storyRef.current = story;
  const audioFor = useCallback((lineId: string) => {
    const source = storyRef.current.scenes.flatMap(s => s.lines).find(l => l.id === lineId.split("~")[0]);
    const key = JSON.stringify([lineId, source?.ja, source?.emotion, source?.voice_style, source?.nichika_voice_style, source?.audio_revision]);
    const existing = cache.current.get(key);
    if (existing) return Promise.resolve(existing);
    const pending = requests.current.get(key);
    if (pending) return pending;
    const signal = audioLifecycle.current?.signal;
    const job = fetch("/api/kaibun/stories/" + story.id + "/audio/" + lineId, { cache: "no-store", signal }).then(async (r) => {
      if (!r.ok) throw new Error(t.voiceFailed);
      const blob = await r.blob();
      if (signal?.aborted) throw new Error(t.voiceFailed);
      const url = URL.createObjectURL(blob);
      cache.current.set(key, url);
      return url;
    }).finally(() => requests.current.delete(key));
    requests.current.set(key, job);
    return job;
  }, [story.id]);
  const nextLine = lines[index + 1];
  const [transitioning, setTransitioning] = useState(false);
  const [transitionEffect, setTransitionEffect] = useState("");
  const previousLine = useRef<{scene: number; id: string} | null>(null);
  useEffect(() => {
    if (!line) return;
    const previous = previousLine.current;
    previousLine.current = {scene: line.scene.index, id: line.id};
    const effect = previous && previous.scene !== line.scene.index ? line.scene.transition : line.scene.line_transitions?.[line.id];
    if (!playing || !previous || previous.id === line.id || !effect || effect === "cut") {setTransitioning(false);return;}
    setTransitionEffect(effect); setTransitioning(true);
    const duration = previous.scene !== line.scene.index ? line.scene.transition_length : line.scene.line_transition_lengths?.[line.id];
    const timer = setTimeout(() => setTransitioning(false), ({short:400,medium:800,long:1400} as const)[duration || "short"]);
    return () => clearTimeout(timer);
  }, [line?.id]);
  useEffect(() => {
    if (!playing || !savedLine || transitioning) return;
    const line = savedLine;
    let active = true;
    let audio: HTMLAudioElement[] = [];
    let timer: ReturnType<typeof setTimeout> | undefined;
    setNotice(""); setSpeaking(false); setSegmentIndex(0);
    let segmentTimer: ReturnType<typeof setInterval> | undefined;
    const subtitleTimer = () => { const duration = line.kind === "thought" ? Math.min(20000, Math.max(5000, line.zh.length * 150)) : Math.min(12000, Math.max(3000, line.zh.length * 115)); const started = Date.now(); clearInterval(segmentTimer); segmentTimer = setInterval(() => setSegmentIndex(segmentAt(line.performance_segments, (Date.now() - started) / duration)), 100); timer = setTimeout(() => { if (active) next(); }, line.kind === "thought" ? Math.min(20000, Math.max(5000, line.zh.length * 150)) : Math.min(12000, Math.max(3000, line.zh.length * 115))); };
    if (!sound || !(line.speaker === "producer" || actors.some((a) => a.id === line.speaker))) subtitleTimer();
    else {
      const ids = line.speakers?.length ? line.speakers.map(id => line.id + "~" + id) : [line.id];
      Promise.all(ids.map(audioFor)).then((urls) => {
        if (!active) return;
        audio = urls.map(url => new Audio(url));
        segmentTimer = setInterval(() => { const duration = Math.max(...audio.map(a => Number.isFinite(a.duration) ? a.duration : 0)); const elapsed = Math.max(...audio.map(a => a.currentTime)); if(duration > 0) setSegmentIndex(segmentAt(line.performance_segments, elapsed / duration)); }, 100);
        let remaining = audio.length;
        for (const player of audio) {
          player.onplaying = () => { if (active) { setNotice(""); setSpeaking(true); } };
          player.onended = () => { if (active && --remaining === 0) { setSpeaking(false); timer = setTimeout(next, 450); } };
          player.onerror = () => { if (active) { setSpeaking(false); setNotice(t.voiceFailed); subtitleTimer(); } };
        }
        return Promise.all(audio.map(player => player.play()));
      }).then(() => {
        if (active && nextLine && !nextLine.speakers?.length && actors.some((a) => a.id === nextLine.speaker)) void audioFor(nextLine.id).catch(() => {});
      }).catch(() => { if (active) { setSpeaking(false); setNotice(t.voiceFailed); subtitleTimer(); } });
    }
    return () => { active = false; clearTimeout(timer); clearInterval(segmentTimer); audio.forEach(player => player.pause()); setSpeaking(false); };
  }, [voiceKey, playing, sound, audioFor, next, transitioning]);
  const cast = story.outline?.cast ?? [];
  const focused = orderedStageCast(line?.screen_cast ? line.screen_cast : line?.speakers?.length ? cast.filter(id => line.speakers?.includes(id)).slice(0, 7) : line ? stageCast(line.scene.lines, line.scene.lines.findIndex(l => l.id === line.id), cast, 5) : [], line?.actor_order);
  const passage = line ? speechPassage(line.scene.lines, line.scene.lines.findIndex(l => l.id === line.id)) : null;
  const presentation = line ? scenePresentation(line.scene, line.id) : null;
  const sceneActors = actors.map(actor => {
    const costume = presentation?.wardrobe[actor.id];
    return costume ? { ...actor, stand: costume, stand_bounds: costume.bounds ?? actor.stand_bounds } : actor;
  });
  const poses = line ? stagePoses(line.scene.lines.map(l => l.id === line.id ? line : l), line.scene.lines.findIndex(l => l.id === line.id), cast, 5) : {};
  const segment = line?.performance_segments?.[editing && preview?.line.id === line.id && !playing ? preview.segment : segmentIndex];
  if (line) for (const id of focused) poses[id] = performancePose(line, segment, id, poses[id]);
  const visible = focused.flatMap(id => { const actor = sceneActors.find(a => a.id === id); return actor ? [actor] : []; });
  return <div className="overflow-hidden rounded-2xl border">
    <div className={cn("relative flex flex-col bg-linear-to-b from-muted to-background transition-opacity duration-300", transitioning && transitionEffect === "fade" && "opacity-0", compact ? "h-[min(35vh,20rem)] min-h-36" : "h-[min(60vh,36rem)] min-h-72")}>
      {presentation?.background && <img key={presentation.background.id} data-story-background={presentation.background.id} src={presentation.background.url} alt="" className="pointer-events-none absolute inset-0 size-full object-cover" />}
      <div className="z-20 flex items-center justify-between gap-3 bg-background/85 px-4 py-3 text-meta text-muted-foreground"><span>{line ? "第" + (story.scenes.indexOf(line.scene) + 1) + "幕" : ""}</span><span>{line?.scene.place ?? ""}</span></div>
      {line && <StoryStage actors={visible} allActors={sceneActors.filter(actor => cast.includes(actor.id))} line={line} poses={poses} speaking={speaking && line.kind !== "thought"} reducedMotion={reducedMotion} />}
      {!line && <div className="z-10 m-auto flex max-w-md flex-col items-center gap-4 rounded-xl bg-background/95 p-6 text-center"><p className="text-body">{story.status === "ready" ? t.end : t.waiting}</p>{story.status === "ready" && <Button onClick={() => { setIndex(0); setPlaying(true); }}>{t.replay}</Button>}</div>}
    </div>
    {!editing && <div className="relative flex min-h-40 cursor-pointer flex-col gap-2 border-t bg-background px-5 py-4 md:px-8" onClick={event => { const rect = event.currentTarget.getBoundingClientRect(); setIndex(value => event.clientX < rect.left + rect.width / 2 ? Math.max(0, value - 1) : Math.min(lines.length, value + 1)); }}>
      <div className="flex items-center justify-between gap-3"><span className="text-row-name">{line ? line.speakers?.length ? "多人" : names[line.speaker] ?? line.speaker : ""}{line?.kind === "thought" && <span className="ml-2 text-meta text-muted-foreground">{t.thought}</span>}</span><span className="text-meta text-muted-foreground">{t.line(Math.min(index + 1, lines.length), lines.length)}</span></div>
      {line && <><p className="text-japanese-line leading-7"><Ja>{passage?.ja ?? line.ja}</Ja></p><p className="text-sm leading-6 text-muted-foreground">{passage?.zh ?? line.zh}</p></>}
      <p role="status" className="min-h-4 text-meta text-muted-foreground">{notice}</p>
    </div>}
    <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2">
      <div className="flex flex-wrap items-center gap-2"><Button variant="ghost" aria-pressed={sound} disabled={!voice} onClick={() => setSound(!sound)}>{sound ? <LetterSoundIcon /> : <LetterMutedIcon />}{sound ? t.sound : t.muted}</Button><StoryVoiceControls story={story} lineId={savedLine?.id} voice={voice} onUpdated={onUpdated} onAction={()=>setPlaying(false)} /></div>
      <div className="flex gap-2"><Button variant="ghost" size="icon-lg" aria-label={t.previous} disabled={index === 0} onClick={() => setIndex(Math.max(0, index - 1))}><StoryPreviousIcon /></Button><Button variant="secondary" size="icon-lg" aria-label={playing ? t.pause : t.play} onClick={() => setPlaying(!playing)}>{playing ? <StoryPauseIcon /> : <StoryPlayIcon />}</Button><Button variant="ghost" size="icon-lg" aria-label={t.next} disabled={index >= lines.length} onClick={next}><StoryNextIcon /></Button></div>
    </div>
  </div>;
}
