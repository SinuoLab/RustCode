#!/usr/bin/env python3
"""RustCode 中文文档验收脚本。stdlib only, 无网络, 无第三方依赖。

用法:
  python3 scripts/check-zh-docs.py inventory [--base REV] [--out PATH]
  python3 scripts/check-zh-docs.py check     [--base REV] (--files P... | --diff) [--report PATH] [--en-ratio F]
  python3 scripts/check-zh-docs.py hostscan  [--base REV]   # 清单产出器，非门禁，恒返回 0
  python3 scripts/check-zh-docs.py gate      [--base REV] [--report PATH]

退出码: 0 = 全部通过 | 1 = 至少一项 FAIL | 2 = 用法/IO 错误
默认 --base = "3ee655e3"（可用环境变量 ZH_BASE 覆盖）

比较基线固定为 ZH_BASE（默认 3ee655e3），禁止用 HEAD 作默认基线：
中途分批 commit 后与 HEAD 比较会产生假绿。--base 只可显式覆盖。
"""

import argparse
import os
import posixpath
import re
import subprocess
import sys

DEFAULT_BASE: str = "3ee655e3"
EN_RATIO_DEFAULT: float = 0.05

# 分类桶（AC-1：SKIP_A + SKIP_B + SKIP_C + SKIP_D + TODO + ZH == 受检 md 总数（已排除 artifacts 豁免域））
SKIP_A_LICENSE = ("license", "licence", "notices", "credits", "copying")  # 路径/文件名小写包含即跳过
SKIP_B_RULES = "crates/rustcode-review/rules/"
SKIP_C_VERBATIM = ("extensions/jetbrains/CHANGELOG.md",)
# D 类：运行时 prompt 载荷（喂给评测判定模型的 prompt），与 SKIP_B 的 rules/*.md 同源 ——
# 汉化会改变评测语义与下游输出解析，故不汉化。
# 裁决来源：feature 2026-09-07-zh-docs-webui 编排裁决（见 03-impl/T-06-gate-script.md）。
# 固定清单，禁止按目录/通配扫描扩充；新增成员必须走裁决，不得由脚本自动发现。
SKIP_D_PROMPTS = (
    "evals/deepseek-v4-flash/prompts/codex-judge.md",
    "evals/deepseek-v4-flash/prompts/codex-report.md",
)
# 不参与汉化但计入 ZH 桶（owner 非 doc-writer）：
OWNED_ELSEWHERE = ("AGENTS.md", "README.zh-CN.md", ".codebuddy/artifacts/2026-09-07-zh-docs-webui/")

# ------------------------------------------------- artifacts 豁免域（T-16）
#
# 裁决来源：feature 2026-09-07-zh-docs-webui 用户裁决「本 feature 改动全部提交，含
# `.codebuddy/artifacts/**` 交接件」的前置条件（PM 裁决落地于本任务）。
#
# 背景：AC-1 的分母是「已跟踪 md」（`git ls-files '*.md'`）。本 feature 的交接件 md
# 在 `git add` 之前属于未跟踪文件，被 gate 显式排除在分母外；一旦 `git add`，它们以
# 「基线不存在」的身份进入分母，AC-4 会把全文 code span 记为 added -> 大面积假 FAIL，
# AC-2/6/7b/32 也会对交接件正文判分。
#
# 裁决：不改判据、不放宽阈值，改为把 `.codebuddy/artifacts/` 提升为与 SKIP_A..SKIP_D
# 同级的**显式豁免域** —— 按路径前缀判定，与基线无关、与是否已跟踪无关。被豁免的文件
# 既不进 AC-1 分母，也不受 AC-2/4/6/7b/32 与 AC-8 段 1 约束（AC-8 段 2 仍以它们作为
# 「历史域」做反向断言）。因此提交（stage）前后门禁语义完全一致。
#
# 边界（禁止外溢）：只豁免我这一个前缀。`.codebuddy/agents/*.md` 是已跟踪且参与 AC-4
# 判分的正式文档，前缀不同，不受影响；`.codebuddy/memory/`、`.codebuddy/teams/` 同理
# 不在域内。显式 `--files` 指定的路径不受豁免影响（见 `resolve_files()`）。
ARTIFACTS_EXEMPT_PREFIX = ".codebuddy/artifacts/"


def is_artifacts_exempt(path: str) -> bool:
    """批量候选是否落在 artifacts 豁免域内（路径前缀精确匹配，非 glob）。"""
    return path.startswith(ARTIFACTS_EXEMPT_PREFIX)

# ------------------------------------------------------------------ AC-4 v2
#
# 判据来源：.codebuddy/artifacts/2026-09-07-zh-docs-webui/01-design-addendum.md
#          （DESIGN-001-A1）§2「AC-4 判据（v2，冻结）」。本文件只按该补遗实现，
#          不得自行放宽或加严；补遗未授权的新类别（D3）必须走裁决。
#
# v2 相对 v1（removed ⊆ {README.zh-CN.md} 且 added 为空）的差别：
#   v1 只回答「消失的 span 是不是那个被删文件」，v2 额外要求「每一条 D1 移除都能被
#   冻结算子 ac4_excise 机械解释，且其产生的等价串逐字出现」。即：只允许被删文件名
#   连同至多一个紧邻分隔符被剔除，其余字符一字不改。
#
# 强度不降的论证（补遗 §2.6，实现者必须保持该性质）：
#   - 等效域：对「不含 README.zh-CN.md 且不等于 ./scripts/build-webui.sh」的任意 span，
#     v2 与 v1 判定完全相同 —— added 一侧两版都必然越界 FAIL（v1：added 非空；
#     v2：不在按文件冻结的放行表内，该表仅 README.md 一个成员）；removed 一侧两版
#     都越界 FAIL。v2 的放宽只发生在与已冻结裁决 D1/D2 有字面因果关系的 span 上。
#   - v2 新增 v1 没有的硬约束：
#       (a) D1 移除必须逐条可解释（span 字面含已删文件名）；
#       (b) 其对应 added 必须是 ac4_excise 的机械输出，而非任意串；
#       (c) 一致性护栏（放行后 new_text 全文不得残留 README.zh-CN 字面量，防半清理）；
#       (d) 放行必须可见（不打印 AC-4-authorized 明细即视同静默放行 -> FAIL）。
#   - 不变量：AC-2 阈值 0.05、AC-6、AC-7a、AC-7b、AC-32 的判据与常量一律不变；
#     code_spans / ac4_span_diff 的提取与完整性（含不截断）不变。
#
# 冻结常量（补遗 §2.3）：不得通配、不得按目录匹配、不得运行时自动发现。
AC4_DELETED_DOC = "README.zh-CN.md"  # 裁决 D1 删除的交付文档
AC4_DELETED_DOC_FULL_RE = re.compile(r"README\.zh-CN\.md(:\d+)?")  # 仅用于 ac4_excise 的 S1 fullmatch
# 裁决 D2：绑定到具体文件的授权新增。键是路径全名（完整相等，非前缀/非通配）。
# 每项计数上限 AC4_MAX_PER_ENTRY（同一 span 在文件里只放行一次），所以被登记的文件
# 必须把行内 code span 用到"每个技术标识只出现一次"——重复出现要么改写中文复述，
# 要么搬进同目录附属 .sh（AC-4 只扫 md）。2026-10-18 交接文档即按此约定登记。
AC4_ALLOWED_ADDED_BY_FILE = {
    "README.md": ("./scripts/build-webui.sh",),
    # docs/handoff/2026-10-18-release-pointers-and-test-hygiene.md（2026-10-18 交接文档，D2 登记 32 项）
    "docs/handoff/2026-10-18-release-pointers-and-test-hygiene.md": (
        '--online', '--sha', '.githooks/pre-push', '/upgrade', '38764522684', '38993016685',
        '39136327878', '51f9a4553', '6.2.3', '60b71be34', '855cf3efc', '90d5038d9', '97f9d235f',
        'AGENTS.md', 'Cargo.toml', 'RUSTCODE_HOME', 'RUSTCODE_PREPUSH_POINTERS=off',
        'RUSTCODE_TEST_INCREMENTAL=1', 'RUSTCODE_TEST_JOBS', 'RUSTCODE_TEST_SYMBOLS=1',
        '[workspace.package].version', 'c55850c4c',
        'docs/handoff/2026-10-18-release-pointers-verify.sh', 'git push origin dev',
        'git rm -r release/v6.2.3', 'latest.json', 'min(nproc,2)', 'release version pointers',
        'release/index.json', 'release/v5.1.0/', 'scripts/release-check-pointers.sh', 'v6.2.1',
    ),
}
AC4_MAX_PER_ENTRY = 1  # 同一 (file, span) 放行次数上限
AC4_NOT_D1 = object()  # 哨兵：该 span 与 D1 无关
# 一致性护栏子串（补遗 §2.1 第 4 步）：D1 放行后 new_text 不得再出现该子串（含非 span 位置）
AC4_CONSISTENCY_NEEDLE = "README.zh-CN"
AC4_LINENO_ONLY_RE = re.compile(r":\d+")  # 仅用于 ac4_excise 的 S5

