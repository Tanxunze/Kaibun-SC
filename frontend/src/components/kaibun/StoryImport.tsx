import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { request, type Story } from "./api";

export function StoryImport({expanded, cast, onImported}: {expanded: boolean; cast:string[]; onImported:(story:Story)=>void}) {
  const [text,setText] = useState("");
  const [filename,setFilename] = useState("粘贴剧本.txt");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [fileContent,setFileContent] = useState<string | null>(null);
  async function load(file?: File) {
    if (!file) return;
    setError("");
    if (file.size > 6 * 1024 * 1024) {setError("请选择6MB以内的剧本文件。");return;}
    try {
      setFilename(file.name);
      if (file.name.toLowerCase().match(/\.(docx|pdf)$/)) {
        const bytes = new Uint8Array(await file.arrayBuffer());
        setFileContent(Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("")); setText("已选择文件，点击导入后检查解析结果。");
      } else {
        const buffer = await file.arrayBuffer(); let content = new TextDecoder("utf-8",{fatal:false}).decode(buffer); if (content.includes("�")) content = new TextDecoder("gb18030").decode(buffer); setText(content);setFileContent(null);
      }
    } catch {setError("文件读取失败，请重新选择。");}
  }
  return <details open={expanded} className="rounded-lg border p-4"><summary>导入现有剧本</summary><div className="mt-3 flex flex-col gap-3"><p className="text-sm text-muted-foreground">支持 TXT、Markdown、DOCX、含文字的 PDF，也可以直接粘贴。建议每行写“人物：台词”，用“第1幕 地点”分场；双语台词可写“人物：日文 || 中文”。先在本地解析并检查，之后点击修改按钮才会发送给模型。</p><input type="file" aria-label="选择剧本文件" accept=".txt,.md,.markdown,.docx,.pdf" onChange={e => void load(e.target.files?.[0])} /><Textarea aria-label="粘贴剧本" value={text} disabled={!!fileContent} onChange={e => {setText(e.target.value);setFilename("粘贴剧本.txt");}} />{fileContent && <Button variant="ghost" onClick={()=>{setFileContent(null);setText("");}}>改为粘贴文本</Button>}{error && <p role="alert">{error}</p>}<Button disabled={busy || !text.trim()} onClick={async()=>{setBusy(true);setError("");try{onImported(await request<Story>("scripts/parse",{filename,content:fileContent ?? text,cast}));}catch(e){setError(e instanceof Error ? e.message : "导入失败");}finally{setBusy(false);}}}>导入并检查解析结果</Button></div></details>;
}
