# 社区预录大肥鱼语音包来源

本项目复用了 bauerelizabeth07139/dsh-pet-dafeiyu 的 assets/voice/ 中 49 个 MP3 文件，保持音频原样。固定上游提交为 fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a。音频文件总计 2362362 字节。

- 仓库：https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu
- 固定资源：https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu/tree/fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a/assets/voice
- 台词与原始分类：https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu/blob/fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a/lib/client.js
- 原始声明：https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu/blob/fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a/README.md#credits-and-licence
- 许可：https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu/blob/fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a/LICENSE

上游 README 声明：这些语音、音效和音乐是作者通过 SenseAudio API 为该插件预先生成的；项目按 MIT 许可发布。该仓库在此提交中未另列音频的许可例外。本项目只复用现成预录 MP3，不做声音克隆，不在运行时连接 SenseAudio、Fish Audio 或其他语音 API，也不把这些片段冒充成可朗读任意文本的离线 TTS。这里没有复用上游角色图片、背景音乐或双人混音小剧场。

assets/voicepack/manifest.json 的 49 条台词由上游 lib/client.js 的 LINES JSON 字面量解析而来；original_groups 原样保存其 GROUPS 分类。未在 GROUPS 中的独立动作片段以 feed/think 等事件名归类。文件名未改变；每条包含字节数和 SHA-256，可检查下载完整性；下载时也逐个验证了上游 Git blob SHA-1。

默认随机池只启用 22 条中性、友好片段。含“爸爸”、固定昵称、较强亲密表达、负面语气或只适合原项目小剧场的片段仍保留，但 enabled_default=false，不能进入默认随机池。全部默认策略都写入 manifest，使用者可明确选择启用其他片段。字幕必须使用对应片段的原文；动态日记、主人名字等自定义文字不应套用不匹配的录音。

## 上游 MIT License（完整保留）

MIT License

Copyright (c) 2026 bauerelizabeth07139

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

