import { useState } from "react";
import { Button } from "@/components/ui/button";
import { StoryOutfits } from "./StoryOutfits";
import { request, type Actor, type Story } from "./api";

export function SceneOutfits({story, actors, onUpdated}: {story:Story; actors:Actor[]; onUpdated:(s:Story)=>void}) {
  const [scene,setScene]=useState(0);
  const [character,setCharacter]=useState(story.outline?.cast[0] || "");
  const [later,setLater]=useState(false);
  const [error,setError]=useState("");
  return <details className="rounded-lg border px-4 py-3"><summary className="cursor-pointer text-sm">场景服装</summary><div className="mt-3 flex flex-col gap-3">
    <div className="flex flex-wrap gap-3"><label>幕 <select className="rounded border bg-background p-2" value={scene} onChange={e=>setScene(Number(e.target.value))}>{story.scenes.map((s,i)=><option key={i} value={i}>第{i+1}幕 · {s.place}</option>)}</select></label><label>人物 <select className="rounded border bg-background p-2" value={character} onChange={e=>setCharacter(e.target.value)}>{(story.outline?.cast || []).map(id=><option key={id} value={id}>{actors.find(a=>a.id===id)?.name || id}</option>)}</select></label></div>
    <label className="text-sm"><input type="checkbox" checked={later} onChange={e=>setLater(e.target.checked)} /> 同时应用到后续幕</label>
    <StoryOutfits actors={actors} cast={character?[character]:[]} outfits={story.scenes[scene]?.outfits || {}} onChange={(id,outfit)=>{if(!outfit)return;setError("");void request<Story>(`stories/${story.id}/scenes/${scene}/outfit`,{character:id,outfit,apply_later:later}).then(onUpdated).catch(e=>setError(e.message));}} />
    {error && <p role="alert">{error}</p>}<Button variant="ghost" onClick={()=>setError("")}>关闭提示</Button>
  </div></details>;
}
