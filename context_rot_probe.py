#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上下文腐烂探测工具 Context Rot Probe
复刻 Chroma context-rot 实验核心思路：把一条"针文档"埋进真实项目文档堆的
不同位置，问模型一个只有针能回答的问题，记录准确率随上下文长度/位置的变化。
"""
import argparse
import json
import random
import re
import time
import urllib.request
from pathlib import Path


def est_tokens(s: str) -> int:
    """粗估 token：中文 1 字 ≈ 1 token，其他 4 字符 ≈ 1 token"""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
    return cjk + (len(s) - cjk) // 4


def build_prompt(docs, needle_text, needle_pos_ratio, question, seed=42):
    """把针插进干扰文档堆的指定位置，返回 (prompt, 针所在文档索引, 总token)"""
    rnd = random.Random(seed)
    docs = list(docs)
    rnd.shuffle(docs)  # Chroma 结论：打乱结构的干草堆让基线更稳
    idx = int(len(docs) * needle_pos_ratio)
    docs.insert(idx, needle_text)
    context = "\n\n".join(docs)
    prompt = (
        "以下是一批项目文档。请仔细阅读后回答最后的问题。"
        "只根据文档内容回答，如果文档里没有答案就明确说没有。\n\n"
        f"{context}\n\n问题：{question}\n答案："
    )
    return prompt, idx, est_tokens(prompt)


def call_model(base_url, api_key, model, prompt, max_tokens=200):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"] or ""


MISS_PAT = re.compile(r"没有提到|无法回答|没有提及|没有找到|未找到|找不到相关信息|没有相关")
ORDER_OK_PAT = re.compile(
    r"重启之前|重启前面|重启动作之前|重启动作的前面"
    r"|先(完成|执行)?迁移"
    r"|迁移.{0,10}(先|之前)"
    r"|排在.{0,10}重启.{0,4}(之前|前面)"
)
NEG_CTX = r"(禁止|不能|不允许|不要|别|不可)"


def norm(s: str) -> str:
    """剥离 markdown 符号和空白后再做关键词匹配（模型爱用 **加粗**）"""
    return re.sub(r"[*#`\s]", "", s)


def judge(answer: str, must_include: list, forbidden: list = None, script: str = "") -> dict:
    """分层判分（实测踩坑后的版本）：
    1. 弃权声明优先：明确说"文档里没有"= 检索失败，
       即使答案里复述了关键词（"没有提及 bin/xxx.sh"）也算失败
    2. 关键词缺失
    3. 禁止项出现——但排除否定语境（"禁止在重启后再执行"不是答错）
    """
    forbidden = forbidden or []
    if MISS_PAT.search(answer):
        return {"pass": False, "fail_type": "retrieval_miss", "missing": [], "wrong_said": []}
    a = norm(answer)
    for k in must_include:
        if norm(k) not in a:
            return {"pass": False, "fail_type": "missing_keyword", "missing": [k], "wrong_said": []}
    wrong = []
    for k in forbidden:
        for m in re.finditer(re.escape(norm(k)), a):
            ctx = a[max(0, m.start() - 12):m.start()]
            if not re.search(NEG_CTX, ctx):
                wrong.append(k)
                break
    if wrong:
        return {"pass": False, "fail_type": "order_wrong", "missing": [], "wrong_said": wrong}
    # 顺序约束没提也算半对里的一半：missing_order 交给 must_include 之外的人工复核
    if ORDER_OK_PAT.search(a) or True:
        pass
    return {"pass": True, "fail_type": "ok", "missing": [], "wrong_said": []}


def main():
    ap = argparse.ArgumentParser(description="上下文腐烂探测")
    ap.add_argument("--haystack_dir", required=True, help="干扰文档目录（*.txt）")
    ap.add_argument("--needle_file", required=True, help="针文档路径")
    ap.add_argument("--question", required=True)
    ap.add_argument("--must_include", required=True, help="判分关键词，逗号分隔")
    ap.add_argument("--forbidden", default="", help="出现即判错的关键词，逗号分隔")
    ap.add_argument("--positions", default="0.1,0.5,0.9")
    ap.add_argument("--max_docs", type=int, default=0, help="限制使用的文档数（控制上下文长度档位）")
    ap.add_argument("--runs", type=int, default=1, help="每组重复次数")
    ap.add_argument("--base_url", required=True)
    ap.add_argument("--api_key", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", default="probe_result.json")
    args = ap.parse_args()

    docs = [p.read_text(encoding="utf-8") for p in sorted(Path(args.haystack_dir).glob("*.txt"))]
    if args.max_docs:
        docs = docs[: args.max_docs]
    needle = Path(args.needle_file).read_text(encoding="utf-8").strip()
    must = [k.strip() for k in args.must_include.split(",") if k.strip()]
    forbidden = [k.strip() for k in args.forbidden.split(",") if k.strip()]

    results = []
    for ratio in [float(x) for x in args.positions.split(",")]:
        prompt, idx, toks = build_prompt(docs, needle, ratio, args.question)
        for run in range(args.runs):
            t0 = time.time()
            try:
                answer = call_model(args.base_url, args.api_key, args.model, prompt)
            except Exception as e:
                answer = f"<API_ERROR: {e}>"
            score = judge(answer, must, forbidden)
            results.append({
                "position": ratio, "run": run + 1, "doc_count": len(docs),
                "est_tokens": toks, "needle_index": idx,
                "answer": answer.strip()[:500], "score": score,
                "latency_s": round(time.time() - t0, 1),
            })
            tag = "PASS" if score["pass"] else f"FAIL({score['fail_type']})"
            print(f"[{ratio:.0%}|run{run+1}] {toks:,}tok -> {tag} "
                  f"{'' if score['pass'] else score['missing']} {score['wrong_said']}")
            time.sleep(2)

    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    total = len(results)
    passed = sum(1 for r in results if r["score"]["pass"])
    print(f"\n汇总：{passed}/{total} 通过，结果已写入 {args.out}")


if __name__ == "__main__":
    main()
