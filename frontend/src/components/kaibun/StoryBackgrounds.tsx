import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { request, type Background, type Story } from "./api";

export function StoryBackgrounds({ story, onUpdated }: { story: Story; onUpdated: (story: Story) => void }) {
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<Background[]>([]);
  const [scene, setScene] = useState(0);
  const [filter, setFilter] = useState("");
  const [limit, setLimit] = useState(12);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [customFile, setCustomFile] = useState<File | null>(null);
  const [customName, setCustomName] = useState("");
  const [customTags, setCustomTags] = useState("");
  const [customTime, setCustomTime] = useState("unknown");
  useEffect(() => {
    if (!open) return;
    let active = true;
    request<Background[]>("backgrounds").then(rows => { if (active) setCatalog(rows); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [open]);
  const filtered = catalog.filter(item => (item.id + item.label + item.description + item.tags.join(" ")).includes(filter));
  async function choose(background: string | null) {
    setBusy(true); setError("");
    try { onUpdated(await request<Story>(`stories/${story.id}/scenes/${scene}/background`, { background })); }
    catch (error) { setError(error instanceof Error ? error.message : "背景暂时未能修改"); }
    finally { setBusy(false); }
  }
  async function upload() {
    if (!customFile || !customName.trim()) return;
    setBusy(true); setError("");
    try {
      if (customFile.size > 10 * 1024 * 1024) throw new Error("请选择10MB以内的图片");
      const image = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(new Error("图片读取失败"));
        reader.readAsDataURL(customFile);
      });
      const item = await request<Background>("backgrounds/import", {image, label:customName.trim(), tags:customTags.split(/[,，、\s]+/).filter(Boolean), time_of_day:customTime});
      setCatalog(await request<Background[]>("backgrounds"));
      setFilter(item.id); setLimit(12);
    } catch(e) { setError(e instanceof Error ? e.message : "图片添加失败"); }
    finally { setBusy(false); }
  }
  return <details className="rounded-lg border px-4 py-3" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer text-sm">场景背景</summary>
    {open && <div className="mt-3 flex flex-col gap-3">
      <details className="rounded-lg border p-3"><summary>添加自己的背景</summary><div className="mt-3 flex flex-col gap-3"><p className="text-sm text-muted-foreground">选择图片并填写名称、地点标签，加入后点击下方缩略图应用到当前幕。标签也可供新故事自动选景使用。</p><input aria-label="自定义背景图片" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={e=>{const file=e.target.files?.[0] || null;setCustomFile(file);if(file)setCustomName(file.name.replace(/\.[^.]+$/,""));}} /><Input aria-label="背景名称" placeholder="例如：病房 · 白天" value={customName} onChange={e=>setCustomName(e.target.value)} /><Input aria-label="背景标签" placeholder="例如：医院，病房，住院，室内" value={customTags} onChange={e=>setCustomTags(e.target.value)} /><label>时间 <select value={customTime} onChange={e=>setCustomTime(e.target.value)}><option value="unknown">不限</option><option value="day">白天</option><option value="dusk">黄昏</option><option value="night">夜晚</option></select></label><Button variant="outline" disabled={busy || !customFile || !customName.trim()} onClick={()=>void upload()}>加入背景素材库</Button></div></details>
      <label className="flex items-center gap-2 text-sm">场景<select value={scene} onChange={event => setScene(Number(event.target.value))} className="min-w-0 rounded-md border bg-background p-2">{story.scenes.map((item, index) => <option key={index} value={index}>第{index + 1}幕 · {item.place}</option>)}</select></label>
      <label>转场 <select value={story.scenes[scene]?.transition || "cut"} onChange={e => {void request<Story>(`stories/${story.id}/scenes/${scene}/transition`, {transition:e.target.value,duration:story.scenes[scene]?.transition_length || "short"}).then(onUpdated).catch(e=>setError(e.message));}}><option value="cut">直接切换</option><option value="pause">短暂停顿</option><option value="fade">淡入</option></select></label>
      <label>转场时长 <select value={story.scenes[scene]?.transition_length || "short"} onChange={e => {void request<Story>(`stories/${story.id}/scenes/${scene}/transition`, {transition:story.scenes[scene]?.transition || "cut",duration:e.target.value}).then(onUpdated).catch(e=>setError(e.message));}}><option value="short">短</option><option value="medium">中</option><option value="long">长</option></select></label>
      <Input aria-label="查找背景" placeholder="查找地点、昼夜或编号" value={filter} onChange={event => { setFilter(event.target.value); setLimit(12); }} />
      <Button variant="outline" disabled={busy} onClick={() => { void choose(null); }}>中性背景</Button>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{filtered.slice(0, limit).map(item => <button type="button" key={item.id} disabled={busy} aria-pressed={story.scenes[scene]?.background_asset?.id === item.id} onClick={() => { void choose(item.id); }} className={cn("flex flex-col gap-2 rounded-lg border p-2 text-left", story.scenes[scene]?.background_asset?.id === item.id && "bg-muted")}><img src={item.thumbnail} alt="" loading="lazy" className="aspect-video w-full rounded object-cover" /><span className="text-subtitle">{item.label} · {item.id}</span></button>)}</div>
      {filtered.length > limit && <Button variant="ghost" onClick={() => setLimit(limit + 12)}>显示更多</Button>}
      {error && <p role="alert" className="text-sm text-muted-foreground">{error}</p>}
    </div>}
  </details>;
}
