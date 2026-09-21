# 实验过程完整记录：上下文腐烂实测

> 本文是《实测上下文腐烂：字面规则19万token全对，"人话规则"5万就开始丢》一文的实验档案。所有数据来自2026-09-21的真实API调用，原始JSON全部保留在`results/`目录。

## 一、实验环境与材料

| 项 | 值 |
|----|-----|
| 时间 | 2026-09-21 15:40 - 16:35 |
| 机器 | macOS（本地终端直连API） |
| 模型 | Agnes 3.0 Flash（OpenAI兼容聚合API，temperature=0） |
| 干草堆 | 作者3个真实项目的77份markdown文档（技术架构/API规范/表结构/会议纪要），共约21.1万token |
| 工具 | context_rot_probe.py（单文件，零第三方依赖） |
| 总调用 | 38次（2次SSL网络错误作废重跑，36次有效） |

**干草堆样例**（真实文档截取）：

```
docs/doc000.txt  ← 3个真实项目里捞的架构文档，每份截取后拼装
docs/doc001.txt
...共77份
```

## 二、操作步骤（4步，全部可复现）

### 第1步：准备干草堆

```bash
# 从真实项目收集markdown，统一转成txt
find ~/work/code/gome-jiagou ~/work/code/mcpgateway ~/work/code/aicode \
  -name "*.md" -size +2k | ... # 过滤后77份，按token估算凑到21万
```

### 第2步：写两根"针"（信息完全相同的两种措辞）

**显式针** `needle.txt`：

> 关键部署事实（仅此一份）：本项目的数据库结构变更必须使用自定义迁移脚本 bin/migrate_custom.sh 执行，并且必须在服务重启之前完成迁移，顺序绝对不能颠倒。禁止直接使用 prisma migrate deploy 裸跑生产库。

**隐式针** `needle_implicit.txt`（同样的事实，会议纪要体）：

> 上周三的架构评审会上，后端负责人明确拍板：以后数据库任何表结构变更都走 bin/migrate_custom.sh 这个内部工具，上线流程里这一步必须排在应用重启动作的前面，谁也不能调换……

### 第3步：跑探测（真实命令）

```bash
# 显式针，5万token档（19份文档），3个位置各3次
python3 context_rot_probe.py \
  --haystack_dir docs --needle_file needle.txt \
  --question "数据库结构变更应该用什么脚本执行？在服务重启之前还是之后？" \
  --must_include "migrate_custom.sh,重启之前" \
  --forbidden "先重启,重启之后" \
  --positions 0.1,0.5,0.9 --max_docs 19 --runs 3 \
  --base_url https://apihub.agnes-ai.com/v1 \
  --api_key sk-*** --model agnes-3.0-flash --out run_19.json

# 10.6万档：--max_docs 38 → run_38.json
# 19.2万档：--max_docs 68 → run_68.json
# 隐式针5万档：--needle_file needle_implicit.txt → run_implicit_19.json
```

### 第4步：判分汇总

脚本内置规则判分（弃权声明优先 → 关键词匹配 → 禁止词否定语境检查），汇总进 `results/final_results.json`。

## 三、终端实录（2026-09-21现场复跑存档）

**用初版判分脚本跑**（裸关键词匹配），第10%位置的PASS被误判成FAIL——现场复现了"坑1"：

```
[10%|run1] 3,089tok -> FAIL ['重启之前'] []
[50%|run1] 3,089tok -> PASS  []
[90%|run1] 3,089tok -> PASS  []
汇总：2/3 通过
```

被误判的原始回答（模型其实答对了，只是用了markdown加粗）：

> 根据文档内容：数据库结构变更应该使用自定义迁移脚本 **`bin/migrate_custom.sh`** 执行。必须在服务重启**之前**完成迁移。

**换修复版判分后重跑**：

```
[10%|run1] 3,089tok -> PASS  []
[50%|run1] 3,089tok -> PASS  []
[90%|run1] 3,089tok -> PASS  []
汇总：3/3 通过
```

## 四、结果图表

### 图1：存活率对比（核心图）

![存活率对比](./chart-pass-rate.png)

蓝色（显式针）：三个token档位、三个位置全部100%。
橙色（隐式针）：开头100%尚可，中间67%，结尾只剩33%。

### 图2：隐式针失败的3次都是什么形态

![失败模式](./chart-fail-modes.png)

2次是"自信弃权"——模型笃定地说"文档里没有这条规定"，还列举了一堆文档主题证明自己读过；1次是漏掉顺序约束。

## 五、原始回答摘录（从results/*.json取）

**显式针·19.2万·中间位置·PASS**：

> "数据库结构变更应该使用自定义迁移脚本`bin/migrate_custom.sh`执行。必须在服务重启之前完成迁移，顺序绝对不能颠倒。禁止直接使用`prisma migrate deploy`裸跑生产库。"

**隐式针·5万·结尾位置·FAIL（弃权）**：

> "根据文档内容，**没有提到**'数据库结构变更应该用什么脚本执行'的具体规定。提供的文档主要涉及以下内容：1.Linear API使用指南……2.locate-path库……"

## 六、诚实的局限性声明

- 每格3次是小样本，只能看趋势，不能当论文引用
- 单模型（Agnes 3.0 Flash），结论不能外推到所有模型
- token数是估算值（中文1字≈1token），非tokenizer精确计数
- 判分是规则匹配，不是人工逐条复核（弃权/关键词/否定语境三层逻辑已开源可审查）

全部原始数据：[github.com/2hei/context-rot-probe](https://github.com/2hei/context-rot-probe) → `results/` 目录
