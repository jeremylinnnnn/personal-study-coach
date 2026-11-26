# 个人自学教练

一个面向大学课程的 Agent Skill。它优先使用你工作区里的教材、课件、作业和试卷，帮你弄懂知识点、动手验证，并把学过的内容整理成可以回看的资料。

## 能做什么

| 模式 | 功能 |
| --- | --- |
| 平时学习 | 概念或题目讲解、课件精讲与自学讲义、知识清单与速查表、练习与自测、批改与错题整理、小实验或代码验证。可以回复编号选择。 |
| 备考 | 可单选或组合考前突击、知识串讲、考点研判、刷题与模拟、HTML 知识卡和跨科复习总表。 |

- **课件精讲与自学讲义**默认按章节和页码嵌入课件原页，在对应位置用教材补充原理、推导和例题。也可选择只嵌入关键图表，或只保留页码索引。
- **知识积累**按科目计数，每问满 5 个不同的问题自动整理一次。可以选 3、5、10 或自定义次数，同一知识点的跟进澄清归入原问题。
- **考前突击与知识串讲**适合部分内容还没学或学得零散的情况。按现有基础补先修知识，讲清推导、适用条件和典型题，再做一道变式自测。
- **考点研判**根据考试范围、练习和历年卷列出优先学什么、常怎么考。结论标明出处，并区分明确考纲和样本推断。
- **HTML 知识卡**一次备好整组具体知识点。按回忆难度选「重来、困难、良好、简单」，按钮上方会显示预计复习间隔，无需估算掌握百分比。带作答和批改的练习可通过「练习与自测」单独做。
- **全局复习总表**会记录在已安装的 `SKILL.md` 中。新增科目、修改考试日期或者换会话时，沿用这张表。

## 安装

先装好 Git 和你使用的 Agent。以下命令把 Skill 安装到当前用户目录，安装后可在不同学习工作区使用。

| 工具 | macOS 安装位置 | Windows 安装位置 |
| --- | --- | --- |
| Codex | `~/.agents/skills/personal-study-coach/` | `C:\Users\<用户名>\.agents\skills\personal-study-coach\` |
| DeepSeek Harness（DSH） | `~/.dsh/skills/personal-study-coach/` | `C:\Users\<用户名>\.dsh\skills\personal-study-coach\` |
| Claude Code | `~/.claude/skills/personal-study-coach/` | `C:\Users\<用户名>\.claude\skills\personal-study-coach\` |
| WorkBuddy（国内版） | `~/.workbuddy/skills/personal-study-coach/` | `C:\Users\<用户名>\.workbuddy\skills\personal-study-coach\` |
| WorkBuddy AI（国际版） | `~/.workbuddy-ai/skills/personal-study-coach/` | `C:\Users\<用户名>\.workbuddy-ai\skills\personal-study-coach\` |
| Qoder IDE | `~/.qoder/skills/personal-study-coach/` | `C:\Users\<用户名>\.qoder\skills\personal-study-coach\` |
| QoderWork | `~/.qoderwork/skills/personal-study-coach/` | `C:\Users\<用户名>\.qoderwork\skills\personal-study-coach\` |

表格是用户级目录示例。DSH 的专用目录由 `DSH_HOME` 决定，共用目录由 `DSH_AGENTS_HOME` 决定。未设置时，DSH 也会读取 `~/.agents/skills`，可以和 Codex 共用一份。相关文档见 [Codex](https://learn.chatgpt.com/docs/build-skills)、[DSH](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md)、[Claude Code](https://code.claude.com/docs/en/skills)、[Qoder IDE](https://docs.qoder.com/zh/extensions/skills)和 [QoderWork](https://docs.qoder.com/qoderwork/skills)。

WorkBuddy 的用户目录随版本而异。也可以在客户端打开「技能 → 添加技能 → 上传技能」，导入包含脚本和资源的完整技能包。参见 [WorkBuddy 国内版目录说明](https://developer.cloud.tencent.com/techpedia/2610/20530)和 [WorkBuddy AI 导入指南](https://www.tencentcloud.com/zh/document/product/1316/84503)。

### macOS（终端）

以下以 Codex 为例。用表中对应的 `skills` 目录替换第一行的路径即可安装到其他工具，例如 Claude Code 用 `$HOME/.claude/skills`。安装给 DSH 时，可以把前两行的注释互换。

```bash
install_root="$HOME/.agents/skills"
# install_root="${DSH_HOME:-$HOME/.dsh}/skills"
mkdir -p "$install_root"
git clone https://github.com/jeremylinnnnn/personal-study-coach.git "$install_root/personal-study-coach"
```

### Windows（PowerShell）

以下以 Codex 为例。使用其他工具时，修改 `Join-Path` 后的相对路径，例如 Qoder IDE 用 `.qoder\skills`。安装给 DSH 时，注释第一行并去掉接下来两行开头的 `#`。

```powershell
$InstallRoot = Join-Path $HOME '.agents\skills'
# $DshHome = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $HOME '.dsh' }
# $InstallRoot = Join-Path $DshHome 'skills'
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
git clone https://github.com/jeremylinnnnn/personal-study-coach.git (Join-Path $InstallRoot 'personal-study-coach')
```

安装完成后，`personal-study-coach` 目录下应直接看到 `SKILL.md`、`assets/`、`references/`、`scripts/`。

**更新已有安装。** Git 克隆安装且没有本地改动时，在安装目录运行 `git pull --ff-only`。如果已经在 `SKILL.md` 中登记了复习总表路径，先保留那一行。可以把新版克隆到另一目录，合并或替换 Skill 文件后，把登记行写回安装目录中的 `SKILL.md`。工作区里的复习总表、各科卡库和学习笔记继续使用原来的文件。

## 第一次使用

1. 在 Agent 里打开你的学习工作区。尽可能把教材、课件、作业、测试题和历年试卷放进去，先放手头已有的材料即可。
2. 在 Codex 里输入 `$personal-study-coach`，在 DSH 或 Claude Code 里输入 `/personal-study-coach`，也可以从工具的技能列表中选择。Skill 会用短菜单介绍能做什么。
3. 选一个成果开始。例如「选 2，电磁学课件当前章节，按顺序嵌入原页」。备考可以说「我还有两小时，前半部分没学。先看工作区里的练习和历年卷，再从最重要的知识点开始讲」。

讲解会优先采用课程的术语和答题习惯。逐页讲义、知识积累和复习资料保存在学习工作区。旧版设置在工作区根目录 `.study-coach.json` 中的 `accumulate_every` 仍可读取。

HTML 卡片与全局排表脚本需要 Python 3.9 或更新版本。macOS 通常用 `python3`，Windows 可用 `py -3` 或 `python`。运行命令、时间设置和保存方式见 [备考模式说明](references/exam-mode.md)。

## 许可

本仓库采用 [MIT 许可](LICENSE)。FSRS 排期实现使用了 [py-fsrs 6.3.3](https://github.com/open-spaced-repetition/py-fsrs/tree/v6.3.3) 的公式，版权与许可见 [第三方声明](THIRD_PARTY_NOTICES.md)。