# ------------------------------------------------------------------ AC-8 v2
#
# 判据来源：01-design-addendum.md §3「AC-8 作用域（v2，冻结）」。
# 三段结构：正式域 0 命中 / 历史域反向断言（必须仍有命中）/ 既有全扩展名兜底域 0 命中。
# 排除集只有 AC8_EXEMPT_PREFIX 这一个成员，按路径前缀精确匹配（非 glob 通配）；
# 成员数必须恒为 1，禁止运行时发现、禁止新增 --allow/--skip 开关。
AC8_NEEDLE = "README.zh-CN"
AC8_GLOBS = ("*.md", "*.html", "*.json", "*.ts", "*.kt", "*.yml", "*.toml")
AC8_EXEMPT_PREFIX = ARTIFACTS_EXEMPT_PREFIX  # 唯一豁免成员（复用 artifacts 豁免域常量，值不变）
AC8_ANCHOR_FILES = ("README.md", "AGENTS.md")  # 反向护栏锚点（A2）
AC8_FALLBACK_SCOPES = ("site", ".github", "docs", "extensions")  # 段 3 兜底域（语义同既有第二次 grep）


FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_RE = re.compile(r"`[^`\n]*`")
URL_RE = re.compile(r"(https?://|mailto:)\S+")
HTML_RE = re.compile(r"<[^>]+>")
IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
TABLE_SEP_RE = re.compile(r"^\|?[\s:\-|]+\|[\s:\-|]*$")
ASCII4_RE = re.compile(r"[A-Za-z]{4,}")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff]")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")

# R5（缩进代码块 / 引用块内裸日志）的护栏：行内出现中文标点即视为散文，不跳过
CJK_PUNCT = "，。：；、"

# hostscan：正文中出现该字面量且语义为"默认绑定"的行才算命中
HOST_LITERAL_RE = re.compile(r"127\.0\.0\.1|localhost")
# 用 default 词干而非 \bdefault\b：需覆盖 default / defaults / defaulting / defaulted
HOST_DEFAULT_RE = re.compile(r"(?i)(\bdefault|默认)")
# 反例护栏（命中后排除）：
#   1) 显式传参/覆盖默认的语境 —— 属于 T-06 明确保留的"IP 字面量"；
#   2) 否定语境（"非默认值"）—— 该行恰恰声明它不是默认值，误报会诱导 T-06 反向改写。
HOST_EXCLUDE_RE = re.compile(r"(?i)(--host\b|\bexplicit|\boverride|显式|手动指定|非默认)")

SKIP_BUCKETS = ("SKIP_A", "SKIP_B", "SKIP_C", "SKIP_D")
TODO_BUCKETS = ("EN", "MIXED")

# stdout 上单个文件最多打印的 offender / R5 行数（完整清单写进 --report）
STDOUT_OFFENDER_LIMIT = 200
STDOUT_R5_LIMIT = 50


# ---------------------------------------------------------------- git helpers


class EnvError(Exception):
    """用法 / IO / git 环境问题 —— 一律映射到退出码 2，绝不当作 PASS。"""


def _git(args, root):
    # `-c core.quotePath=false`：git 默认把含非 ASCII 的路径写成八进制转义并整体加引号
    # （如 `".../HANDOFF-\346\261\211\345\214\226\351\223\201\345\276\213.md"`）。这类字符串
    # 既不是磁盘上的真实路径（os.path.isfile 判否），也不匹配任何路径前缀常量 —— 会让
    # artifacts 豁免域与 AC-8 段 2 的前缀判定静默漏掉非 ASCII 文件名的交接件（T-16 实测）。
    # 关掉该选项后，git 输出即仓库真实路径（UTF-8 原样），前缀匹配与文件读取都成立。
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotePath=false"] + args,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise EnvError("git 调用失败: %s" % exc)
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def find_root():
    rc, out, err = _git(["rev-parse", "--show-toplevel"], os.getcwd())
    if rc != 0:
        raise EnvError("不在 git 仓库内: %s" % err.strip())
    root = out.strip()
    if not root:
        raise EnvError("git rev-parse --show-toplevel 返回空")
    return root


def git_lines(args, root):
    rc, out, err = _git(args, root)
    if rc != 0:
        raise EnvError("git %s 失败: %s" % (" ".join(args), err.strip()))
    return [ln for ln in out.split("\n") if ln.strip() != ""]


def list_md_files(root):
    """AC-1 的分母：仓库当前跟踪的全部 md，减去 artifacts 豁免域。

    等价于 `git ls-files -- '*.md'` 再过滤 `ARTIFACTS_EXEMPT_PREFIX`（T-16）。
    `inventory` / `gate` 共用此函数，故两个子命令的分母与豁免语义天然一致。
    """
    return sorted(
        path for path in git_lines(["ls-files", "--", "*.md"], root) if not is_artifacts_exempt(path)
    )


def read_work_file(root, path):
    full = os.path.join(root, path)
    if not os.path.isfile(full):
        return None
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        raise EnvError("读取工作区文件失败 %s: %s" % (path, exc))


def verify_base_commit(root, base):
    """确认 `--base` 是一个可解析的 commit。

    不做这一步时，`git show <base>:<path>` 对非法 base 也会失败，而
    `read_base_file()` 会把失败一律当成「基线无此文件」，于是每个文件都被判为新增、
    AC-4/AC-2 刷出几百条假 FAIL，真正的根因（base 非法，退出码本该是 2）被淹没在
    FAIL 里。故在消耗 base 之前先显式校验。
    """
    rc, out, err = _git(["rev-parse", "--verify", "--quiet", "%s^{commit}" % base], root)
    if rc != 0 or not out.strip():
        raise EnvError(
            "--base 不是可解析的 commit: %r（git rev-parse --verify %s^{commit} 失败: %s）"
            % (base, base, err.strip() or "无输出")
        )
    return out.strip()


def read_base_file(root, base, path):
    """git show <base>:<path>；文件在基线不存在时返回 None（新增文件退化为与空文档比较）。"""
    rc, out, _err = _git(["show", "%s:%s" % (base, path)], root)
    if rc != 0:
        return None
    return out


# ------------------------------------------------------------------ AC-1 分类


def classify(path: str, han_lines: int, letter_lines: int) -> str:
    """返回 SKIP_A / SKIP_B / SKIP_C / SKIP_D / EN / MIXED / ZH。

    ratio = han_lines / max(letter_lines, 1)
    ratio == 0        -> EN
    0 < ratio < 0.5   -> MIXED
    ratio >= 0.5      -> ZH      # 已中文：不许改写，只许修 en 行
    """
    lowered = path.lower()
    if any(key in lowered for key in SKIP_A_LICENSE):
        return "SKIP_A"
    if path.startswith(SKIP_B_RULES):
        return "SKIP_B"
    if path in SKIP_C_VERBATIM:
        return "SKIP_C"
    if path in SKIP_D_PROMPTS:
        return "SKIP_D"
    if is_owned_elsewhere(path):
        return "ZH"
    ratio = han_lines / max(letter_lines, 1)
    if ratio == 0:
        return "EN"
    if ratio < 0.5:
        return "MIXED"
    return "ZH"


def is_owned_elsewhere(path: str) -> bool:
    for item in OWNED_ELSEWHERE:
        if item.endswith("/"):
            if path.startswith(item):
                return True
        elif path == item:
            return True
    return False


