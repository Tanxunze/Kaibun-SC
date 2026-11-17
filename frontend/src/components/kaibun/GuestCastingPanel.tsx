import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { request, type Actor, type GuestCasting, type Story, type Wardrobe } from "./api";

type Props = { story: Story; actors: Actor[]; onUpdated: (story: Story) => void };
const empty: GuestCasting = { voice_id: "", outfit_owner: "", outfit: "", portrait: "" };

export function GuestCastingPanel(props: Props) {
  const guests = props.story.outline?.guests ?? [];
  const [confirmation, setConfirmation] = useState("");
  const [selected, setSelected] = useState("");
  const guest = guests.find(g => g.id === selected) ?? guests[0];
  if (!guest) return null;
  const saved = props.story.guest_cast?.[guest.id] ?? empty;
  return <details className="rounded-lg border p-4">
    <summary className="cursor-pointer">配角音色与立绘</summary>
    <div className="mt-3 grid gap-3">
      <label>配角 <select aria-label="配角" value={guest.id} onChange={e => { setConfirmation(""); setSelected(e.target.value); }}>
        {guests.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
      </select></label>
      <GuestEditor key={JSON.stringify([props.story.id, guest.id, saved])} {...props} guestId={guest.id} saved={saved} onUpdated={updated => { props.onUpdated(updated); setConfirmation(guest.name + "的设置已保存"); }} />
      {confirmation && <p role="status" className="text-sm">{confirmation}</p>}
    </div>
  </details>;
}

function readImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1]);
    reader.onerror = () => reject(new Error("无法读取图片"));
    reader.readAsDataURL(file);
  });
}

function GuestEditor({ story, actors, guestId, saved, onUpdated }: Props & { guestId: string; saved: GuestCasting }) {
  const [voice, setVoice] = useState(saved.voice_id);
  const [custom, setCustom] = useState(!!voice && !actors.some(a => a.voice_id === voice));
  const [mode, setMode] = useState(saved.portrait ? "image" : saved.outfit ? "outfit" : "none");
  const [owner, setOwner] = useState(saved.outfit_owner);
  const [outfit, setOutfit] = useState(saved.outfit);
  const [choices, setChoices] = useState<Wardrobe[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!file) { setPreview(""); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => {
    let active = true;
    setChoices([]);
    if (mode === "outfit" && owner) {
      request<Wardrobe[]>(`characters/${owner}/outfits`).then(rows => {
        if (active) setChoices(rows);
      }).catch(e => { if (active) setError(e.message); });
    }
    return () => { active = false; };
  }, [owner, mode]);

  async function save() {
    setBusy(true); setError("");
    try {
      if (file && mode === "image" && file.size > 5 * 1024 * 1024) throw new Error("请选择 5 MB 以内的图片");
      const updated = await request<Story>(`stories/${story.id}/guests/${guestId}`, {
        voice_id: voice.trim(), outfit_owner: mode === "outfit" ? owner : "", outfit: mode === "outfit" ? outfit : "",
        portrait: mode === "image" && !file ? saved.portrait : "",
        image_base64: mode === "image" && file ? await readImage(file) : "",
        base_fingerprint: story.base_fingerprint,
      });
      onUpdated(updated);
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }
  const picture = preview || (saved.portrait ? `/api/kaibun/guest-portraits/${saved.portrait}.png` : "");
  const incomplete = (custom && !voice.trim()) || (mode === "image" && !picture) || (mode === "outfit" && !outfit);
  return <fieldset disabled={busy} className="grid gap-3">
    <label>音色 <select aria-label="音色" value={custom ? "custom" : voice} onChange={e => {
      setCustom(e.target.value === "custom"); setVoice(e.target.value === "custom" ? "" : e.target.value);
    }}>
      <option value="">仅字幕</option>
      {actors.filter(a => a.voice_id).map(a => <option key={a.id} value={a.voice_id}>{a.name}</option>)}
      <option value="custom">自定义 Fish 音色</option>
    </select></label>
    {custom && <label>Fish 音色 ID <input value={voice} maxLength={150} onChange={e => setVoice(e.target.value)} /></label>}
    <label>立绘 <select aria-label="立绘" value={mode} onChange={e => setMode(e.target.value)}>
      <option value="none">无立绘</option><option value="outfit">本地角色衣装</option><option value="image">上传静态图片</option>
    </select></label>
    {mode === "outfit" && <>
      <label>衣装所属角色 <select aria-label="衣装所属角色" value={owner} onChange={e => { setOwner(e.target.value); setOutfit(""); }}>
        <option value="">选择角色</option>{actors.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select></label>
      {owner && <label>衣装 <select aria-label="衣装" value={outfit} onChange={e => setOutfit(e.target.value)}>
        <option value="">选择已下载衣装</option>{choices.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>}
    </>}
    {mode === "image" && <><label>静态立绘（PNG、JPEG、WebP） <input type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
      {picture && <img src={picture} alt="静态立绘预览" className="h-28 w-fit object-contain" />}</>}
    <div><Button size="sm" disabled={incomplete || busy} onClick={save}>保存配角设置</Button></div>
    {error && <p role="alert">{error}</p>}
  </fieldset>;
}
