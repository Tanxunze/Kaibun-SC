import { useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { Actor } from "./api";

export function StoryCastOrder({ actors, order, selected, onOrder, onSelected }: {
  actors: Actor[]; order: string[]; selected: string[]; onOrder: (ids: string[]) => void; onSelected: (ids: string[]) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const previous = useRef(new Map<string, DOMRect>());
  const gesture = useRef<{id: string; x: number; y: number; active: boolean; original: string[]} | null>(null);
  const [drag, setDrag] = useState<{id: string; x: number; y: number} | null>(null);
  const ids = [...order.filter(id => actors.some(a => a.id === id)), ...actors.map(a => a.id).filter(id => !order.includes(id))];
  useLayoutEffect(() => {
    const next = new Map<string, DOMRect>();
    root.current?.querySelectorAll<HTMLElement>("[data-cast-id]").forEach(node => {
      const id = node.dataset.castId!; const box = node.getBoundingClientRect(); const old = previous.current.get(id);
      if (old && (old.x !== box.x || old.y !== box.y)) node.animate([{transform:`translate(${old.x-box.x}px,${old.y-box.y}px)`},{transform:"translate(0,0)"}], {duration:160,easing:"ease-out"});
      next.set(id, box);
    });
    previous.current = next;
  }, [ids.join("|")]);
  function finish(cancel = false) {
    const state = gesture.current;
    if (cancel && state?.active) onOrder(state.original);
    gesture.current = null; setDrag(null);
  }
  return <div ref={root} className="flex flex-wrap gap-2 select-none" onDragStart={e => e.preventDefault()} onContextMenu={e => {if(gesture.current?.active)e.preventDefault();}}>
    {ids.map(id => <div key={id} data-cast-id={id} className={cn("flex touch-none select-none items-center gap-2 rounded-lg border bg-background px-3 py-2 text-sm", drag?.id===id ? "opacity-30" : "cursor-grab active:cursor-grabbing")}
      onPointerDown={e => { if(e.button!==0 || (e.target as HTMLElement).closest("input"))return; e.preventDefault(); e.currentTarget.setPointerCapture(e.pointerId); gesture.current={id,x:e.clientX,y:e.clientY,active:false,original:ids}; }}
      onPointerMove={e => {
        const state=gesture.current;if(!state || state.id!==id)return;
        if(!state.active && Math.hypot(e.clientX-state.x,e.clientY-state.y)<5)return;
        state.active=true;setDrag({id,x:e.clientX,y:e.clientY});
        const nodes=Array.from(root.current!.querySelectorAll<HTMLElement>("[data-cast-id]"));
        const target=nodes.filter(n=>n.dataset.castId!==id).sort((a,b)=>{const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return Math.hypot(e.clientX-(x.left+x.width/2),e.clientY-(x.top+x.height/2))-Math.hypot(e.clientX-(y.left+y.width/2),e.clientY-(y.top+y.height/2));})[0];
        if(!target)return;const box=target.getBoundingClientRect();const remaining=ids.filter(v=>v!==id);let at=remaining.indexOf(target.dataset.castId!);if(e.clientX>box.left+box.width/2)at++;remaining.splice(at,0,id);if(remaining.join('|')!==ids.join('|'))onOrder(remaining);
      }} onPointerUp={() => finish()} onPointerCancel={() => finish(true)}>
      <input aria-label={actors.find(a=>a.id===id)?.name} type="checkbox" checked={selected.includes(id)} onChange={e=>onSelected(e.target.checked?[...selected,id]:selected.filter(v=>v!==id))}/>
      <span className="pointer-events-none">{actors.find(a=>a.id===id)?.name}</span>
    </div>)}
    {drag && <div aria-hidden className="pointer-events-none fixed z-50 rounded-lg border bg-background px-3 py-2 text-sm shadow-lg" style={{left:drag.x+12,top:drag.y-18,transform:"rotate(2deg)"}}>{actors.find(a=>a.id===drag.id)?.name}</div>}
  </div>;
}