def count_lang_lines(text):
    """返回 (han_lines, letter_lines)：含 CJK 的行数 / 含任意 ASCII 字母的行数。"""
    han = 0
    letter = 0
    for line in text.split("\n"):
        if CJK_RE.search(line):
            han += 1
        if re.search(r"[A-Za-z]", line):
            letter += 1
    return han, letter


# ---------------------------------------------------------------------- AC-2


def split_frontmatter(text):
    """仅当第 1 行为 `---` 时，剥到下一个 `---`。返回 (body_text, frontmatter_lines)。"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text, []
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "\n".join(lines[idx + 1 :]), lines[: idx + 1]
    return text, []


def strip_frontmatter(text):
    body, _fm = split_frontmatter(text)
    return body


def frontmatter_block(text):
    _body, fm = split_frontmatter(text)
    return fm


def _strip_blockquote(line: str) -> str:
    """逐层剥掉 `>` 引用标记（以及其后最多一个空格）。非引用行原样返回。"""
    cur = line
    while True:
        stripped = cur.lstrip()
        if not stripped.startswith(">"):
            return cur
        cur = cur[cur.index(">") + 1 :]
        if cur.startswith(" "):
            cur = cur[1:]


def _is_fence(line: str) -> bool:
    """fence 开/关行；同时识别引用块内的 fence（`> ```rust`）。"""
    return bool(FENCE_RE.match(line) or FENCE_RE.match(_strip_blockquote(line)))


def _is_indented(line: str) -> bool:
    return line.startswith("    ") or line.startswith("\t")


def _has_cjk_punct(line: str) -> bool:
    return any(ch in line for ch in CJK_PUNCT)


def _bq_fence_flags(lines):
    """标记"位于含 fence 的引用块内"的行 —— R5 的第二种形态（裸日志行）。"""
    flags = [False] * len(lines)
    idx = 0
    total = len(lines)
    while idx < total:
        if lines[idx].lstrip().startswith(">"):
            end = idx
            while end < total and lines[end].lstrip().startswith(">"):
                end += 1
            if any(_is_fence(lines[k]) for k in range(idx, end)):
                for k in range(idx, end):
                    flags[k] = True
            idx = end
        else:
            idx += 1
    return flags


def ac2_en_lines(text):
    """返回 (total, en, offenders, r5_skipped)。

    逐行：
       R1 剥 frontmatter（整块）
       R2 fence 内外状态机：fence 开/关行与其内部全部行 -> skip
       R3 4 空格及以上缩进的行（缩进代码块）-> skip          【补充规则 R5，见设计 §10.1】
          + 引用块内含 fence 时的裸日志行 -> skip
          护栏：行内含中文标点（，。：；、）时不跳过，回落为散文判定
       R4 去 inline code / URL / HTML 标签 / 图片 / 表格分隔行
       R5 剩余为空行 -> skip（不进 total）
       否则 total += 1
       if ASCII4_RE.search(l) and not CJK_RE.search(l): en += 1; offenders.append((lineno, raw))
    """
    body, fm = split_frontmatter(text)
    offset = len(fm)
    lines = body.split("\n")
    flags = _bq_fence_flags(lines)

    total = 0
    en = 0
    offenders = []
    r5_skipped = []
    inside = False
    idx = 0
    nlines = len(lines)

    while idx < nlines:
        raw = lines[idx]
        eff = _strip_blockquote(raw)

        # R2
        if _is_fence(raw):
            inside = not inside
            idx += 1
            continue
        if inside:
            idx += 1
            continue

        # R5（空行不进 total）
        if raw.strip() == "":
            idx += 1
            continue

        # R3-a 缩进代码块
        if _is_indented(eff) and not _has_cjk_punct(eff):
            r5_skipped.append((offset + idx + 1, raw))
            idx += 1
            continue

        # R3-b 含 fence 的引用块内的裸日志行
        if flags[idx] and not _has_cjk_punct(eff):
            r5_skipped.append((offset + idx + 1, raw))
            idx += 1
            continue

        # R4
        probe = INLINE_RE.sub("", eff)
        probe = URL_RE.sub("", probe)
        probe = HTML_RE.sub("", probe)
        probe = IMG_RE.sub("", probe)
        if TABLE_SEP_RE.match(probe.strip()):
            idx += 1
            continue

        # R5（剥离后为空 -> 不进 total）
        if probe.strip() == "":
            idx += 1
            continue

        total += 1
        if ASCII4_RE.search(probe) and not CJK_RE.search(probe):
            en += 1
            offenders.append((offset + idx + 1, raw))
        idx += 1

    return total, en, offenders, r5_skipped


def en_ratio_of(total: int, en: int) -> float:
    if total == 0:
        return 0.0
    return en / total


# ------------------------------------------- AC-4 / AC-7 / AC-32 / AC-6 比较


def code_spans(text):
    """sorted(inline code 去反引号 + fence body 行)：多重集。"""
    out = []
    for match in INLINE_RE.finditer(text):
        out.append(match.group(0).strip("`"))
    inside = False
    for line in text.split("\n"):
        if _is_fence(line):
            inside = not inside
            continue
        if inside:
            out.append(line)
    return sorted(out)


def link_targets(text):
    """`](...)` 内的目标串，排序后返回（多重集；显示文字不参与比较）。"""
    return sorted(re.findall(r"\]\(([^)]*)\)", text))


def frontmatter_keys(text):
    """frontmatter 块内 ^([A-Za-z_][A-Za-z0-9_]*): 的键名，排序后返回。"""
    keys = []
    for line in frontmatter_block(text):
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):", line)
        if match:
            keys.append(match.group(1))
    return sorted(keys)


def emoji_hits(text) -> int:
    """len(EMOJI_RE.findall(text))；与 base 版本比较，只允许 <=。"""
    return len(EMOJI_RE.findall(text))


def frontmatter_desc(text):
    """frontmatter 的 description 值（用于 AC-6 逐条列示）。"""
    for line in frontmatter_block(text):
        match = re.match(r"^description:\s*(.*)$", line)
        if match:
            return match.group(1).strip()
    return None


def multiset_diff(old_items, new_items, limit=10):
    """返回 (removed_only, added_only) 两个精简清单，用于 FAIL 详情。"""
    from collections import Counter

    old_counter = Counter(old_items)
    new_counter = Counter(new_items)
    removed = sorted((old_counter - new_counter).elements())
    added = sorted((new_counter - old_counter).elements())
    return removed[:limit], added[:limit]


def ac4_span_diff(old_spans, new_spans):
    """AC-4 专用：完整（不截断）的多重集差，返回 (removed_all, added_all)。

    不复用 multiset_diff：判据必须基于完整差集，截断会导致越界移除漏判。
    """
    from collections import Counter

    old_counter = Counter(old_spans)
    new_counter = Counter(new_spans)
    return (
        sorted((old_counter - new_counter).elements()),
        sorted((new_counter - old_counter).elements()),
    )


def ac4_excise(span: str):
    """D1 最小剔除式重写算子（补遗 §2.2，冻结；顺序固定，每步至多替换一次）。

    返回:
      None        -> 允许该 span 整体消失（不产生对应 added）
      str         -> 允许出现且只允许出现该等价串（调用方按多重集扣减 1）
      AC4_NOT_D1  -> 该 span 与 D1 无关（调用方判越界移除）

    步骤（顺序不可调换，禁止任何其它字符改动）:
      S1 fullmatch AC4_DELETED_DOC_FULL_RE (README\\.zh-CN\\.md(:\\d+)?)  -> None
      S2 " / README.zh-CN.md" in span -> replace(..., "", 1)
      S3 elif " README.zh-CN.md" in span -> replace(..., "", 1)
      S4 elif "README.zh-CN.md" in span  -> replace(..., "", 1)
      S5 结果 .strip() 为空、或 fullmatch(:\\d+) -> None
      S6 未含 AC4_DELETED_DOC -> AC4_NOT_D1
    """
    if AC4_DELETED_DOC_FULL_RE.fullmatch(span):
        return None  # S1
    if " / " + AC4_DELETED_DOC in span:
        out = span.replace(" / " + AC4_DELETED_DOC, "", 1)  # S2
    elif " " + AC4_DELETED_DOC in span:
        out = span.replace(" " + AC4_DELETED_DOC, "", 1)  # S3
    elif AC4_DELETED_DOC in span:
        out = span.replace(AC4_DELETED_DOC, "", 1)  # S4
    else:
        return AC4_NOT_D1  # S6
    if out.strip() == "" or AC4_LINENO_ONLY_RE.fullmatch(out):
        return None  # S5
    return out


