export default function About() {
  return <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-12">
    <a href="/" className="underline">返回怪文书</a>
    <h1 className="text-3xl font-semibold">怪文书 · Kaibun</h1>
    <p>输入想法，创作分幕的日中双语对白剧。可先审阅大纲、修改台词、续写故事，再播放或导出视频。未配置配音或素材时可使用字幕、姓名和中性背景。</p>
    <p>完整的安装方式、模型配置、数据位置及可选素材说明见项目根目录 README.md。个人故事和配音保存在本机配置的数据目录中。</p>
    <p>本项目基于 <a href="https://github.com/Sallyn0225/eidolon-sc" className="underline">Eidolon-SC</a> 修改，代码采用 AGPL-3.0-or-later。第三方组件适用各自许可证。</p>
    <p>这是《偶像大师 闪耀色彩》的非官方粉丝作品，与 Bandai Namco Entertainment 及相关权利人无关联。角色、原作设定和素材属于各自权利人；代码开源不代表获得素材或声音授权。Spine 运行库和原作立绘、背景、音色均不随本包分发。</p>
    <p>提示词和人物资料会发送给你配置的模型服务，图片标注及配音会发送对应图片或文本。请按服务商政策使用；这些服务可能计费。</p>
  </main>;
}
