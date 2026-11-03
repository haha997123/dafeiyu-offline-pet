# 公开版素材来源与许可

代码、角色视觉素材、录音和第三方运行库分别适用各自许可。仓库根目录的 `LICENSE` 是代码的 MIT 许可，不将下面的角色素材重新许可为 MIT。

## 代码与文字资源：MIT

应用底座来自 [QCYTSN/ds-local-pet](https://github.com/QCYTSN/ds-local-pet)，该项目进一步基于 [1190fasheqi/dafeiyu-pet](https://github.com/1190fasheqi/dafeiyu-pet)。保留上游 `LICENSE` 和 [CREDITS.md](CREDITS.md) 中的代码署名。

本仓库的 Python 源码、构建脚本、测试、本版自行编写的文档和清单，以及来源于该 MIT 项目的 `assets/dialogue/*.json`、`assets/app_categories.json`、`assets/privacy_rules.json` 文字资源适用 MIT；文件另有明确声明时按该声明执行。

## 全部角色动画、静态头像与图标：社区非商业素材

公开版随附的全部角色视觉图像均来自下列同一套社区动画，或由其帧图派生。没有混入 QCYTSN 的旧人物图片或图标。

- 动画制作者与直接来源：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。
- 固定上游提交：`3229ab287d82d7621af2ee51544a0e746c2e40fd`。
- 原始动画目录：[dsh-pet/assets/webm](https://github.com/PC2005-cloud/dsh-pet/tree/3229ab287d82d7621af2ee51544a0e746c2e40fd/dsh-pet/assets/webm)。
- 原角色“溟月”：B 站 [上善无形](https://space.bilibili.com/4456176)。
- DeepSeek 女仆鲸鱼娘设计：B 站 [ZipZipPipe](https://space.bilibili.com/4168597)。
- 许可依据：[固定提交 README 的许可章节](https://github.com/PC2005-cloud/dsh-pet/blob/3229ab287d82d7621af2ee51544a0e746c2e40fd/README.md#许可)，以及随包保留的 [assets/community/NOTICE.md](assets/community/NOTICE.md)。

直接上游声明素材“允许开源使用，禁止商用”，并将角色形象声明为 **[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans)**（署名、非商业、相同方式共享）。本版保持这些媒体条款：可依照原许可非商业使用、分享和改编；保留作者、来源和许可链接，标明改动，改编媒体继续按相同许可共享。不能将角色动画、头像或图标单独标成 MIT，也不能据代码的 MIT 许可将这些媒体用于商业用途。

公开仓库、发布页及其他公开展示渠道须保留原作者 GitHub 地址：[https://github.com/PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。

### 当前分发的视觉文件及改动

| 文件或用途 | 来源与处理 |
| --- | --- |
| `assets/community/<动作名>/*.webp` | 上游透明 VP9-alpha WebM 提取为每秒 12 帧、每段 120 帧；alpha 小于 12 的压缩噪声清零；按整段稳定联合包围盒裁切；使用所有动作共同的缩放比例，最大高度 306；保存为无损 RGBA WebP |
| 静态头像 | 直接使用 `assets/community/idle/0000.webp`，不使用旧 `idle_front` PNG |
| `sprites/icon.png`、`icon.ico` | 从上述社区待机帧居中放到透明正方形画布，缩放并转换为 PNG／多尺寸 ICO；属于同一社区图像的派生格式 |
| 仓库或发布页中新制作的角色预览 | 若包含这些社区帧，角色部分继续适用同一署名、非商业、相同方式共享条款 |

提帧、裁切、缩放及格式转换不改变底层素材许可。动作名称、固定上游路径、源文件哈希和帧路径保存在 `assets/community/manifest.json`；转换逻辑见 `tools/import_community_animation.py`。

### 公开版没有分发的旧图像

QCYTSN 原项目的 [ASSET_LICENSE.md](https://github.com/QCYTSN/ds-local-pet/blob/v0.2.0/ASSET_LICENSE.md) 将其人物图像排除在 MIT 代码许可之外，并未授予额外视觉许可。本公开版保留其代码来源署名，但不随源码、运行包或源码压缩包分发以下旧视觉资源：

- 原 `sprites/` 中的人物图、三视图及旧图标。
- 原 `assets/processed/` 中的母版、运行时兼容状态帧。
- 原 `assets/source/`、`assets/references/`、`assets/candidates/`、`assets/previews/` 及付费姿势参考图。

本公开版同名的 `sprites/icon.png` 和 `icon.ico` 已重新从上面的社区帧制作，不能与已剔除的旧文件混淆。

## 社区预录声音：保留上游 MIT 声明

- 原作者与来源：[bauerelizabeth07139/dsh-pet-dafeiyu](https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu)。
- 固定提交：`fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a`。
- 原录音：[assets/voice](https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu/tree/fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a/assets/voice)。
- 许可：[该提交的 MIT LICENSE](https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu/blob/fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a/LICENSE)；该提交未另列音频许可例外。

公开版保留原 49 个 MP3、台词与对应来源，默认只启用其中 22 条中性友好片段。播放用 WAV 是原录音的格式转换，并以 ffmpeg loudnorm（I=-18、TP=-2、LRA=7）统一响度；原 MP3 未改动。上游声明录音经 SenseAudio 预先生成。本程序只在本地播放文件，不调用语音 API，不把通用 TTS 或新合成音色冒充为这套社区原声。

完整上游版权与 MIT 文本见 [companion_voicepack_notice.md](companion_voicepack_notice.md)，文件映射见 `assets/voicepack/manifest.json`。原录音及派生 WAV 的来源和处理记录应随复制件保留。

## 用户自行导入的语音

导入文件保存在用户本机数据目录，不属于本仓库的公开素材，不随发布包上传。导入和播放不会改变原音频的权利或许可。

## 运行库与名称

Python、Qt/PySide、Pillow、psutil 及构建组件分别保留各自许可，详见 [THIRD_PARTY_NOTICES_DIARY.md](THIRD_PARTY_NOTICES_DIARY.md) 和发布包 `licenses/`。

本项目是非官方社区衍生作品，与 DeepSeek 无隶属或认可关系；相关名称和标识仍归各自权利人所有。