def ac4_verdict(path, old_text, new_text, old_spans, new_spans):
    """AC-4 v2 判定（补遗 §2.1）。返回 (ok, failures, authorized)。

    authorized 元素为 (path, removed_span | "-", added_span | "-", cause)
    —— cause 取 "D1"（最小剔除式等价/允许整体消失）或 "D2"（冻结登记的新增）。

    判定顺序（逐字照补遗，不得增删条件）：
      0. removed 与 added 同时为空 -> PASS，无明细
      1. removed 每条必须字面含 AC4_DELETED_DOC，否则越界移除 -> FAIL
      2. 对每条 D1 移除 r，e = ac4_excise(r)：
           e is None  -> 允许整体消失，不产生 added
           e is str   -> added 中必须恰有一条等于 e（多重集扣减 1），缺则 FAIL
      3. 扣减后剩余 added 必须逐条是绑定到本文件的 D2 项且计数 <= AC4_MAX_PER_ENTRY
      4. 一致性护栏：产生过 D1 放行时，new_text 全文不得再出现 README.zh-CN 子串
      5. 可见性：放行明细由调用方打印（本函数只负责产出）
    """
    from collections import Counter

    removed, added = ac4_span_diff(old_spans, new_spans)
    if not removed and not added:
        return True, [], []

    failures = []
    authorized = []
    added_counter = Counter(added)

    # 第 1、2 步：逐条 D1 移除
    for span in removed:
        if AC4_DELETED_DOC not in span:
            failures.append(
                "越界移除（非 D1：span 字面不含 %s）: %s" % (AC4_DELETED_DOC, repr(span))
            )
            continue
        excised = ac4_excise(span)
        if excised is AC4_NOT_D1:  # pragma: no cover - 第 1 步已保证不会发生
            failures.append("越界移除（ac4_excise 判 AC4_NOT_D1）: %s" % repr(span))
            continue
        if excised is None:
            authorized.append((path, span, "-", "D1"))
            continue
        if added_counter[excised] > 0:
            added_counter[excised] -= 1
            authorized.append((path, span, excised, "D1"))
        else:
            failures.append(
                "D1 移除未产生最小剔除式等价 span: removed=%s 期望 added=%s"
                % (repr(span), repr(excised))
            )

    # 第 3 步：剩余 added 只可能是绑定到本文件的 D2 项
    remaining = sorted(added_counter.elements())
    remaining_counter = Counter(remaining)
    for span in remaining:
        allowed = AC4_ALLOWED_ADDED_BY_FILE.get(path, ())
        bound = path in AC4_ALLOWED_ADDED_BY_FILE
        within_quota = remaining_counter[span] <= AC4_MAX_PER_ENTRY
        if bound and span in allowed and within_quota:
            authorized.append((path, "-", span, "D2"))
        else:
            failures.append(
                "越界新增（未登记在 AC4_ALLOWED_ADDED_BY_FILE[%r] 内或超过计数上限 %d）: %s"
                % (path, AC4_MAX_PER_ENTRY, repr(span))
            )

    # 第 4 步：一致性护栏（半清理）
    if any(item[3] == "D1" for item in authorized) and AC4_CONSISTENCY_NEEDLE in new_text:
        failures.append(
            "一致性护栏：本文件已放行 D1 移除，但 new_text 仍残留子串 %s（半清理）"
            % AC4_CONSISTENCY_NEEDLE
        )

    return (not failures), failures, authorized


# ------------------------------------------------------------------ check 内核


class FileResult:
    def __init__(self, path):
        self.path = path
        self.total = 0
        self.en = 0
        self.ratio = 0.0
        self.offenders = []
        self.r5_skipped = []
        self.failures = []  # [(ac, detail_lines)]
        self.notes = []  # [(ac, text)]
        self.is_new = False
        # AC-4 v2：授权放行明细 [(path, removed|"-", added|"-", cause)]，cause in {D1, D2}
        self.authorized = []

    @property
    def ok(self):
        return not self.failures


def check_file(root, base, path, en_ratio):
    result = FileResult(path)
    new_text = read_work_file(root, path)
    if new_text is None:
        raise EnvError("工作区文件不存在: %s" % path)
    old_text = read_base_file(root, base, path)
    if old_text is None:
        old_text = ""
        result.is_new = True

    total, en, offenders, r5 = ac2_en_lines(new_text)
    result.total = total
    result.en = en
    result.ratio = en_ratio_of(total, en)
    result.offenders = offenders
    result.r5_skipped = r5

    # AC-2
    if result.ratio > en_ratio:
        detail = ["AC-2 en_ratio %.4f > %.4f (en=%d/total=%d)" % (result.ratio, en_ratio, en, total)]
        for lineno, raw in offenders[:STDOUT_OFFENDER_LIMIT]:
            detail.append("  %s:%d: %s" % (path, lineno, raw.rstrip()))
        if len(offenders) > STDOUT_OFFENDER_LIMIT:
            detail.append("  ... 其余 %d 行见 --report" % (len(offenders) - STDOUT_OFFENDER_LIMIT))
        result.failures.append(("AC-2", detail))

    # AC-4 v2：code span 多重集严格相等，仅放行与裁决 D1/D2 有字面因果关系的差异
    old_spans = code_spans(old_text)
    new_spans = code_spans(new_text)
    ok4, failures4, authorized4 = ac4_verdict(path, old_text, new_text, old_spans, new_spans)
    result.authorized = authorized4
    if failures4:
        removed, added = ac4_span_diff(old_spans, new_spans)
        detail = ["AC-4 code span 多重集不等 (old=%d new=%d)" % (len(old_spans), len(new_spans))]
        for item in failures4[:STDOUT_OFFENDER_LIMIT]:
            detail.append("  %s" % item)
        detail.append("  完整 removed: %s" % (removed or "无"))
        detail.append("  完整 added: %s" % (added or "无"))
        result.failures.append(("AC-4", detail))
    elif authorized4:
        # 可见性硬要求（补遗 §2.1 第 5 步）：有放行必须打印明细，静默 PASS 视同 FAIL
        for auth_path, removed_span, added_span, cause in authorized4:
            result.notes.append(
                (
                    "AC-4-authorized",
                    "%s | removed=%s | added=%s | cause=%s"
                    % (auth_path, removed_span, added_span, cause),
                )
            )

    # AC-7b 链接目标多重集相等
    old_links = link_targets(old_text)
    new_links = link_targets(new_text)
    if old_links != new_links:
        removed, added = multiset_diff(old_links, new_links)
        result.failures.append(
            (
                "AC-7b",
                [
                    "AC-7b 链接目标多重集不等 (old=%d new=%d)" % (len(old_links), len(new_links)),
                    "  仅存在于基线: %s" % (removed or "无"),
                    "  仅存在于工作区: %s" % (added or "无"),
                ],
            )
        )

    # AC-32 emoji 命中数不增加
    old_emoji = emoji_hits(old_text)
    new_emoji = emoji_hits(new_text)
    if new_emoji > old_emoji:
        result.failures.append(
            ("AC-32", ["AC-32 emoji 命中数增加: 基线 %d -> 工作区 %d" % (old_emoji, new_emoji)])
        )

    # AC-6 frontmatter 键名集合相等
    old_keys = frontmatter_keys(old_text)
    new_keys = frontmatter_keys(new_text)
    if old_keys != new_keys:
        removed, added = multiset_diff(old_keys, new_keys)
        result.failures.append(
            (
                "AC-6",
                [
                    "AC-6 frontmatter 键名集合不等",
                    "  仅存在于基线: %s" % (removed or "无"),
                    "  仅存在于工作区: %s" % (added or "无"),
                ],
            )
        )
    old_desc = frontmatter_desc(old_text)
    new_desc = frontmatter_desc(new_text)
    if old_desc != new_desc:
        result.notes.append(
            (
                "AC-6-desc-changed",
                "description: %s => %s" % (repr(old_desc), repr(new_desc)),
            )
        )

    return result


