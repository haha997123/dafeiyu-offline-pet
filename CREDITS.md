# 来源与致谢

本公开版将独立桌宠、离线相处记录、本地语音包导入和社区预录声音组合为 Windows 应用。代码和媒体分别保留其来源与许可，详见 [ASSET_LICENSE.md](ASSET_LICENSE.md)。

## 应用底座与 MIT 代码

- 直接代码底座：[QCYTSN/ds-local-pet](https://github.com/QCYTSN/ds-local-pet)，基于其公开的模块化桌宠、动作、互动和本地台词代码进行改版。

- 上游仓库：https://github.com/1190fasheqi/dafeiyu-pet
- 导入基线提交：2822f8f215e34f3177c00b1fb6c0d073eefdea31
- 上游许可证：MIT

上游的 LICENSE 已原样保留在本仓库根目录。

## 上游底座提供的实现

以下实现来自 QCYTSN 的模块化底座，保留其 MIT 许可与署名，不作为本版新增部分：

- `app/`、`animation/`、`pet/`、`awareness/`、`behavior/`、`dialogue/`、`settings/` 的模块化架构
- 本地环境感知与隐私过滤
- 本地台词与人格调度（`assets/dialogue/*.json` 文本内容）
- 素材管线与校验工具（`tools/`）、单元测试（`tests/`）、发布打包脚本与 CI 配置

## 本版增加与调整

本版增加或调整了主人档案、相处事件与长期存档、备份、成长、互动小卡、设置行为、社区连续动画接入、预录语音播放和本地 ZIP／目录语音包导入。新增 Python 代码同样按 MIT 许可提供。来源于上游的本地台词、分类与隐私配置文字资源保留其 MIT 来源。

## 全部角色视觉：PC2005-cloud 社区动画

- 动画来源：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)。
- 固定提交：`3229ab287d82d7621af2ee51544a0e746c2e40fd`。
- 原角色“溟月”：B 站 [上善无形](https://space.bilibili.com/4456176)。
- DeepSeek 女仆鲸鱼娘设计：B 站 [ZipZipPipe](https://space.bilibili.com/4168597)。
- 媒体条款：直接上游允许开源使用、禁止商用，并声明角色适用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.zh-hans)。

公开版的全部角色动画均从这一固定来源提帧、清理透明噪声、稳定裁切、统一缩放并转成 12fps 无损 WebP。静态头像直接使用社区待机帧；PNG／ICO 图标由同一帧居中放入透明正方形画布后转换产生。这些图像继续保留原署名、非商业及相同方式共享要求，不能按 MIT 重新许可。

上游许可原文、作者链接和转换记录分别见 [assets/community/NOTICE.md](assets/community/NOTICE.md)、`assets/community/manifest.json` 和 [ASSET_LICENSE.md](ASSET_LICENSE.md)。

QCYTSN 项目的旧人物图像、运行时状态 PNG、旧图标、三视图、母版、付费参考和候选图没有随本公开版分发；其代码署名仍保留。当前同名 `sprites/icon.png`、`icon.ico` 是上述社区待机帧的派生文件。

[MerZlin/dsh-pet-indesktop](https://github.com/MerZlin/dsh-pet-indesktop) 的资源整理与性能经验用于研究参考；本版实际采用的连续动画直接取自 PC2005-cloud，未复制 MerZlin 的程序代码或独立素材。

## 社区预录声音

49 条原录音和台词来自 [bauerelizabeth07139/dsh-pet-dafeiyu](https://github.com/bauerelizabeth07139/dsh-pet-dafeiyu)，固定提交 `fc1ad4c0fa29ee29338a469c74ebe7776bf3d66a`。上游采用 MIT，并声明这些声音由 SenseAudio 为该插件预先生成；该提交未另列音频许可例外。

本版保留原 MP3，默认只播放其中 22 条中性友好片段；另提供相同录音的 WAV 格式与响度统一副本。完整原版权和许可文本见 [companion_voicepack_notice.md](companion_voicepack_notice.md)。本版不声称这套录音代表全部 B 站“大肥鱼”作者的声音，也不把其他 TTS 音色归为该作者作品。

## 运行库

感谢 Python、Qt/PySide、Pillow、psutil、PyInstaller 及其依赖的维护者。完整依赖与许可见 [THIRD_PARTY_NOTICES_DIARY.md](THIRD_PARTY_NOTICES_DIARY.md) 和发布包的 `licenses/`。

## 新增的本地提示音

`assets/chimes/reminder.wav` 为本项目用正弦波合成的原创短提示音，随代码按 MIT 许可提供。
