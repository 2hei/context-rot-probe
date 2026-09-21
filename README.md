# context-rot-probe

上下文腐烂（Context Rot）自测工具——用你自己的项目文档，测一测模型的长上下文到底什么时候开始"变笨"。

灵感来自 Chroma 2025 年 7 月的技术报告《Context Rot: How Increasing Input Tokens Impacts LLM Performance》。那份报告测了 18 个主流模型，结论是：所有模型的性能都随输入变长而下降，而且**腐烂速度和"针-问语义相似度"强相关**——字面匹配的检索几乎不腐烂，语义改写过的信息腐烂得快。

这个工具把那套实验方法简化成单文件脚本，让你可以在自己的项目文档上复现。

## 实验设计

1. 准备一堆"干扰文档"（你的真实项目文档：API 说明、日志、设计文档）
2. 写一条"针文档"——只有它能回答某个问题的事实
3. 把针插进干扰堆的不同位置（默认 10% / 50% / 90% 处）
4. 问模型那个问题，用规则判分记录对错
5. 对比两种针的差别：
   - **显式针**：指令手册风格的原文（字面可匹配）
   - **隐式针**：会议纪要风格的语义改写（需要模型自己连线）

## 快速开始

零依赖，Python 3.8+ 直接跑：

```bash
# 1. 把项目文档转成 txt 放进 docs/
# 2. 准备一根针
cp examples/needle_explicit.txt needle.txt

# 3. 跑探测（任何 OpenAI 兼容 API）
python3 context_rot_probe.py \
  --haystack_dir ./docs \
  --needle_file needle.txt \
  --question "数据库结构变更应该用什么脚本执行？在服务重启之前还是之后？" \
  --must_include "migrate_custom.sh,重启之前" \
  --forbidden "先重启,重启之后" \
  --positions 0.1,0.5,0.9 \
  --max_docs 19 \
  --runs 3 \
  --base_url https://your-api.com/v1 \
  --api_key sk-xxx \
  --model your-model \
  --out run_19.json
```

用 `--max_docs` 控制上下文长度档位（我用了 19 / 38 / 68 份文档，分别对应约 5 万 / 10.6 万 / 19.2 万 token）。

## 实测结果（2026-09）

干草堆：3 个真实企业项目的 77 份 markdown 文档（技术架构、API 规范、表结构、会议纪要式笔记），总计约 21 万 token。

模型：Agnes 3.0 Flash（OpenAI 兼容聚合 API），temperature=0，每组 3 次。

| 实验 | 上下文 | 针位置 10% | 针位置 50% | 针位置 90% |
|------|--------|-----------|-----------|-----------|
| 显式针 | 5 万 tok | 3/3 | 3/3 | 3/3 |
| 显式针 | 10.6 万 tok | 3/3 | 3/3 | 3/3 |
| 显式针 | 19.2 万 tok | 3/3 | 3/3 | 3/3 |
| **隐式针** | **5 万 tok** | 3/3 | **2/3** ⚠️ | **1/3** 🔴 |

隐式针的失败模式很有意思：模型**自信地弃权**——"根据文档内容，没有提到数据库结构变更应该用什么脚本执行"，语气笃定，还煞有介事地列举了一堆文档主题。

两种针的信息完全相同，唯一区别是措辞：显式针是"必须使用 bin/migrate_custom.sh 执行，必须在服务重启之前完成"；隐式针是"上周三架构评审会上，后端负责人拍板……这一步必须排在应用重启动作的前面"。

**字面匹配的规则 19 万 token 都扛得住，换成人话说的规则 5 万 token 就开始丢。**

完整原始数据见 `results/`。

## 判分踩坑记录

自动判分很容易被模型回答的"格式"骗到，这几个坑我们都踩过：

1. **markdown 加粗**：模型回答"重启**之前**"，裸关键词匹配"重启之前"会 miss——先剥掉 `*` 和反引号再匹配
2. **弃权时复述关键词**：模型说"文档里没有提及 bin/migrate_custom.sh"——字面包含了脚本名，但实际是检索失败。弃权声明要优先判
3. **否定语境**：模型复述约束原文"禁止在重启后再执行"，裸匹配"重启后再"会误判为答错——要检查前 12 个字符内是否有"禁止/不能/不允许"

脚本里的 `judge()` 已内置这三条处理。

## 注意事项

- 单次抽样有随机性，每组至少跑 3 次（`--runs 3`）取多数
- token 估算是粗粒度的（中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token），精确计费请以 API 返回的 usage 为准
- 干草堆文档可能包含敏感内容，请勿提交到公开仓库（.gitignore 已排除 `docs/`）
- 温度设 0 能减少随机性，但不能消除

## 参考

- Chroma, "Context Rot: How Increasing Input Tokens Impacts LLM Performance", 2025.07
- Liu et al., "Lost in the Middle: How Language Models Use Long Contexts", TACL 2024

## License

MIT