def print_check_result(result):
    verdict = "PASS" if result.ok else "FAIL"
    print(
        "%s %s en=%d/%d=%.4f%s"
        % (
            verdict,
            result.path,
            result.en,
            result.total,
            result.ratio,
            " (新增文件)" if result.is_new else "",
        )
    )
    for ac, detail in result.failures:
        for line in detail:
            print("  [%s] %s" % (ac, line))
    for ac, text in result.notes:
        print("  [%s] %s" % (ac, text))


def render_check_report(base, results, en_ratio, r5_all):
    lines = []
    lines.append("# zh-check 报告")
    lines.append("")
    lines.append("- 基线 (--base): `%s`" % base)
    lines.append("- 阈值 (--en-ratio): `%s`" % en_ratio)
    lines.append("- 判定: AC-2 / AC-4 / AC-6 / AC-7b / AC-32，任一失败即 FAIL（fail-closed）")
    lines.append("")
    failed = [r for r in results if not r.ok]
    lines.append("## 汇总")
    lines.append("")
    lines.append("- 受检文件: %d" % len(results))
    lines.append("- PASS: %d" % (len(results) - len(failed)))
    lines.append("- FAIL: %d" % len(failed))
    lines.append("")
    for result in results:
        lines.append("## %s `%s`" % ("PASS" if result.ok else "FAIL", result.path))
        lines.append("")
        lines.append("- en=%d/%d ratio=%.4f" % (result.en, result.total, result.ratio))
        for ac, detail in result.failures:
            lines.append("- **%s FAIL**" % ac)
            for item in detail:
                lines.append("  - `%s`" % item.replace("`", "'"))
        for ac, text in result.notes:
            lines.append("- %s: `%s`" % (ac, text.replace("`", "'")))
        if result.offenders:
            lines.append("- AC-3 残留行清单 (en 行，共 %d 行):" % len(result.offenders))
            for lineno, raw in result.offenders:
                lines.append("  - `%s:%d`: `%s`" % (result.path, lineno, raw.rstrip().replace("`", "'")))
        if result.r5_skipped:
            lines.append("- R5 跳过的行 (共 %d 行):" % len(result.r5_skipped))
            for lineno, raw in result.r5_skipped:
                lines.append("  - `%s:%d`: `%s`" % (result.path, lineno, raw.rstrip().replace("`", "'")))
        lines.append("")
    if r5_all:
        lines.append("## 附录 · 被 R5 跳过的行（供抽检）")
        lines.append("")
        lines.append("共 %d 行。" % len(r5_all))
        lines.append("")
        for path, lineno, raw in r5_all:
            lines.append("- `%s:%d`: `%s`" % (path, lineno, raw.rstrip().replace("`", "'")))
        lines.append("")
    return "\n".join(lines)


def write_report(path, content):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


# ------------------------------------------------------------------ inventory


def build_inventory(root, files):
    entries = []
    for path in files:
        text = read_work_file(root, path)
        if text is None:
            text = read_base_file(root, path) or ""
        han, letter = count_lang_lines(text)
        bucket = classify(path, han, letter)
        entries.append(
            {
                "path": path,
                "bucket": bucket,
                "han": han,
                "letter": letter,
                "ratio": (han / max(letter, 1)) if letter or han else 0.0,
                "owned_elsewhere": is_owned_elsewhere(path),
            }
        )
    return entries


def inventory_counts(entries):
    counts = {"SKIP_A": 0, "SKIP_B": 0, "SKIP_C": 0, "SKIP_D": 0, "EN": 0, "MIXED": 0, "ZH": 0}
    for entry in entries:
        counts[entry["bucket"]] += 1
    return counts


def render_inventory(base, entries):
    counts = inventory_counts(entries)
    total = len(entries)
    skip = counts["SKIP_A"] + counts["SKIP_B"] + counts["SKIP_C"] + counts["SKIP_D"]
    todo = counts["EN"] + counts["MIXED"]
    zh = counts["ZH"]
    identity_ok = skip + todo + zh == total

    out = []
    out.append("# md 清单（AC-1）")
    out.append("")
    out.append("- 生成者: `scripts/check-zh-docs.py inventory`")
    out.append("- 基线 (--base): `%s`" % base)
    out.append(
        "- 分母: `git ls-files -- '*.md'`（仓库当前跟踪的 md），已排除 artifacts 豁免域 `%s`（T-16）"
        % ARTIFACTS_EXEMPT_PREFIX
    )
    out.append("")
    out.append("## 恒等式")
    out.append("")
    out.append("```")
    out.append(
        "SKIP_A(%d) + SKIP_B(%d) + SKIP_C(%d) + SKIP_D(%d) + TODO(%d) + ZH(%d) = %d ；受检 md 总数（已排除 artifacts 豁免域） = %d ；%s"
        % (
            counts["SKIP_A"],
            counts["SKIP_B"],
            counts["SKIP_C"],
            counts["SKIP_D"],
            todo,
            zh,
            skip + todo + zh,
            total,
            "恒等式成立" if identity_ok else "恒等式 **不成立**",
        )
    )
    out.append("```")
    out.append("")
    out.append("| 桶 | 数量 | 期望 | 说明 |")
    out.append("|---|---|---|---|")
    out.append("| SKIP_A | %d | 4 | 路径/文件名小写含 license/licence/notices/credits/copying |" % counts["SKIP_A"])
    out.append("| SKIP_B | %d | 47 | `crates/rustcode-review/rules/*.md`（运行时载荷，Q1 不动） |" % counts["SKIP_B"])
    out.append("| SKIP_C | %d | 1 | `extensions/jetbrains/CHANGELOG.md`（逐字历史） |" % counts["SKIP_C"])
    out.append(
        "| SKIP_D | %d | 2 | 运行时 prompt 载荷（`evals/deepseek-v4-flash/prompts/codex-{judge,report}.md`）；与 SKIP_B 同源，汉化会改变评测语义与输出解析，不汉化 |"
        % counts["SKIP_D"]
    )
    out.append("| TODO=EN | %d | - | ratio == 0，待汉化 |" % counts["EN"])
    out.append("| TODO=MIXED | %d | - | 0 < ratio < 0.5，待汉化 |" % counts["MIXED"])
    out.append("| ZH | %d | - | ratio >= 0.5，已中文（含 OWNED_ELSEWHERE） |" % zh)
    out.append("")
    out.append("> ratio = 含 CJK 行数 / max(含 ASCII 字母行数, 1)")
    out.append("")

    sections = [
        ("SKIP_A", "A 类 · 法律/声明文本（跳过）"),
        ("SKIP_B", "B 类 · review rules（跳过）"),
        ("SKIP_C", "C 类 · 逐字历史（跳过）"),
        ("SKIP_D", "D 类 · 运行时 prompt 载荷（跳过）"),
        ("EN", "待汉化 · EN（ratio == 0）"),
        ("MIXED", "待汉化 · MIXED（0 < ratio < 0.5）"),
        ("ZH", "已中文 · ZH（ratio >= 0.5）"),
    ]
    for bucket, title in sections:
        bucket_entries = [e for e in entries if e["bucket"] == bucket]
        out.append("## %s（%d）" % (title, len(bucket_entries)))
        out.append("")
        if not bucket_entries:
            out.append("（空）")
            out.append("")
            continue
        out.append("| 路径 | Han 行 | 字母行 | ratio | 备注 |")
        out.append("|---|---|---|---|---|")
        for entry in sorted(bucket_entries, key=lambda e: e["path"]):
            note = "OWNED_ELSEWHERE（owner 非 doc-writer）" if entry["owned_elsewhere"] else ""
            out.append(
                "| `%s` | %d | %d | %.3f | %s |"
                % (entry["path"], entry["han"], entry["letter"], entry["ratio"], note)
            )
        out.append("")
    return "\n".join(out), counts, identity_ok


def cmd_inventory(args):
    root = find_root()
    files = list_md_files(root)
    entries = build_inventory(root, files)
    text, counts, identity_ok = render_inventory(args.base, entries)

    if args.out:
        write_report(args.out, text)
        print("inventory: 已写入 %s" % args.out)
    else:
        print(text)

    print(
        "inventory: total=%d SKIP_A=%d SKIP_B=%d SKIP_C=%d SKIP_D=%d TODO(EN=%d,MIXED=%d) ZH=%d 恒等式=%s"
        % (
            len(entries),
            counts["SKIP_A"],
            counts["SKIP_B"],
            counts["SKIP_C"],
            counts["SKIP_D"],
            counts["EN"],
            counts["MIXED"],
            counts["ZH"],
            "OK" if identity_ok else "BROKEN",
        )
    )
    ok = (
        identity_ok
        and counts["SKIP_A"] == 4
        and counts["SKIP_B"] == 47
        and counts["SKIP_C"] == 1
        and counts["SKIP_D"] == 2
    )
    return 0 if ok else 1


# ---------------------------------------------------------------------- check


def resolve_files(root, base, args):
    # 显式 --files 优先且**不受 artifacts 豁免域影响**：用户手工点名某个交接件时仍要出结果
    # （豁免只作用于「批量候选」，不改变显式指定的语义）。
    if args.files:
        return list(args.files)
    files = []
    seen = set()
    for path in git_lines(["diff", "--name-only", base, "--", "*.md"], root):
        if path not in seen:
            seen.add(path)
            files.append(path)
    for path in git_lines(["ls-files", "--others", "--exclude-standard", "--", "*.md"], root):
        if path not in seen:
            seen.add(path)
            files.append(path)
    # 批量候选与 AC-1 分母同一豁免域（T-16）：提交前后 `check --diff` 的受检集不变。
    return sorted(
        path
        for path in files
        if os.path.isfile(os.path.join(root, path)) and not is_artifacts_exempt(path)
    )


def cmd_check(args):
    root = find_root()
    files = resolve_files(root, args.base, args)
    if not files:
        raise EnvError("没有待检文件（--files 为空或 --diff 无改动）")

    results = []
    r5_all = []
    for path in files:
        result = check_file(root, args.base, path, args.en_ratio)
        results.append(result)
        for lineno, raw in result.r5_skipped:
            r5_all.append((path, lineno, raw))
        print_check_result(result)

    failed = [r for r in results if not r.ok]
    print("")
    print("check: 受检 %d，PASS %d，FAIL %d" % (len(results), len(results) - len(failed), len(failed)))

    if args.report:
        write_report(args.report, render_check_report(args.base, results, args.en_ratio, r5_all))
        print("check: 报告已写入 %s" % args.report)

    return 0 if not failed else 1


# ------------------------------------------------------------------- hostscan


def scan_host_line(raw, inside_fence):
    """返回 True 表示该行是"默认绑定"语义的命中行。

    T-06 规则：作为 IP 字面量出现的 `127.0.0.1`（显式 `--host 127.0.0.1`）**保留**，
    只列"默认值 = 127.0.0.1"这类叙述。判别标准是语义，不是"是否位于 inline code 内"：
    文档惯例把 IP 写成 `` `127.0.0.1` ``，若沿用 AC-2 的做法先把 inline code mask 掉再搜
    字面量，命中数会恒为 0（hostscan 曾因此输出空清单，导致 T-06 退化为无文件可改）。
    """
    if inside_fence:
        return False
    eff = _strip_blockquote(raw)
    if _is_fence(raw):
        return False
    if _is_indented(eff):
        return False
    if not HOST_LITERAL_RE.search(eff):
        return False
    if not HOST_DEFAULT_RE.search(eff):
        return False
    if HOST_EXCLUDE_RE.search(eff):
        return False
    return True


def cmd_hostscan(args):
    """清单产出器（供 T-06 取 files_owned），**不是门禁**：无论命中多少恒返回 0。

    CI 需要卡口请用 `gate`；本子命令的返回码不携带通过/失败语义。
    """
    root = find_root()
    files = list_md_files(root)
    hits = {}
    for path in files:
        lower = path.lower()
        if any(key in lower for key in SKIP_A_LICENSE):
            continue
        if path.startswith(SKIP_B_RULES) or path in SKIP_C_VERBATIM:
            continue
        if is_owned_elsewhere(path):
            continue
        text = read_work_file(root, path)
        source = "worktree"
        if text is None:
            text = read_base_file(root, args.base, path)
            source = "base"
        if text is None:
            continue
        body, fm = split_frontmatter(text)
        offset = len(fm)
        inside = False
        for idx, raw in enumerate(body.split("\n")):
            if _is_fence(raw):
                inside = not inside
                continue
            if scan_host_line(raw, inside):
                hits.setdefault(path, {"source": source, "lines": []})["lines"].append(
                    (offset + idx + 1, raw.rstrip())
                )
        _ = lower

    paths = sorted(hits)
    print("hostscan: base=%s 命中 %d 个文件（内容来源：工作区优先，缺失时回退基线）" % (args.base, len(paths)))
    print("")
    print("## 命中文件（供 T-06 的 files_owned；T-06 需自行排除 README.md）")
    print("")
    for path in paths:
        print(path)
    print("")
    print("## 明细")
    print("")
    for path in paths:
        for lineno, raw in hits[path]["lines"]:
            print("%s:%d: %s" % (path, lineno, raw))
    print("")
    print("hostscan: 命中文件 %d，命中行 %d" % (len(paths), sum(len(v["lines"]) for v in hits.values())))
    return 0


# ----------------------------------------------------------------------- gate


def gate_check_ac1(root, base, entries):
    counts = inventory_counts(entries)
    total = len(entries)
    skip = counts["SKIP_A"] + counts["SKIP_B"] + counts["SKIP_C"] + counts["SKIP_D"]
    todo = counts["EN"] + counts["MIXED"]
    zh = counts["ZH"]
    detail = []
    ok = True
    if skip + todo + zh != total:
        ok = False
        detail.append("恒等式不成立: %d + %d + %d = %d != %d" % (skip, todo, zh, skip + todo + zh, total))
    for bucket, expected in (("SKIP_A", 4), ("SKIP_B", 47), ("SKIP_C", 1), ("SKIP_D", 2)):
        if counts[bucket] != expected:
            ok = False
            detail.append("%s = %d，期望 %d" % (bucket, counts[bucket], expected))
    if not detail:
        detail.append(
            "SKIP_A=%d SKIP_B=%d SKIP_C=%d SKIP_D=%d TODO=%d ZH=%d total=%d"
            % (
                counts["SKIP_A"],
                counts["SKIP_B"],
                counts["SKIP_C"],
                counts["SKIP_D"],
                todo,
                zh,
                total,
            )
        )
    return ok, detail


def gate_check_ac5(root, base):
    detail = []
    ok = True

    rc, out, _err = _git(["diff", "--name-only", base, "--", "crates/rustcode-review/rules/"], root)
    if rc != 0:
        return False, ["AC-5a git diff 失败"]
    changed = [ln for ln in out.split("\n") if ln.strip()]
    if changed:
        ok = False
        detail.append("AC-5a rules 目录有改动: %s" % ", ".join(changed[:10]))
    else:
        detail.append("AC-5a rules 目录无改动: OK")

    rc, out, _err = _git(
        ["diff", "--name-only", base, "--", "crates/rustcode-capabilities/assets/setup-seeds/"], root
    )
    if rc != 0:
        return False, ["AC-5b git diff 失败"]
    changed = [ln for ln in out.split("\n") if ln.strip()]
    if not changed:
        ok = False
        detail.append("AC-5b setup-seeds 无改动（期望非空）")
    else:
        detail.append("AC-5b setup-seeds 有改动 (%d 个文件): OK" % len(changed))

    rc, out, _err = _git(
        ["diff", "-U0", base, "--", "crates/rustcode-capabilities/assets/setup-seeds/"], root
    )
    if rc != 0:
        return False, ["AC-5b git diff -U0 失败"]
    name_lines = [ln for ln in out.split("\n") if re.match(r"^[+-]name:", ln)]
    if name_lines:
        ok = False
        detail.append("AC-5b 出现 name: 行变更: %s" % name_lines[:5])
    else:
        detail.append("AC-5b 无 ^[+-]name: 变更: OK")
    return ok, detail


def gate_check_ac7a(root, base):
    """无 md 被重命名/删除（README.zh-CN.md 与 A/C 类除外）。"""
    rc, out, _err = _git(["diff", "--name-status", base, "--", "*.md"], root)
    if rc != 0:
        return False, ["AC-7a git diff --name-status 失败"]
    bad = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]
        if status.startswith("D") or status.startswith("R"):
            if path == "README.zh-CN.md":
                continue
            lowered = path.lower()
            if any(key in lowered for key in SKIP_A_LICENSE):
                continue
            if path.startswith(SKIP_B_RULES) or path in SKIP_C_VERBATIM:
                continue
            bad.append(line.strip())
    if bad:
        return False, ["AC-7a 存在删除/重命名: %s" % "; ".join(bad[:10])]
    return True, ["AC-7a 无 md 删除/重命名（README.zh-CN.md 与 A/C 类除外）: OK"]


def ac8_candidates(root):
    """AC-8 段 1/段 2 的公共候选集（补遗 §3.1）：git ls-files 按 AC8_GLOBS 取已跟踪文件。

    返回 (formal, historical)：historical = 路径以 AC8_EXEMPT_PREFIX 开头的候选，
    formal = 其余候选。AC8_EXEMPT_PREFIX 在本脚本中只有这一处「过滤使用」（A4）；
    段 1/段 2 之外不存在任何其它目录级排除。
    """
    paths = git_lines(["ls-files", "--"] + list(AC8_GLOBS), root)
    formal = [p for p in paths if not p.startswith(AC8_EXEMPT_PREFIX)]
    historical = [p for p in paths if p.startswith(AC8_EXEMPT_PREFIX)]
    return formal, historical


def git_grep_fixed(root, needle, paths, chunk=500):
    """对给定路径集做固定串 grep，返回命中行 ['<path>:<lineno>:<line>', ...]。

    采用「git ls-files 取候选 -> Python 过滤 -> 对剩余路径 grep」的推荐形式（补遗 §3.2），
    不使用 pathspec magic；固定串用 -F，避免转义差异。
    路径数 <= 1000 时单次调用，超过则分片每片 <= 500。
    rc not in (0, 1) -> EnvError（映射到退出码 2），绝不当作 PASS。
    """
    if not paths:
        return []
    size = len(paths) if len(paths) <= 1000 else chunk
    hits = []
    for start in range(0, len(paths), size):
        part = paths[start : start + size]
        rc, out, err = _git(["grep", "-n", "-F", needle, "--"] + part, root)
        if rc not in (0, 1):
            raise EnvError("git grep 失败 (rc=%d): %s" % (rc, err.strip()))
        if rc == 0:
            hits.extend(ln for ln in out.split("\n") if ln.strip())
    return hits


def gate_check_ac8(root):
    """AC-8 v2（补遗 §3）：三段都必须执行，任一段不满足即 FAIL。

    段 1 正式域 —— 候选集减去 AC8_EXEMPT_PREFIX，要求 0 命中
    段 2 历史域 —— 豁免前缀内，反向断言「必须仍有命中」（探测器：捕获清理历史件来修绿）
    段 3 兜底域 —— site/ .github/ docs/ extensions/ 全扩展名，0 命中（与既有第二次 grep 同义）
    护栏 A1 正式域非空 / A2 锚点存在 / A3 历史域命中 >=1 / A4 排除集不外溢
    """
    detail = []
    ok = True

    formal, historical = ac8_candidates(root)

    # A1 非空：防排除集被写成 "." 让检查空转
    if not formal:
        return False, ["AC-8 A1 断言失败：正式域候选集为空（排除集被过度放大，检查将空转）"]
    # A2 锚点存在：防误排除（README.md / AGENTS.md 必须真的被扫到）
    #
    # 前置：AC8_EXEMPT_PREFIX 必须是「至少一个路径段、以 / 结尾」的相对目录前缀。
    # 补遗 §3.3 A1/A2 的立法意图是「防排除集被写成 '.' 让检查空转」，但 git ls-files 输出的
    # 是仓库相对路径（无前导 './'），单靠「锚点是否留在正式域」拦不住 '.' —— '.' 只会吞掉
    # 点开头的目录（.github/ .codebuddy/ ...），锚点仍在正式域内，段 1 反而会假绿。
    # 故在此附加「非退化前缀」前置条件（只拒绝非法的常量取值，不新增任何排除、不影响任何
    # 正式文档判定）；常量冻结为 '.codebuddy/artifacts/' 时该断言恒成立。
    degenerate = (not AC8_EXEMPT_PREFIX.endswith("/")) or posixpath.normpath(
        AC8_EXEMPT_PREFIX
    ) in (".", "/", "")
    if degenerate:
        return False, [
            "AC-8 A2 断言失败：AC8_EXEMPT_PREFIX=%r 是退化前缀（'.'/'/'/缺尾斜杠），"
            "排除集退化为根目录或外溢到同级路径，锚点护栏失效" % (AC8_EXEMPT_PREFIX,)
        ]
    missing = [p for p in AC8_ANCHOR_FILES if p not in formal]
    if missing:
        return False, ["AC-8 A2 断言失败：锚点文件未进入正式域候选集: %s" % ", ".join(missing)]

    # 段 1 正式域：0 命中
    hits = git_grep_fixed(root, AC8_NEEDLE, formal)
    if hits:
        ok = False
        detail.append(
            "段 1 正式域（候选 %d，已排除 %s）：命中 %d 处 -> FAIL，示例: %s"
            % (len(formal), AC8_EXEMPT_PREFIX, len(hits), hits[:5])
        )
    else:
        detail.append(
            "段 1 正式域（候选 %d，已排除 %s）：0 命中 -> OK" % (len(formal), AC8_EXEMPT_PREFIX)
        )

    # 段 2 历史域：反向断言必须仍有命中（A3），且命中不越界（A4）
    hist_hits = git_grep_fixed(root, AC8_NEEDLE, historical)
    if not hist_hits:
        ok = False
        detail.append(
            "段 2 历史域（候选 %d，前缀 %s）：0 命中 -> FAIL；历史交接件中的 `%s` 记录消失：违反历史不可篡改"
            % (len(historical), AC8_EXEMPT_PREFIX, AC8_NEEDLE)
        )
    else:
        stray = [h for h in hist_hits if not h.split(":", 1)[0].startswith(AC8_EXEMPT_PREFIX)]
        if stray:
            ok = False
            detail.append(
                "段 2 历史域：A4 断言失败，出现豁免前缀之外的命中行: %s" % (stray[:5],)
            )
        else:
            detail.append(
                "段 2 历史域（候选 %d）：命中 %d 处，全部位于 %s -> OK（历史痕迹仍在）"
                % (len(historical), len(hist_hits), AC8_EXEMPT_PREFIX)
            )

    # 段 3 兜底域：目录存在才扫，不限扩展名，要求 0 命中
    scopes = [d for d in AC8_FALLBACK_SCOPES if os.path.isdir(os.path.join(root, d))]
    if scopes:
        scope_hits = git_grep_fixed(root, AC8_NEEDLE, scopes)
        if scope_hits:
            ok = False
            detail.append(
                "段 3 兜底域 %s：命中 %d 处 -> FAIL，示例: %s"
                % ("/".join(scopes), len(scope_hits), scope_hits[:5])
            )
        else:
            detail.append("段 3 兜底域 %s（全扩展名）：0 命中 -> OK" % "/".join(scopes))
    else:
        detail.append("段 3 兜底域跳过（site/.github/docs/extensions 均不存在）")
    return ok, detail


def cmd_gate(args):
    root = find_root()
    files = list_md_files(root)
    # 可见性提示（MINOR-5）：`list_md_files()` 只含**已跟踪** md，而 `check --diff`
    # 经 `resolve_files()` 额外并入未跟踪 md。故新建且未 `git add` 的 md 不进本门禁的
    # 分母，不受 AC-1 恒等式与 AC-2/4/6/7b/32、AC-8 段 1 约束。判据与分母**刻意不改**
    # （未跟踪文件没有基线可比，并入会因「新文件无基线」大面积假 FAIL），仅打印提示，
    # 退出码语义不变。
    untracked = [
        p
        for p in git_lines(["ls-files", "--others", "--exclude-standard", "--", "*.md"], root)
        if os.path.isfile(os.path.join(root, p)) and not is_artifacts_exempt(p)
    ]
    # artifacts 豁免域（T-16）：与 SKIP_A..SKIP_D 同级的显式豁免域，按路径前缀判定，
    # 与是否已跟踪 / 基线无关，故 `git add` 前后分母一致。
    exempt = [p for p in git_lines(["ls-files", "--", "*.md"], root) if is_artifacts_exempt(p)]
    if untracked:
        print("gate: 未跟踪 md 已排除：%d 个（不进 AC-1 分母，也不受 AC-2/4/6/7b/32 与 AC-8 段 1 约束）" % len(untracked))
        for p in untracked[:5]:
            print("  - %s" % p)
        if len(untracked) > 5:
            print("  - ... 其余 %d 个未列出" % (len(untracked) - 5))
        print("")
    if exempt:
        print(
            "gate: artifacts 豁免域 `%s` 已排除：%d 个（与 SKIP_A..SKIP_D 同级，按路径前缀判定、与基线无关；"
            "不进 AC-1 分母，也不受 AC-2/4/6/7b/32 与 AC-8 段 1 约束；域内文件仍是 AC-8 段 2 的历史域）"
            % (ARTIFACTS_EXEMPT_PREFIX, len(exempt))
        )
        print("")
    entries = build_inventory(root, files)
    targets = [e["path"] for e in entries if e["bucket"] not in SKIP_BUCKETS]

    sections = []
    all_ok = True

    ok, detail = gate_check_ac1(root, args.base, entries)
    all_ok = all_ok and ok
    sections.append(("AC-1 清单自洽", ok, detail))

    results = []
    r5_all = []
    for path in targets:
        result = check_file(root, args.base, path, args.en_ratio)
        results.append(result)
        for lineno, raw in result.r5_skipped:
            r5_all.append((path, lineno, raw))
    failed = [r for r in results if not r.ok]
    ac2_detail = ["全量 check 受检 %d，FAIL %d" % (len(results), len(failed))]
    for result in failed:
        acs = ",".join(sorted({ac for ac, _d in result.failures}))
        ac2_detail.append(
            "  FAIL %s [%s] en=%d/%d=%.4f" % (result.path, acs, result.en, result.total, result.ratio)
        )
    # AC-4 授权放行汇总（补遗 §2.7）：只统计 AC-4 未 FAIL 的文件的放行明细 ——
    # 已 FAIL 的文件其放行未生效，计入会虚报"已授权"。
    released = [item for r in results if not any(ac == "AC-4" for ac, _d in r.failures) for item in r.authorized]
    d1 = len([i for i in released if i[3] == "D1"])
    d2 = len([i for i in released if i[3] == "D2"])
    ac2_detail.append("AC-4 授权放行合计 %d 条（D1 %d / D2 %d）" % (len(released), d1, d2))
    for auth_path, removed_span, added_span, cause in released:
        ac2_detail.append(
            "  %s | removed=%s | added=%s | cause=%s" % (auth_path, removed_span, added_span, cause)
        )
    all_ok = all_ok and not failed
    sections.append(("AC-2/3/4/6/7b/32 全量 check", not failed, ac2_detail))

    ok, detail = gate_check_ac5(root, args.base)
    all_ok = all_ok and ok
    sections.append(("AC-5 运行时载荷", ok, detail))

    ok, detail = gate_check_ac7a(root, args.base)
    all_ok = all_ok and ok
    sections.append(("AC-7a 无改名/删除", ok, detail))

    ok, detail = gate_check_ac8(root)
    all_ok = all_ok and ok
    sections.append(("AC-8 外链残留", ok, detail))

    print("gate: base=%s" % args.base)
    print("")
    for title, ok, detail in sections:
        print("%s %s" % ("PASS" if ok else "FAIL", title))
        for line in detail:
            print("  %s" % line)
    print("")
    print("--- 附录 · 被 R5 跳过的行（供抽检，共 %d 行）---" % len(r5_all))
    for path, lineno, raw in r5_all[:STDOUT_R5_LIMIT]:
        print("  %s:%d: %s" % (path, lineno, raw.rstrip()))
    if len(r5_all) > STDOUT_R5_LIMIT:
        print("  ... 其余 %d 行见 --report" % (len(r5_all) - STDOUT_R5_LIMIT))
    print("")
    print("gate: %s" % ("PASS" if all_ok else "FAIL"))

    if args.report:
        report_lines = ["# gate 报告", "", "- 基线 (--base): `%s`" % args.base, ""]
        for title, ok, detail in sections:
            report_lines.append("## %s %s" % ("PASS" if ok else "FAIL", title))
            report_lines.append("")
            for line in detail:
                report_lines.append("- `%s`" % line.replace("`", "'"))
            report_lines.append("")
        report_lines.append("## 附录 · 被 R5 跳过的行（供抽检）")
        report_lines.append("")
        report_lines.append("共 %d 行。" % len(r5_all))
        report_lines.append("")
        for path, lineno, raw in r5_all:
            report_lines.append("- `%s:%d`: `%s`" % (path, lineno, raw.rstrip().replace("`", "'")))
        report_lines.append("")
        report_lines.append(render_check_report(args.base, results, args.en_ratio, []))
        write_report(args.report, "\n".join(report_lines))
        print("gate: 报告已写入 %s" % args.report)

    return 0 if all_ok else 1


# ----------------------------------------------------------------------- main


def build_parser():
    parser = argparse.ArgumentParser(
        prog="check-zh-docs.py",
        description="RustCode 中文文档验收脚本（stdlib only）",
    )
    sub = parser.add_subparsers(dest="subcommand")

    p_inv = sub.add_parser("inventory", help="产出 md 清单（AC-1）")
    p_inv.add_argument("--base", default=None)
    p_inv.add_argument("--out", default=None)
    p_inv.set_defaults(func=cmd_inventory)

    p_check = sub.add_parser("check", help="逐文件双轨比较（AC-2/4/6/7b/32）")
    p_check.add_argument("--base", default=None)
    p_check.add_argument("--files", nargs="+", default=None)
    p_check.add_argument("--diff", action="store_true")
    p_check.add_argument("--report", default=None)
    p_check.add_argument("--en-ratio", type=float, default=None)
    p_check.set_defaults(func=cmd_check)

    p_host = sub.add_parser(
        "hostscan",
        help="列出默认绑定语义的 127.0.0.1/localhost 叙述（清单产出器，非门禁，恒返回 0）",
    )
    p_host.add_argument("--base", default=None)
    p_host.set_defaults(func=cmd_hostscan)

    p_gate = sub.add_parser("gate", help="集成门禁（AC-1/2/3/4/5/6/7/8/32）")
    p_gate.add_argument("--base", default=None)
    p_gate.add_argument("--report", default=None)
    p_gate.add_argument("--en-ratio", type=float, default=None)
    p_gate.set_defaults(func=cmd_gate)

    return parser


def resolve_base(value):
    """基线解析顺序：显式 --base > 环境变量 ZH_BASE > 常量 DEFAULT_BASE。禁止回落到 HEAD。"""
    if value:
        return value
    env = os.environ.get("ZH_BASE")
    if env:
        return env
    return DEFAULT_BASE


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "subcommand", None):
        parser.print_help()
        return 2

    args.base = resolve_base(args.base)
    # 判空必须显式用 `is None`：`--en-ratio 0` 会被 argparse 存成 0.0，而
    # `not 0.0` 为真，旧写法会把它静默放宽成 EN_RATIO_DEFAULT(0.05) —— 与
    # fail-closed 方向相反（用户要求最严阈值，实际却更松）。
    if getattr(args, "en_ratio", None) is None:
        args.en_ratio = EN_RATIO_DEFAULT

    if args.subcommand == "check" and not args.files and not args.diff:
        print("check: 必须指定 --files P... 或 --diff", file=sys.stderr)
        return 2
    if args.subcommand == "check" and args.files and args.diff:
        print("check: --files 与 --diff 互斥", file=sys.stderr)
        return 2

    try:
        # 先校验 base 再消耗它：非法 base 必须以退出码 2 报环境错误，而不是退化成
        # 「基线无此文件」刷出几百条假 FAIL（NIT-2）。
        verify_base_commit(find_root(), args.base)
        if args.en_ratio < 0:
            raise EnvError(
                "--en-ratio 必须 >= 0（0 表示不允许任何纯英文行）；实际取值 %s" % args.en_ratio
            )
        return args.func(args)
    except EnvError as exc:
        print("错误: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
