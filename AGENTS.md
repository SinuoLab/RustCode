# RustCode 开发约束 (面向 Agent)

本文件是二次开发 fork 的长期约束与高信号上下文。历史方案、旧基线和上游 core 退役过程留在 `docs/`。

**维护规则(强制):文件内容变更时同步更新,不得滞后。** 项目结构、构建/测试/检查命令、架构边界、开发约定或本文件记录的任何事实发生变化时,**必须在同一次改动里同步改本文件**,不得留待后续轮次。本文件同时是 AI 代理的加载入口(仓库内无 `.rustcode.md` / `CLAUDE.md`),改动即生效。

**现状以本文件前半部分的活章节为准**:`常用命令` / `环境约束与已知坑` / `分支策略` / `架构总览` / `架构方向` / `Runtime 生命周期不变量` / `编码约束` / `门禁`。下方「已知剩余项」是按时间倒序的沿革流水,**其中的结论会被更晚的轮次推翻**——凡是标注 `[SUPERSEDED]`、`[已过期]`、`[CORRECTION]` 的条目,或与代码/实测冲突的条目,一律以代码与实测为准,不要据其行动。

`rustcode` 在本文件与 `docs/architecture.md` 中均为**历史名引用**,不代表现役 crate。现役 crate 一律 `rustcode-*`。

## 新参与者速查 (先看这几处入口)

| 想改什么 | 落点 |
|---------|------|
| CLI 子命令 / 参数 / help 文案 | `crates/rustcode-cli/src/main.rs`(包名 `rustcode`) |
| TUI 命令、渲染、模态 | `crates/rustcode-tuix/src/`(`event_loop/`、`render/`、`modals/`) |
| 守护进程 / HTTP API / WebUI 后端 | `crates/rustcode-daemon/src/{main.rs,lib.rs,live_api.rs}` |
| agent 运行时生命周期 | `crates/rustcode-coding/src/runtime.rs`(`CodingRuntime`,唯一 owner) |
| 中立 agent 循环(**零文案**) | `crates/rustcode-kernel/src/agent.rs` |
| 出站 HTTP 唯一工厂 | `crates/rustcode-capabilities/src/egress/client.rs` |
| 目录名 / 环境变量前缀 / 端口 | `crates/rustcode-config/src/distribution.rs` |
| 托管端点 / `RUSTCODE_*` 变量名 | `crates/rustcode-config/src/endpoints.rs` |
| 用户可见文案 | `crates/rustcode-config/src/i18n/{messages,en,zh_cn}.rs` |
| kernel 结构化事件的本地化单点 | `crates/rustcode-coding/src/controllers.rs`(`retry_reason_label` / `localize_agent_notice` / `localize_kernel_event`) |
| 调度求值(`next_run`)、运行台账与 tick 原语 | `crates/rustcode-config/src/schedule.rs`(cron 手写五段 + weekly weekday 对齐 + `RunRecord`/`runs/` 台账 + `due_tasks`/`try_claim_run`/补跑窗口) |
| 模型回退判定单点 | `crates/rustcode-capabilities/src/fallback.rs`(`fallback_eligible*`)+ `crates/rustcode-coding/src/fallback.rs`(`FallbackWalk`) |
| 独立评审 CLI / `rustcodex` | `crates/rustcode-clix/src/`、`crates/rustcode-review/` |
| 反向隧道中继 | `crates/rustcode-tunnel/`(bin `rustcode-relay`) |
| IM 渠道接入(钉钉 Stream 等) | `crates/rustcode-cli/src/im/`、`crates/rustcode-cli/src/im_runner.rs`、`crates/rustcode-capabilities/src/im_probe.rs` |

## 仓库结构与工具链事实

顶层目录:`crates/`(12 个成员 crate,`rustcode-wiki` 在列)、`webui/`(Preact 前端,`npm ci && npm run build` 产出 gitignored 的 `webui/dist/`)、`site/`(静态文档站,索引由 `cd site && node build-search-index.mjs` 重生成,勿手改 JSON)、`extensions/`(VS Code / JetBrains 插件)、`scripts/`(**32 个**脚本 + `__pycache__`;**无** Makefile/justfile/Taskfile,不要去找)、`release/`(已提交的发布产物兜底源)、`docker/`、`packages/`(npm / homebrew 打包)、`examples/`、`docs/`、`evals/`(headless 配对评测,`evals/deepseek-v4-flash/` 含 `eval.py`/`benchmark.json`)。`Knowledge/` 是空目录且**未纳入 git**,勿依赖其内容;`target/`、`dist/` 为构建产物(gitignored)。

根文件:`Cargo.toml`(workspace `version = "6.2.3"`)、`Cargo.lock`、`CONTEXT.md`(运行时术语)、`DEVENV.md`、`latest.json`(自更新 manifest,由 `scripts/release-publish.sh` 每次发布时随 `release/<v>/manifest.json` 与 `release/index.json` 同批刷新——2026-10-15 前只由全矩阵 `scripts/release.sh` 生成,而该脚本在 Linux 上跑不完,故长期冻结,已修)、`.mcp.json.example`。

工具链:全仓 `edition = "2021"` + `resolver = "2"`;**无** `rust-toolchain` 文件,也**无** `rust-version` / MSRV 约束——不要臆断或新增版本钉。`.cargo/config.toml` 只做交叉构建底座:两个 musl target(`x86_64-`/`aarch64-unknown-linux-musl`)配各自 `*-linux-musl-gcc` linker,两个 windows-msvc target 配 `crt-static`;无其它全局配置。WebUI 需 Node `>= 22.6`(`webui/package.json` 的 engines,`scripts/build-webui.sh` 会 fail-closed 前置检查)。

## 常用命令

构建:
- `cargo build` — 构建 `default-members`(`rustcode-cli` / `rustcode-daemon` / `rustcode-tuix` / `rustcode-tunnel`),产物 `target/debug/rustcode`。
- `cargo build --release -p rustcode` — 只构建发布版 CLI。`rustcode-cli` 的**包名是 `rustcode`**(`-p rustcode-cli` 会失败),产物 `target/release/rustcode`。
- `cargo build --workspace` — 构建全部 `crates/*`(含默认成员外的 `clix`、`review`;原并列于此的 `codingplan` 已于 2026-09-09 按用户裁决 Q1=B 整体移除)。
- `cargo install --path crates/rustcode-cli --locked` — 安装到 `~/.cargo/bin`。
- WebUI 需先构建前端:`cd webui && npm ci && npm run build` 产出 `webui/dist/`(gitignored)。重建前端后必须 `cargo clean -p rustcode-daemon`,cargo 不追踪 `webui/dist/` 变化;缺失时所有 webui 页面返回 `webui not built`。
  - 前端校验三件套:`npm run typecheck`(`tsc --noEmit`)、`npm test`(`node --experimental-strip-types --test "src/**/*.test.ts"`)、`npm run build`。**需 Node >= 22.6**(`package.json` `engines`)。
  - 非 React 模块之间做值导入**必须带 `.ts` 扩展名**(如 `import { translate } from '../i18n.ts'`)——node 的 strip-types 无打包器解析,tsconfig 已开 `allowImportingTsExtensions`。`import type` 不受影响。
  - 断言英文镜像文案的前端测试要在 stub localStorage 里 `setItem(LANG_STORAGE_KEY,'en')` 钉死语言(无 storage 时 `translate` 回落 zh)。
- scripts/build-webui.sh —— WebUI 前端一键构建(等价 cd webui && npm ci && npm run build,可重复执行)。--if-missing 仅在 webui/dist/index.html 不存在时才构建(已存在则跳过并 exit 0);成功结尾会主动打印上一条要求的 cargo clean -p rustcode-daemon。前置检查 fail-closed:缺 node / 缺 npm / 缺 webui/package-lock.json / node 版本低于 webui/package.json 的 engines.node 时,打印可执行的修复指引并 exit 2;npm ci 或 npm run build 失败 exit 1;构建命令返回 0 但 dist/index.html 仍缺失(半产出)同样判失败。环境不足时绝不降级为警告继续。
- 发布打包:`scripts/release*.sh`、`scripts/macOS-release-*.sh`、`scripts/linux-release-*.sh`、`scripts/sign-macos.sh`;矩阵见 `.github/workflows/build.yml`。
- **仓库内发布兜底目录 `release/`(新增,与流水线解耦)**:每个成功构建的完整版本提交为 `release/<version>/`(如 `release/v5.1.0/`),目录**只按版本区分,不在层级上拆分 OS/ARCH**——OS/ARCH 由文件名 `rustcode-<version>-<os>-<arch>[.exe]` 体现(沿用既有命名)。发布脚本在构建成功后统一调用 `scripts/release-publish.sh` 把 `dist/<version>/` 里**已验证通过**的二进制原子合并进 `release/<version>/`(先写入 `release/.tmp/<version>` 再 rename,绝不删除已提交的其它平台二进制,故流水线/单机部分失败不会破坏既有成功版本),并生成 `release/<version>/manifest.json`、顶层 `release/index.json`(版本降序 + 每版本 targets 清单)与根 `latest.json`。**只有目录内确实存在 `rustcode-*` 二进制的版本才会进 `index.json`**——只带 `manifest.json` 的目录被排除(否则 `install.sh` 会为它造出一堆必然 404 的 raw 回退 URL;实测 `release/v5.1.0` 即此种幽灵条目,已随此规则出列)。
  - **两份清单语义不同,不要互相校准**:`release/<v>/manifest.json` + `release/index.json` 描述的是**仓库 raw 兜底源**,只列真正入库的二进制(v6.2.3 入库 linux-arm64 / linux-x64 / windows-x64 三个,约 137 MB;darwin/freebsd 走在线 Release + `install.sh` 内置的 GitHub mirror);根 `latest.json` 描述的是**在线可下载的最新版**,可含在线已发布但仓库未入库的平台(v6.2.3 为 8 个)。因此裁剪入库集合或补发旧版本时,发布必须带 `RUSTCODE_PUBLISH_NO_LATEST=1`,否则 `latest.json` 会被削回入库集合。开发者主机手动跑发布脚本即会填充 `release/` 并提交,作为 `install.sh` / `install.ps1` 的**二级回退源**(一级为 GitCode 在线 Release,二级为 `release/` 的 raw 文件 URL)。下载脚本多级回退顺序:在线 Release → `release/` 同版本 → `release/` 更旧版本(按 `index.json` 降序)→ 明确报错(并列出 OS/ARCH、试过的版本与来源)。
- **版本探测:两个来源都是候选,不是权威**(2026-09-27 修复的实测 bug):远端 `releases/latest` API 会**滞后**于仓库——实测它回答 `v6.1.0` 而仓库 `release/index.json` 已含 `v6.2.0`(因为 v6.2.0 的在线 Release 当时还不存在,该 URL 是 404)。旧代码把 API 结果**无条件插到候选首位**,于是"最新版"实际装成旧版。现两个来源合并去重后**统一按语义版本号降序**(自写 `sort_versions_desc`:零填充数值字段 + `sort -r`,刻意不用 GNU-only 的 `sort -V`),最高版本胜出且不论谁报的;两源不一致时额外打印一行 `==> Note: latest-version API reports X, repo index has Y; installing Y`。`RUSTCODE_VERSION` 钉版本路径不受影响。另注意 `latest.json`(客户端自更新 manifest)的生成方:2026-10-15 前**只有**全矩阵 `scripts/release.sh` 写它,而该脚本在 Linux 主机上跑不完(macOS 交叉步骤失败),导致 `latest.json` 长期停在旧版本、与在线 Release 已发布的版本脱节——`/upgrade` 因此会提供一个在线 Release 里根本没有二进制的版本(v6.2.1 即此情况)。**已修**:`scripts/release-publish.sh` 每次发布都会用刚落地的二进制刷新 `latest.json`(`RUSTCODE_PUBLISH_NO_LATEST=1` 可在补发布旧版本时避免指针回退)。另有 `RUSTCODE_PUBLISH_SRC_SHA` 用于钉构建源 commit(在 detached worktree / CI 产物事后发布时,避免 manifest 谎称"构建自 HEAD")。
- `scripts/release-auto.sh` / `scripts/release-daemon.sh` — 2026-09-29 补上的**自动发版**入口(`dcd82994`),填补此前「没有 tag 生产者」的缺口:push 前后按 Cargo.toml 版本自动产出并提交 `release/<version>/`。与手工的 `release-host.sh`(本机单目标)、`release.sh`(全矩阵,macOS 交叉导向,Linux 上会失败)三者的取舍见各自脚本头注释。**仅在 dev 且自最新 tag 起有源码改动时才 bump patch**;**构建失败默认只警告不阻断 push**(2026-10-18 按用户裁决改,此前 fail-closed 会把每次 `git push origin dev` 卡在本机 cross-build 上——而 musl gcc 未进 PATH、v6.2.3 起产物本就由 GitHub runner 构建,本机构建几乎不可能成功)。失败时按提示 `bash scripts/release-auto.sh` 重跑即可;`RUSTCODE_AUTO_RELEASE_STRICT=1` 恢复阻断(给真的会构建的发版机/CI),`RUSTCODE_AUTO_RELEASE=off` 仍可整体跳过。构建失败同时会**回滚 Cargo.toml/Cargo.lock 到 bump 前**(`855cf3efc`),否则工作树会停在一个没有产物的版本号上,被指针门禁拒绝后续每一次 push。
- 下载源回退:`RUSTCODE_RELEASE_MIRRORS`(逗号/空格分隔,定义于 `crates/rustcode-config/src/endpoints.rs`,常量 `RELEASE_MIRRORS_ENV`)提供**镜像列表块**,在主下载源失败时按序回退(2026-09-29 `3900cb13`)。与 `RUSTCODE_RELEASE_BASE` 的关系:后者是单一必填基址,前者是可选的多镜像补充。
- `scripts/prepush-release-check.sh` — 推送前发布产物门禁(由 `.githooks/pre-push` 调用,CI `release-gate` job 复用同一判据);`--self-test` 跑内建回归;`--sha <sha>` / `--root <dir>` / `--target <os-arch|any>` 可覆盖,`RUSTCODE_PREPUSH_RELEASE=on|strict|off` 控制强度。产物门禁通过后**还会跑指针门禁**(见下条),`RUSTCODE_PREPUSH_POINTERS=off` 可单独关掉。
- `scripts/release-check-pointers.sh` — 版本指针一致性门禁(2026-10-15 新增):断言 `Cargo.toml` 版本、`release/index.json` 最高条目、根 `latest.json` 三者一致,且 index 声明的 targets 与各 `manifest.json` 的 binaries 键集完全相同、manifest 点名的每个二进制在树里真实存在(未提交的产物 = 必然 404 的回退 URL)。默认纯离线;`--online` 额外对账 GitCode releases API 中「确实带 attach 二进制」的最高版本。已接入 `prepush-release-check.sh` 与 CI `release-pointers` job(该 job 不像 `release-gate` 那样限定 canonical 仓库,故在 GitHub 镜像上也真跑)。
- **为既有版本补缺失 target 的产物(2026-09-27 实测流程)**:从该版本 `manifest.json` 的 `source.sha` 建 detached worktree 同源构建(`git worktree add --detach /tmp/<dir> <sha>`),worktree 内先跑 `build-webui.sh`(`webui/dist` 是 gitignored,**不能拷主工作区的 dist**——那会让前端比后端新),再交叉构建并用**同一提交版**的 `release-publish.sh` 发布;发布前先把该版本**已提交**的二进制复制进 worktree 的 `release/<v>/`(脚本重生成 manifest 时扫描全部 `rustcode-*`,旧条目得以保留)。**坑**:旧提交(≤`bd6c070d`,2026-09-20)的 `cross-build.sh` 仍用 musl.cc 死源(实测挂死无输出),要用 HEAD 的 `install-musl-cross.sh` 钉源工具链(`/opt/aarch64-unknown-linux-musl`)并 env 覆盖链接器三件套(`CARGO_TARGET_AARCH64_UNKNOWN_LINUX_MUSL_LINKER` / `CC_aarch64_unknown_linux_musl` / `AR_aarch64_unknown_linux_musl`,env 优先于 worktree 里指向旧命名 `aarch64-linux-musl-gcc` 的 `.cargo/config.toml`)。v6.1.0 的 linux-arm64 即此法补齐(manifest sha256 双向核对 + prepush self-test 通过;记录见 `.codebuddy/artifacts/2026-09-25-release-arm64-handoff/HANDOFF.md`)。
- GitCode 发布:`scripts/gitcode_release.py`(GitCode 官方 OpenAPI `POST /api/v5/repos/{owner}/{repo}/releases` + GitLab-v5 `releases/{tag}/upload_url` 附件上传;`--dry-run`/`--attach`/`--file-name`;主机/owner/repo/token 全部由 env `RUSTCODE_RELEASE_API_HOST`/`OWNER`/`REPO`/`ACCESS_TOKEN` 注入,脚本不带厂商默认)。Gitee Go 流水线 `.workflow/构建与发布.yml` 用 `shell@agent`(自托管主机组 `gitee-go`;Gitee Go 无 Rust 云端编译插件、也无容器版 shell,故整条跑在主机组上):先 `npm ci && npm run build` 构建 webui,再 `bash scripts/cross-build.sh` 交叉出 linux-x64/arm64(musl)+windows-x64(gnu),最后分别调 `scripts/gitcode_release.py` 与 `scripts/gitee_release.py` 双发到 GitCode + Gitee;凭据走流水线 env(GitCode 侧 `RUSTCODE_RELEASE_*`、Gitee 侧 `GITEE_*`),不在 YAML 硬编码。`shell@1` 不是合法插件(正确是 `shell@agent` 且必须带 `hostGroupID`)。macOS 不在 Gitee 覆盖,由 `.github/workflows/build.yml` 在 GitHub Actions 构建并只发 GitCode,两套互为冗余。`build.yml` 的发布门控是 `!cancelled() && (github.ref_type == 'tag' || inputs.publish == true)`:tag 推送必然发布,手动 `workflow_dispatch` 默认**只构建**,需勾 `publish` 才发布(GitHub Release 显式传 `tag_name`,故非 tag ref 也能建 Release);发布前有 6 产物守卫,缺任一平台即显式失败,不再静默跳过。注意作业级 `if` 只写业务条件时会**隐式叠加 `success()`**,必须带 `!cancelled()` 才能让构建不全时仍执行到守卫。
- `RUSTCODE_HOME` 覆盖配置目录(默认 `~/.rustcode`)。**禁止 `sudo` 运行**——`~/.rustcode` 一旦出现 root 属主文件,后续非 root 启动在 runtime 初始化即失败。

## 分支策略 (强制门禁)

**dev 是唯一的开发分支;main 只是上游 `atomgit_atomcode/atomcode` 的同步镜像,只接受上游单向流入——禁止从 dev 合并、禁止任何 fork 自造的提交。**

### 远程约定

| remote | 地址 | 角色 |
|--------|------|------|
| `origin` | `https://gitcode.com/SecLab/RustCode` | 本 fork(推送目标) |
| `upstream` | `https://gitcode.com/atomgit_atomcode/atomcode` | **上游同步目标(只读)** |

`main` 的 upstream 跟踪目标**必须是 `upstream/main`**,不得设置为 `origin/main`、`dev` 或任何其它分支。
`upstream` remote 与跟踪关系都不在版本控制内,新克隆需手动建立(或跑 `./scripts/install-hooks.sh`,它已幂等包含这几步):

```bash
git remote add upstream https://gitcode.com/atomgit_atomcode/atomcode
git config remote.upstream.tagOpt --no-tags   # 不抓上游 tag
git fetch upstream main --no-tags
git branch --set-upstream-to=upstream/main main
```

| 分支 | 用途 | 允许操作 |
|------|------|---------|
| `dev` | 主开发分支,所有功能/修复在此提交 | 直接 push、PR 合并 |
| `main` | 上游镜像,与 `upstream/main` 对齐 | **仅上游同步**(不得含 fork 自造提交) |

fork 的全部改动只存在于 `dev`(及特性分支);**release tag 从 `dev` 打**,不再假定 `main` 带有 fork 代码。

### 环境约束与已知坑 (先读这条,能省掉几轮返工)

- **cgroup 内存上限 4 GiB**(AGENTS.md 旧记录的 8GB 已过时,以实测为准):默认并发下 rustc 会 SIGBUS(曾在 `rustcode-coding` 与 CLI 的 `acp_end_to_end` 目标崩溃)。内存峰值主要来自**链接四个大二进制**(`rustcode` / `rustcode-daemon` / `rustcode-coding` / `rustcode-tuix`),不是编译小 crate。**三条降峰手段,均已内置**:① `cargo test -j 1 --workspace --no-fail-fast`;② 对大 bin 关 debug 符号(`CARGO_PROFILE_DEV_PACKAGE_<name>_DEBUG=0` / 命令行 `--config 'profile.dev.package.rustcode.debug=0'`),链接器工作集与产物体积降数倍,而库 crate 仍带符号(backtrace 仍可定位行号);③ 关增量编译(`CARGO_INCREMENTAL=0`)。`./scripts/test-all.sh` 已默认带上 ②③并把并行度压到 `min(nproc,2)`,可用 `RUSTCODE_TEST_JOBS` / `RUSTCODE_TEST_SYMBOLS=1` / `RUSTCODE_TEST_INCREMENTAL=1` 逐项放开;CI `test` job 同样默认关大 bin 的 debug 符号。
- **磁盘会被打满**:`target/debug/incremental` 能涨到 15G+ 并致链接器 `No space left on device`。该目录与 `target/debug/examples` 是**可弃缓存**,直接删恢复;**保留 `deps/` 下的 `.rlib/.rmeta/.d/.o`**,否则全量重编。
- **工具会话超时约 60–90s**,长任务须 `setsid nohup ... &` 脱离会话后轮询。**同一日志路径绝不可被两个进程共用**,且启动全量前先确认 `pgrep -c cargo = 0`——并发全量测试会争用 daemon 固定端口 **13456-13458** 而假红(`daemon_token_auth` 尤甚)。
- **CLI 包名是 `rustcode` 不是 `rustcode-cli`**:`-p rustcode-cli` 直接失败,用 `-p rustcode`。
- **测试隔离靠 `#[ctor]`**:`coding`/`tuix`/`daemon`/`capabilities`/`cli` 入口文件顶部把 `RUSTCODE_HOME` 重定向到临时目录。**重命名这批目录/变量名时必须同步改,否则隔离失效**(会污染真实 `~/.rustcode`)。
- **测试内改 `RUSTCODE_HOME` 必须持 `crate::home_test_lock()`**(`cli` 的 `main.rs`,2026-10-17 修):`std::env::set_var` 是**进程级**的,`#[ctor]` 只保证"进程启动时隔离一次",挡不住同一测试进程内**并行**跑的两个测试互相改写 HOME。曾经的 CI 假红 `im_admin::add_persists` 就是这么来的——`schedule_cmd` 的 store 测试与它并行,把 env var 换掉,导致第二次 `load_config()` 读到第一次的 allowlist。**注意"每个模块各有一把锁"是无效的**(两把锁互不排斥,等于没锁):`schedule_cmd::tests::store_lock()` 与 `im_admin::tests::HomeGuard` 都委托到这一把进程级锁。新增会碰 `RUSTCODE_HOME` / config / schedule store 的测试,一律接这把锁,不要另起 `OnceLock`;`#[serial_test::serial]` 只串行化自己标记的测试,同样拦不住别的模块。验证姿势:`cargo test -p rustcode --bin rustcode -- --test-threads=8 <filter>`(单线程跑不出来这个竞态)。
- **改动 i18n 文案后要跑整个 crate 的 `--lib`**:内容断言散落在 `en.rs`/`zh_cn.rs` 末尾的测试模块里,不是只有受影响的功能测试。
- **断言本地化输出的测试必须持锁**:`i18n::test_lock()` + `set_locale(...)`。漏锁在默认中文下**确定性失败**(曾把 6 个存量红误诊为"locale 竞态")。
  **但注意分两种锁**:`summarise_*` 类测试是**刻意与 locale 无关**的——它用 `t()` 现算期望值再比对,只持 `test_lock()` 取稳定性,**绝不能 `set_locale`**(两次调用间 locale 被翻转会制造新红)。
- **统计残留面必须用 shell 精确计数**:`grep -rIoi ... | wc -l`。搜索工具的聚合 `count` 会低估(曾据此漏报 92 处的实际规模)。
- **已跟踪文件不受 `.gitignore` 约束**:判断是否入库必须 `git ls-files` / `git status` 实测,别只读 `.gitignore`。
- **子代理通道不稳定**:涉及编译的任务派发 `code-implementer` 易 idle timeout(编译期无输出触发空闲);纯文档任务(`doc-writer`,不跑构建)可正常派发。长编译任务宜直接执行或先拆小。

### 四层保护

1. **CI 门禁**(`ci.yml` `branch-protection` job):push 到 main 时触发,先 `git remote add upstream` 再 `git fetch upstream main --no-tags`,检查 `git rev-list --count upstream/main..HEAD` 是否为 0;不为 0 则 CI 失败。
2. **本地 pre-push hook**(`.githooks/pre-push`):推送到 main 前检查 `upstream/main..<local_sha>` 是否有提交;有则拒绝推送。**未配置 `upstream` 跟踪 ref 时 fail-closed 拒绝**(不再像旧的 dev 判据那样「找不到就跳过」)。安装:`./scripts/install-hooks.sh`(等价 `git config core.hooksPath .githooks`)。
3. **平台分支保护**:在 GitCode 仓库设置中将 main 设为 protected branch,限制 push 权限(需仓库管理员在 Web 界面操作)。
4. **发布产物门禁**(`.githooks/pre-push` → `scripts/prepush-release-check.sh`):**仅对非 main 分支生效**——main 是上游镜像,其提交不含 fork 的 `release/` 产物,把门禁套在 main 上会拒绝每一次上游同步。推送前要求被推送提交内**已提交** `release/<version>/manifest.json` 与该推送主机 OS/ARCH 的产物,`<version>` 取自被推送的 `Cargo.toml`——版本号 bump 必须配套产物,同版本内迭代不阻塞。`RUSTCODE_PREPUSH_RELEASE=strict` 额外要求 `manifest.source.sha` 是被推送提交的祖先、其间除 `release/` 外无源码改动、且 `source.dirty=false`(即产物确由该代码构建);`=off` 跳过。门禁**只校验不编译**(钩子内编译会阻塞每次 push 且可能 OOM)。产物未提交时按提示跑 `scripts/release-host.sh`(`RUSTCODE_PUBLISH_COMMIT=1` 可让它自动 `git add release/` 并提交,不卷入他人 WIP)。注意 `source.sha` **不可能等于**被推送 sha——manifest 在构建时写、产物之后才提交,那会构成自指哈希,故 strict 取「祖先 + 其间无源码漂移」这一可满足的最强判据。
  - **同门禁附带的指针检查**(2026-10-15 加):产物齐了也可能发不出去——`Cargo.toml` 已是 v6.2.3 而 `release/index.json` 最高只到 v6.2.1、`latest.json` 也停在 v6.2.1 时,在线 Release 有 v6.2.3 全套二进制,但仓库 raw 回退源没有该版本、`/upgrade` 还会指向一个在线零二进制的 v6.2.1。三处指针任一落后即拒绝推送(判据与修复命令见 `scripts/release-check-pointers.sh --help`)。

### 正确的 main 同步流程

```bash
# 1. 拉上游(只读)
git fetch upstream main --no-tags

# 2. 本地 main 前进到上游(fast-forward only)
git checkout main
git merge --ff-only upstream/main    # 纯镜像等价写法: git reset --hard upstream/main

# 3. 推送 fork 的 main
git push origin main
```

本地 main 若含 fork 自造提交,第 2 步会失败——那不是命令的问题,而是违规,按下一节处理。

### 违规处理

如果 main 上出现了 `upstream/main` 不存在的提交(例如又把 dev 合并了进来):
1. 把这些提交搬到 dev:`git checkout dev && git cherry-pick <sha>`(若本来就来自 dev,确认 dev 已包含即可)
2. 推送 dev:`git push origin dev`
3. 重置 main 为上游:`git fetch upstream main --no-tags && git checkout main && git reset --hard upstream/main`
4. 推送 main:`git push origin main --force`(**仅此一次性纠正场景允许 force push main**,且必须先确认这些提交都已进入 dev)

测试:
- `cargo test` — 默认成员;`cargo test --workspace` — 全量(跨 crate 改动必跑)。
- `cargo test -p rustcode-capabilities` — 单 crate;`cargo test -p rustcode-coding <filter>` — 按测试名过滤;`--` 后接 `--nocapture` / `--test-threads=1`。
- `cargo test -p rustcode-kernel --test <name>` — 只跑某个 `tests/*.rs`;`--lib` 只跑内联单测,`--bins` 只跑 bin 内测试。
- `./scripts/test-all.sh` — 全量测试并产出 `test-report.md`,能区分"编译失败 / 测试失败 / 全部通过"。已内置 OOM 防护:并行度 `min(nproc,2)`、大二进制默认 `debug=0`、默认关增量编译;逐项放开用 `RUSTCODE_TEST_JOBS` / `RUSTCODE_TEST_SYMBOLS=1` / `RUSTCODE_TEST_INCREMENTAL=1`。
- `./scripts/test-headless.sh` — headless 冒烟(需先 `cargo build`);未设 `RUSTCODE_TEST_PROVIDER` 时跳过联网用例。
- `./scripts/smoke-test-all.sh`(校验 test-all.sh 自身)、`python3 scripts/acp_smoke.py`(ACP stdio 冒烟)、`python3 scripts/analyze_datalogs.py`(turn datalog 分析)。
- `python3 scripts/test_gitcode_release.py` — `gitcode_release.py` 的 unittest(等价 `python3 -m unittest scripts.test_gitcode_release`)。
- python3 scripts/check-zh-docs.py gate —— 中文文档门禁(全量,判定全仓 md 的英文化残留);check --files <path> 只查指定文件,inventory 产出 md 清单,hostscan 仅产出「默认绑定语义」的 127.0.0.1 / localhost 叙述清单(清单工具,非门禁,恒返回 0)。
- 测试隔离:`coding`(`src/lib.rs:35`)/ `tuix` / `daemon` / `capabilities`(`src/lib.rs:27`)/ `cli`(`src/lib.rs:10`,另 bin 的 `main.rs` 也有一份)的入口文件顶部有 `#[ctor]` 把 `RUSTCODE_HOME` 重定向到临时目录。新增测试不得依赖真实 `~/.rustcode`;**重命名这批目录/变量名时同步修改,否则测试隔离失效**。注意 capabilities 的注释明说「每个测试二进制各带一份自己的 ctor,不共享」——新增 crate 或测试二进制必须自己加一份,别指望被覆盖。

Lint / 格式:
- `cargo fmt` / `cargo fmt --check`;提交前 `cargo clippy --workspace --all-targets`。
- `cargo check --workspace --all-targets` — 快速编译校验;`cargo test` 已覆盖相同编译验证时不再重复 `cargo check`。
- 仓库当前无 `rustfmt.toml` / `clippy.toml` / `[lints]` 段,无需新增。

WebUI 默认绑定地址(改这里前必读,默认值按入口而不同):
- CLI 两个入口默认绑定 0.0.0.0:`rustcode webui` 与 `rustcode daemon` 的 `--host` 均为 `#[arg(long, default_value = "0.0.0.0")]`(daemon 在 `crates/rustcode-cli/src/main.rs:1184`、webui 在 `:1208`,两处 help 共用 `Msg::CliHelpHost`,逐字一致),由 `main.rs:2808` 的 `ServerOpts { host, .. }` 传入 `run_server`,即局域网可达、仅靠 token 保护、无 TLS。两个入口都可用 `--host 127.0.0.1` 退回仅本机。
- 独立 `rustcode-daemon` 二进制与 TUI 的 `/webui` 默认仍是 127.0.0.1:前者见 `crates/rustcode-daemon/src/main.rs:21` 的 `DEFAULT_HOST`(由 `:110` 的 `host.unwrap_or_else` 兜底),后者见 `crates/rustcode-tuix/src/event_loop/commands.rs:1812` 的 `"webui" =>` 臂——内部 `parse_host()`(`:1822`)默认返回 127.0.0.1,且**额外支持快捷词 `lan`**(= 0.0.0.0),这是 `/webui lan` 的唯一实现。同文件 `:1916` 的 `/tunnel` 也有独立的 `lan` 分支(`:1928`),改一处不会带动另一处。这是刻意保留的安全边界,**不要为了「统一默认值」把它们也改成 0.0.0.0**。
- 非回环风险提示:旧的启动横幅 `Msg::DaemonWarnNonLoopback` 已从 `run_server` 移除,改由 `Msg::WebuiLanWarning`(0.0.0.0 或 `::`)与 `Msg::WebuiNonLoopbackWarning`(其它非回环地址)承担,**两处发射点**:`ensure_server_and_open`(随访问 URL 打印,`crates/rustcode-daemon/src/lib.rs:5871`)与 `run_server` 的 `if !quiet` 分支(`:6927`,给不经 `ensure_server_and_open` 的 `rustcode daemon` / 独立二进制补发);回环绑定保持静默。判定谓词是 `is_loopback_bind_host`(`crates/rustcode-daemon/src/lib.rs:1284`,在 `is_loopback_authority` 之外额外认 `::1` 与 `::ffff:127.0.0.1`),故 IPv6 回环写法不告警;该谓词**只用于是否打印提示,不得用于任何鉴权判定**(同一文件 `:1288-1297` 的注释解释了为何不放宽 `is_loopback_authority` —— 后者被 `client_interactive_permission` 用于安全决策)。`Msg::DaemonWarnNonLoopback` 变体本身按 T-04 契约 K4 保留在 `crates/rustcode-config/src/i18n/messages.rs:4898`,勿当死码清理。

免密访问 webui(不输入密码/令牌,打开即用):
- 开关只有一个解析入口:`rustcode_config::config::webui_no_auth_enabled(cli_flag, Option<&Config>)`(crates/rustcode-config/src/config/mod.rs)。优先级**环境变量 `RUSTCODE_WEBUI_NO_AUTH` > 命令行 `--no-auth` > 配置 `webui_no_auth`**,默认 false(保持 token 鉴权)。环境变量取的是**显式值**,`=0` 能压住配置里已开的开关。**任何新入口都必须调它,禁止各自 `std::env::var` 再判一次**——否则两套真相。
- 三个 driver 的接线:`rustcode webui --no-auth` 与 `rustcode daemon --no-auth`(crates/rustcode-cli/src/main.rs,两处 help 共用 `Msg::CliHelpNoAuth`);独立 `rustcode-daemon` 二进制没有该参数,只读 env + 配置(crates/rustcode-daemon/src/main.rs);TUI 的 `/webui` 同样不带开关,由 `ensure_server_and_open(host, port, sync, no_auth_flag)` 内部解析(第 4 参)。
- 免密的落点是 `ServerOpts.webui_no_auth` → `AppState.webui_no_auth`,**鉴权判据是 `enforce_token = webui_tokens.is_some() && !webui_no_auth`**(crates/rustcode-daemon/src/lib.rs)。免密时 token store 仍在、token 文件照写(IDE 客户端行为不变),只是 `require_webui_token` 不再拦。
- `client_interactive_permission()` 额外把 `webui_no_auth` 计入交互式权限:免密是**用户主动放弃鉴权**,不等于「没有 UI 可应答」。只看 `enforce_token` 会让绑 0.0.0.0 的免密 webui 因非回环被判成不可交互,权限请求无人应答。
- 进程内 webui 复用判定额外要求鉴权姿态一致(`WebuiHandle.no_auth`):正在跑的实例若与本次要求的免密/带密相反,先 `abort` 旧的再重新起,绝不静默复用出与用户要求相反的访问方式。
- 免密时 URL 不再 mint/携带 `?token=`,并在 URL 后与 daemon 启动横幅各补一条 `Msg::WebuiNoAuthNotice`。
- **免密 + 已配静态密钥 = 密钥被架空**,必须额外提示:密钥仍登记进 token store、token 文件照写,但中间件不校验,运维容易误以为 `access_key` 还在守门。判据是 `webui_no_auth_masks_access_key(Option<&Config>)`(config 层),三个 driver 都补一条 `Msg::WebuiNoAuthKeyIgnored`(cli daemon 子命令 stderr、独立 daemon 二进制 stdout、`ensure_server_and_open` 追加到返回消息)。**刻意不看 `RUSTCODE_DAEMON_TOKEN`** —— 那是主进程拉起 daemon 的桥接令牌(多为随机值),拿它判定会一开免密就误报。
- `/tunnel`(经中继暴露到公网)**刻意不受本开关影响**(`ensure_tunnel_server` 硬写 `webui_no_auth: false`),远程接入始终要 token。
- 环境变量名的事实源是 `endpoints::WEBUI_NO_AUTH_ENV`(crates/rustcode-config/src/endpoints.rs),与其它 `RUSTCODE_*` 同处一处;`config::WEBUI_NO_AUTH_ENV` 只是它的再导出,**不要再在 config 里另写字面量**。

daemon 文件面 `/fs/*`(改这块前必读,**安全敏感**):
- 五个端点都在 `protected` router 内(挂 `require_webui_token`):`GET /fs/list`、`GET /fs/search`、`POST /fs/mkdir`、`POST /fs/open`、**`GET /fs/read`(2026-09-25 新增,文本预览)**。
- **保护强度取决于 `enforce_token`**:`require_webui_token` 在 `!enforce_token` 时**直接放行**(auth_token.rs:123-126)。`enforce_token=false` 见于独立 daemon / VSCode 实例,以及**免密模式**(`webui_no_auth`)。
- **各端点的约束强度不同,别一概而论**(2026-09-25 用户裁决:「暂时不允许下载,只允许工作目录内查看,不运行越权访问」):
  | 端点 | 工作目录约束 | 敏感路径拒绝 | 免密 |
  |------|------------|------------|------|
  | `GET /fs/read` | **强制**(会话工作目录) | 是 | **403** |
  | `POST /fs/mkdir` | **不约束**(项目选择器要建目录) | 是 | **403** |
  | `POST /fs/open` | **不约束**(产物回看,且不返回内容) | 是 | 允许(非内容/写操作) |
  | `GET /fs/list` `/fs/search` | 不约束 | **尚未加**(见「残留」) | 允许 |
  **残留(如实登记,勿当已解决)**:`/fs/list` `/fs/search` 仍可列/搜工作目录外的任意目录——它们服务"选项目目录"这一既有交互,不返回文件内容,但**信息面仍在**,收束属后续独立评估。`/fs/download` 与 `/fs/package` **按裁决未实现**(不引入 zip 依赖)。
- **[CORRECTION 2026-09-25] `/fs/open` 并未被限制在工作目录内**。`resolve_workspace_file`(`:6471`)只做 canonicalize + 要求普通文件,**没有 `target.starts_with(root)` 校验**:绝对路径直接采纳、相对 `../` 可逃逸。它不返回内容(只调 GUI 打开器)故危害有限,但**新增任何"返回内容"的端点时绝不能沿用该函数**。
- **根约束有统一 helper 了**(2026-09-25 F1):`capabilities/src/pathnorm.rs` 的 `path_within_root`——**先 canonicalize 再判前缀**(顺序是硬要求,否则符号链接可绕过),任一侧 canonicalize 失败即 false(fail-closed)。它放在无 feature 门控的 `pathnorm` 里,因为 `lsp` / `skills` 等 feature **不**启用 `tools`,放在 `fs_boundary` 会被挡住。已复用的三处:`tools/mod.rs`(not-found 提示)、`tools/open_file.rs`(`OpenFileWorkspaceGate`)、`codeintel/lsp_tool.rs`。
  - **例外:`skills/render.rs` 的 `source_rank` 刻意保持词法 `starts_with`**——它是目录**排名**启发式且候选路径可能不存在,`path_within_root` 会 canonicalize 致其恒 false;该处**不是安全边界**,勿"统一"。已在原地加注释说明。
- **文件面唯一判据**是 `capabilities/src/fs_boundary.rs`(feature `tools`)的 `authorize_file_access(root, requested, FileOp, FilePolicy)`:**判据集中,禁止调用点各写 `if`**。判定顺序固定:空路径 → 免密且内容/写操作(`NoAuthMode`)→ canonicalize → 根约束 → `path_is_sensitive` → 按 op 校验(Read/Download 另查普通文件+大小上限+二进制;Package 查目录)。返回 `FileDeny`(机器枚举,无文案,L1 不依赖 config,由 daemon 边缘映射 i18n)。默认上限 `DEFAULT_MAX_FILE_BYTES` = 1 MiB;`FileOp::exposes_content()`(Read/Download/Package)与 `is_write()`(Mkdir)是免密 fail-closed 的判据。
- 可复用的现成轮子:`capabilities/src/tools/sensitive_path.rs` 的 `path_is_sensitive`(`:201`,系统保护前缀 + `.ssh`/`.aws`/`.gnupg` + 秘密文件名/扩展名)与 `references_sensitive_path`(`:65`);`tools/read.rs` 的限流常量(`MAX_IN_MEMORY_BYTES` / `DEFAULT_READ_LIMIT` / `MAX_READ_OUTPUT_BYTES` / `MAX_LINE_LEN`)。
- **入站方向无 TLS**:`Cargo.lock` 中 `axum-server` 0 命中,daemon 的 rustls/reqwest 只服务**出站**(`egress/client.rs` 的 `build_http_client`)。`rustcode-config` 里的 `skip_tls_verify` 全是**出站 provider** 语义,**不可复用**于入站。TLS 走反向代理或 `/tunnel` wss,不在 daemon 内自建。
- **`/fs/list` 返回体只有文件名字符串数组**(`{path, dirs, files}`),无 size/类型/是否二进制——前端无法判断大文件与二进制。
- **判据模块**(`capabilities/src/fs_boundary.rs`,feature `tools`):`authorize_file_access(root, requested, FileOp, FilePolicy)`(读/打开/打包)、`read_text_file`(一次解析一次读,避免校验与使用之间文件被换)、`authorize_directory_creation`(建目录:走**最近已存在祖先** canonicalize,故 `..` 按落点判定)。**判据集中,禁止调用点各写 `if`**。返回 `FileDeny`(机器枚举、**零文案**——L1 不依赖 config),由 daemon 边缘的 `file_deny_message`/`file_deny_status` 映射 i18n;新增 `FileDeny` 变体会让该 match 非穷尽而**编译失败**,强制补齐两语。
- **`path_is_sensitive` 的真实边界(易误判)**:它只把 `.ssh`/`.aws`/`.gnupg` 判为敏感**当它们位于真实 home 之下**,另加系统前缀与**秘密文件名/扩展名**(`id_rsa`、`.env`、`*.pem` 等)。故"工作目录内恰好叫 `.ssh` 的目录"**不**被判敏感——`.ssh/id_rsa` 之所以被拒是靠**文件名** `id_rsa` 命中。这是与写审批共享的既有定义,**不要在文件面另写第二套**。
- 改造方案与分期(F1/F2'/F4 已落地,F5/F6 按裁决推迟):`docs/plans/2026-09-25-file-surface-security.md`。

WebUI 右侧文件面板(2026-09-25 新增):
- **三栏**:`.app`(flex row)= `Sidebar` | `.main-column` | `.file-panel`。面板**默认关闭**,由 `app.tsx` 的 `filePanelOpen` 控制;开关按钮 `.file-panel-toggle` 放在 **main-column 内**(绝对定位,窄屏面板改为 fixed 覆盖,见 `@media (max-width:900px)`)。
- **本轮改动文件的单一来源**:`Chat` 经 `onTurnArtifacts` 上报**最近一个**助手回合的产物(内部调 `turnArtifacts.ts` 的 `artifactsByAssistantIndex`),`app.tsx` 存于 `turnArtifacts` state 并传给 `FilePanel`。落地态/空消息显式上报 `[]`,避免上一会话文件残留。**不要再在面板里重新解析消息**——否则两套"改了什么"的真相。
- **预览走 `GET /fs/read`**(`api.ts` 的 `readFile`),服务端才是边界:锁定会话工作目录 + 敏感路径拒 + 1 MiB 上限 + 二进制拒 + **免密 403**。面板必须**原样显示服务端返回的本地化错误**,不要在浏览器重写判定——浏览器无法解析符号链接,重写必然与服务端不一致。
- **浏览走 `/fs/list`(不锁工作目录)**:工作目录外的文件**照常列出但标为不可预览**(`filePanel.outside`),不隐藏——agent 可能确实写到了外面,隐藏会像 bug。`filePanel.ts` 的 `fsIsWithinWorkspace` 只是 **UX 判断,不是安全边界**。
- 纯函数进 `webui/src/lib/filePanel.ts`(归一化/包含判定/面包屑/目录行/产物配对),组件只渲染;单测在 `filePanel.test.ts`。**只读面板**:无新建/改名/删除/上传/下载(下载按裁决推迟)。

WebUI 前端三条约定(改这块前必读):
- **剪贴板必须走 `webui/src/lib/clipboard.ts` 的 `copyText()`**,禁止在组件里直接 `navigator.clipboard.writeText`。webui 默认绑 0.0.0.0、通常经局域网 `http://192.168.x.x` 打开,那是**非安全上下文**,`navigator.clipboard` 为 `undefined` —— 直接调用要么同步抛 TypeError(按钮完全没反应),要么 optional chaining 静默短路却仍显示「已复制」。`copyText` 的顺序是:Clipboard API → `document.execCommand('copy')` 回退 → 返回 `boolean`;**调用点必须按返回值区分成功/失败并给出可见反馈**(`copy.failed`),不要吞掉。
- **模型列表刷新是事件驱动,不是轮询**:`ModelConfigDialog` 关闭 → `app.tsx` 的 `modelsVersion` 自增 → `Chat` 转 `modelRefreshSignal` → `ModelSelector` 重拉 `/models`;此外每次**打开**下拉也会强制重拉(刚新增的模型必须能在同一次交互里选中)。`loadModels(interactive)` 里 `seqRef` 是「最新响应胜出」的竞态守卫,`onDefaultChangeRef` 用来保持回调 identity 稳定——**不要把父组件回调直接放进 `useCallback` 依赖**,否则 effect 会在每次父级 render 重新拉一次。
- **回合级「回退 / 重新生成」建立在 `/undo N` 之上**:目标由 `webui/src/lib/turnActions.ts` 的 `assistantTurnActions()` 计算(`promptN` 就是 `/undo N` 的 N),动作在 `Chat.tsx` 的 `undoTurn()`(走 `POST /command` 的 `command:'undo'`,已白名单、会落盘并修正 token 统计)。约束:sync 模式与 busy 时**明确拒绝**(前者 `/command` 直接改磁盘快照会与 live runtime 的 lease 冲突);`Rewind`(代码回滚)目前在 v5.0.5 默认关闭,不要拿它当 restore 的落点。sync 模式支持需新增 `/live/undo` 路由 + `UndoFinished(Ok)` 的 wire 投影(当前 projector 只转发 Err,Ok 被丢弃),属独立后续项。

凭据闸门与 Auto 模式(改这块前必读):
- `CredentialBashGate`(crates/rustcode-capabilities/src/tools/credential_bash_gate.rs)拦截 bash 里的凭据字面量/配置读取:`Prompt` 走审批、`Strict` 直接终止回合。
- **Auto 模式(绝对信任)会绕过该闸门**:`CodingParts::bypass_mode` 这个 `Arc<AtomicBool>` 经 `CredentialBashGate::with_bypass()` 注入主 agent 与 `task` / `team` 子代理的 gate;置位时直接 `Proceed`,既不弹审批、也不降级为 call-only deny,连 `Strict` 也不终止回合。这是刻意的——用户自己接管了方向盘,凭据检测不该冒出 `policy_denied`。
- 该 flag 在 `parts.rs` 的 `prepare` 里**创建一次**并克隆到主 gate 与两个子代理 gate(`subagent_child_middlewares_with_bypass` / `team_child_middlewares_with_bypass`),共享同一 cell 才能让中途 Shift+Tab / `/mode auto` 立即生效而无需重建 gate。**新增子代理入口时务必传同一个 cell**,各自 `new` 一个就退化成两套真相。
- 回归防线:`crates/rustcode-coding/tests/credential_bash_auto.rs` 走完整 `prepare` + `assemble`(不只测 gate 本身),断言 Auto 开时放行、关时 `Strict` 仍终止回合。

## 架构总览(分层与 crate 地图)

```text
L3  drivers   rustcode-cli(pkg `rustcode`)  rustcode-tuix  rustcode-daemon
              rustcode-clix(bin `rustcodex`)  ACP(src/acp/)
                    |             |                |
L2  specialize      |             +----> rustcode-coding (CodingRuntime)
                    |                          |     `-- rustcode-review
L1  capabilities    rustcode-capabilities / rustcode-wiki <----+
L0  neutral         rustcode-kernel <----------+
leaf                rustcode-config / rustcode-updater / rustcode-tunnel
```

> 上图 leaf 行的 `rustcode-codingplan` 与 `rustcode-codingplan-crypto` 两个 crate 已于 2026-09-09
> 按用户裁决 Q1=B 删除,图中已移除;`rustcode-tunnel`(内置反向隧道中继客户端)为新增 leaf 成员。现工作区 crates 目录下有 **12 个成员**,`members = ["crates/*"]` 全量纳入;`rustcode-wiki`(2026-09-11 新增的项目 wiki 自动生成模块)是其中之一。`default-members` 为 cli / daemon / tuix / **tunnel**——tunnel 特意列入,好让 `cargo build --release` 直接产出中继二进制 `rustcode-relay`(`crates/rustcode-tunnel/src/bin/rustcode-relay.rs`),否则需 `-p rustcode-tunnel` 而容易被漏掉。
> 原 `auth` leaf crate（即旧 `rustcode` 的 auth 子 crate）已随本批次基线删除,故已从 leaf 行移除,不保留对照。

- **出站 HTTP 只有一个入口**:`capabilities/src/egress/`(`egress` feature,由 `provider` / `web` / `atomgit` / `mcp` 拉起)。`egress::client::build_http_client` 是唯一工厂,统一承载信任根分层、代理策略、超时、UA、pool-idle。**新增任何出站调用都必须走它,禁止再写 `reqwest::Client::new()`。** 离开 async 运行时的一次性调用(TUI 模型发现、OAuth 登录/刷新)走同一工厂的阻塞变体 `build_blocking_http_client`(`egress-blocking` feature,2026-09-23 新增):与异步侧共用同一 `HttpClientSpec` 字段映射、同一份信任根收集(#514)与 webpki 兜底重试,**禁止再手写 `reqwest::blocking::Client::builder()`**。
  - **两类结构性豁免,别当违规上报**:① leaf crate 无法依赖 capabilities(`rustcode-updater` / `rustcode-tunnel`);② LLM 适配器(`provider/{anthropic,openai_compat,ollama}.rs`)打的是**用户自供的 base_url**,属 BYO 语义,不走工厂。
- 依赖只向下:`kernel`(无内部依赖) <- `capabilities`(禁止反向依赖 coding / driver / 已退役 core) <- `coding`(另依赖 kernel、config、review) <- `tuix`(另依赖 daemon、updater) <- `cli`(唯一同时依赖 tuix + daemon)。`clix -> review, coding, capabilities, kernel, config`。
- 工作区 `members = ["crates/*"]`,`default-members` 为 cli / daemon / tuix / tunnel;`rustcode-codingplan-crypto` 曾是闭源签名占位桩(默认成员故意不含它,官方构建用 `--features rustcode/codingplan-crypto` 开启),该 crate 与该 feature 已于 2026-09-09 一并删除,现无此成员、无此开关。
- **[SUPERSEDED 2026-09-09,整条作废]** codingplan 的网关 HTTP client feature 传递链(`client` Cargo feature、驱动侧 `codingplan` feature 向上传递 `rustcode-codingplan/client`、原先必跑的七种 feature 组合校验)已随 crate 删除而不复存在,详见 `docs/archive/`。
- **`CodingRuntime`**(`coding/src/runtime.rs`)是 coding agent 的唯一运行时所有者,对外暴露 `CodingRuntimeHandle`。Driver 通过 `DriverCommand` 驱动,读 `CodingRuntimeEvent`;不得自建第二套 live agent 生命周期。
- 启动路径:CLI `spawn_native_cli_runtime`、ACP `spawn_native_runtime_for_session_deferred_with_preprocessor`、daemon `kernel_runtime::start_native_runtime*`,三者最终都落到 `CodingRuntime::start_with_session_lease` / `start_with_bootstrap`。**TUI 不自己启动 runtime**:外部把已启动的 `SpawnedRuntime` 传进 `tuix::run`。
- kernel `Agent` + `AgentBuilder` / `AgentHandle` / `AgentCommand` / `AgentEvent` 是中立循环,不得承载 coding 产品语义。`rustcode-review` 是独立业务 agent,以 `code_review` 子 agent 工具挂进 coding。
- 运行时领域术语(Live View、Runtime Generation、Session Transition、Tool Catalog Revision、Committed Snapshot、Replay Window)**以 `CONTEXT.md` 为准**(注意:该文件使用旧 `RustCode` 命名,但术语定义仍有效),其中 `_Avoid_` 条目是硬性命名约束。

## Fork 重构目标与完成状态

本仓库是 `SecLab/RustCode` 的二次开发 fork,核心约束:禁止使用任何 Unicode Emoji,日志/注释一律用 ASCII 标签 (`[INFO]`/`[WARN]`/`[ERROR]`/`[SUCCESS]`/`[CHECK]`/`[+]`/`[-]`/`[*]`)。

### [OBJECTIVE-1] 产品重命名 — [DONE]

13 个 crate 全部 `atomcode-*` -> `rustcode-*`。配置目录 `~/.rustcode`;环境变量前缀 `RUSTCODE_*`。

重命名的事实源集中在两个文件(改这两处即可带动大部分):
`rustcode-config/src/distribution.rs`(`HOME_ENV` / `HOME_DIR_NAME` / 端口 `13456,13457,13458` / `PROCESS_NAMES` / `RELEASE_ASSET_PREFIX` 等)与 `rustcode-config/src/endpoints.rs`(10 个 `RUSTCODE_*` 环境变量名 + 托管端点常量)。

**[CHECK] `rustcode` 是已锁定的产品身份**(决策 D1,见 `docs/REFACTOR_DESIGN_PHASE1.md` §2.0),不是中间态;不要再次改名。O1 剩余工作只有 `extensions/` / `site/` / `docs/architecture.md` 的旧 `rustcode` 前缀收尾。

### [OBJECTIVE-2] 零遥测 — [DONE, 仅守卫性声明残留]

`rustcode-telemetry` crate 已删除;`Telemetry`/`Event`/`track`/`install_panic_hook` 等上报调用已移除。**全仓不存在 Sentry/PostHog/Segment/GA 等第三方埋点 SDK 或依赖**。崩溃处理仅保留 stderr 输出。

文档口径已对齐:`docs/telemetry.md` 已改为"Telemetry — removed"说明页;原中文 README 的零遥测声明与事实一致;`site/docs/{en,zh}/headless-daemon.html` 中 `--no-telemetry` 标注为"accepted and ignored"。

**[CHECK] 词义歧义已清零**:kernel(`hook.rs` / `agent.rs` / `event.rs` / `message.rs` / `tests/turn_complete.rs` / `tests/hook_a2_surface.rs`)与 capabilities(`mcp/mod.rs`)、clix(`main.rs`)里把"可观测性挂载点"误写为 `telemetry` 的 hook seam 注释已统一改为 `observability`。

**[ERROR] 剩余 `telemetry` 字样只有三类,全部是守卫而非生产方,禁止"顺手清理"式删除**:
1. 断言式澄清 —— `daemon/src/client_mode.rs`("NOT telemetry")、`cli/src/main.rs`("no network, no telemetry" ×2、"--client is NOT telemetry")、`config/src/config/provider.rs`("telemetry-free logs")、`cli/tests/shell_completion.rs`(断言不创建遥测状态)。删掉会让"本 fork 无遥测"失去可执行证据。
2. legacy 兼容与清理 —— `config/src/config/mod.rs` 的 `legacy_telemetry_section_tests` 守卫决策 D4(旧 `[telemetry]` 段被**忽略而非报错**,含 save/reload 往返);`cli/src/uninstall/{mod,paths}.rs` 卸载时清理旧 `telemetry/` 目录名(真实历史目录,删了会漏清理)。
3. 历史迁移说明 —— `config/src/session_mode.rs` / `config/src/lib.rs` 中被删 `telemetry_legacy` 模块的迁移目标。

**[CHECK] 客户端身份现状(不得误删)**:daemon 的 `ClientMode`(`daemon/src/client_mode.rs`)是本地分支逻辑,不是遥测;`RepoOrigin` / `detect_repo_origin` 已迁至 `rustcode-config/src/session_mode.rs`(纯字符串解析,无网络)。

### [OBJECTIVE-3] LLM Provider 解耦 — [DONE, 平台中立]

- 统一 trait `LlmProvider`(`kernel/src/provider.rs`),`async_trait`,唯一方法是 `chat_stream` -> `BoxStream<'static, StreamEvent>`。
- 三个适配器在 `capabilities/src/provider/`:`anthropic.rs`、`openai_compat.rs`、`ollama.rs`。
- 工厂是 **trait** `CodingProviderFactory`(`crates/rustcode-coding/src/provider_factory.rs:34`),默认实现按 `provider_type` 分发。ACP / daemon / clix 都通过它注入。
- 配置(`config/src/config/provider.rs`)已支持:`base_url`、`api_key`(支持 `$VAR` / `${VAR}` / `${VAR:-default}` 展开)、`extra_headers`、`proxy`、`skip_tls_verify`、`retry_max_attempts`、`thinking_*` / `reasoning_*` 系列等。
- **平台中立**:默认不绑定任何平台。签名网关识别器 `is_codingplan_llm_gateway` 与其唯一开关 `RUSTCODE_CODINGPLAN_LLM_BASE_URL` 已于 2026-09-09 一并删除——现在没有任何 base_url 会被判为签名网关,所有 provider 一律走纯 `bearer_auth(api_key)`,该环境变量设置后被直接忽略、不再报错。AtomGit REST 工具(`atomgit_repo/pr/issue`)由 `atomgit` Cargo feature 门控,默认成员不启用。
- **不向第三方模型厂商外发产品身份(默认关闭)**:`capabilities/src/provider/openai_compat.rs` 的 OpenRouter app 归因头(`X-OpenRouter-Title` / `X-OpenRouter-Categories` / `HTTP-Referer`)**默认全部不发**,需 `RUSTCODE_OPENROUTER_ATTRIBUTION=1|true|on|yes` 显式 opt-in(解析抽为纯函数 `attribution_enabled_from`,便于不改动进程级 env 地单测);`HTTP-Referer` 永不硬编码 host,由 `RUSTCODE_OPENROUTER_REFERER` 单独 opt-in。默认出站只携带第三方配置(`base_url` / `api_key` / `model` / `extra_headers`)本身。host 门禁 `is_openrouter_url` 保留(含 `openrouter.ai:x@evil.com` userinfo 冒用防护),即使 opt-in 也不会泄漏到非 OpenRouter 端点。落实 `docs/REFACTOR_DESIGN_PHASE1.md` §4.3 G6。
- 强类型错误分类器已就位:`capabilities/src/provider/error.rs` 的 `LlmError`(thiserror,`retryable()` 单点判定);**新代码必须经 `LlmError` 转换,存量按 `docs/phase1-refactor-design.md` 第 3 节渐进迁移**。

**[ERROR] 禁止在 kernel 之上再叠第二套 `LlmClient` trait。** 解耦落点是**配置 + 装配 + 错误映射**,即复用既有 `CodingProviderFactory` 与 `reassemble_provider` 热切换命令。

### [OBJECTIVE-4] License 与合规 — [DONE]

根 `LICENSE` 为 MIT,双版权行 `Copyright (c) 2026 Yubang Xu` + `Copyright (c) 2026 The rustcode authors (fork of rustcode)`。新模块头部只追加本 fork 声明,**不得覆盖或删除任何既有版权行**。

### [OBJECTIVE-5] 默认中文与平台残留收尾 — [DONE]

- **默认语言为简体中文**。事实源:`rustcode-config/src/locale.rs` 的 `Default for Locale` 与 `i18n/mod.rs`(static `LOCALE` 初值、`current_locale` 毒锁回退、`resolve_initial_locale_with_env` 终值)三处默认均为 `Locale::ZhCn`。优先级仍是 CLI `--lang` > config `language` > `LC_ALL/LC_MESSAGES/LANG` > 默认。`LANG=C`/`POSIX`/空值视为"无偏好"→ 中文;显式但不支持的 locale(如 `fr_FR`)→ 英文回退。WebUI(`webui/src/settings.tsx` `readLang`)默认本就是 `zh`。
- Agent 对话默认语言:persona 装配时按 `preferred_language` 注入 `## LANGUAGE` 段(`coding/src/persona.rs` `conversation_language_guidance`),用户语言不明时中文回复;显式英文 locale 则英文。
- **扩展旧名清零**:`extensions/vscode`(`_atomCode*Watcher` 字段、测试名、package-lock 根 name)与 `extensions/jetbrains`(`commonAtomcodePaths`/`guardAtomcodeHome`、临时目录前缀)已全部改为 rustcode;`packages/*` 无旧名。
- **平台残留注释泛化**:oauth/tls/proxy/codingplan/persona/kernel 等处硬编码 `*.atomgit.com` 的注释改为"managed endpoint"中性表述;`friendly_http_error` 的 403 提示改为"检查 API key 权限与账户状态";测试夹具 URL 改 `example.com`。OAuth loopback 回调的**错误分支不再 302 跳转 `atomgit.com`**,改为与成功分支同构的本地中性 HTML 错误页(本构建无附属平台站点);`strip_force_login` 等测试夹具 URL 改 `example.com`。`atomgit` Cargo feature(REST 工具、`api.atomgit.com/api/v5` 装配、push-label 中间件)整体 `#[cfg(feature = "atomgit")]` 门控、默认成员不启用——这是刻意保留的上游开关,不是残留;旧前缀兼容逻辑(`is_codingplan_provider_name`)及其测试夹具已于 2026-09-09 删除,生产代码中不再有由它承载的 `AtomGit*` 字样。
- **遥测注释收尾**:失实的"telemetry-tracked/telemetry sink"注释已改为实际行为;纯 hook seam 注释(datalog/cache-RCA 可挂载点)保留,无上报逻辑。`openai_compat.rs` UA 注释中的 "analytics" 措辞已改为中性的路由/缓存说明。**G6 复核为 0 命中**(sentry/posthog/segment/analytics,含 extensions)。
- **tuix 测试编译修复**:`event_loop/mod.rs` 测试模块中历史机械重命名残留 `atomgit_configcodingplan_config("model-b")`(E0425,函数不存在)已改为 `codingplan_config("model-b")`。此修复让 tuix lib-test 重新能编译,也因此暴露了一批存量红测试(见已知剩余项)。**该夹具已于 2026-09-09 随 tuix 侧 codingplan 剥离一并删除,本条仅作沿革。**

### [OBJECTIVE-6] 子代理并发双车道(worker / explore 独立信号量)— [DONE]

- 写车道与只读车道分离:`task` 工具(`tools/task.rs`,`TaskTool::max_concurrent` vs 新增 `max_concurrent_explore`,builder `with_max_concurrent_explore`)与 team 运行时(`team/manager.rs` `TeamRuntimeConfig` 同名字段,`delegate` 按 `TeamPermission::Worker` 分配 worker semaphore、其余分配 explore semaphore)各自持有独立信号量。
- 默认值:worker 车道保守(3,scope-confined 写活树);explore 车道更宽(8,只读不冲突,排查扇出不被 worker 预算节流)。
- 配置面:`[subagent]` 表 `max_concurrent`(写,默认 3,env `RUSTCODE_SUBAGENT_MAX_CONCURRENT`)与新增 `max_concurrent_explore`(只读,默认 8,env `RUSTCODE_SUBAGENT_EXPLORE_MAX_CONCURRENT`),serde 默认函数 `default_subagent_worker_concurrent`/`default_subagent_explore_concurrent`;装配与 env 解析在 `coding/src/parts.rs`(`subagent_runtime_knobs` 返回三元组)。
- 测试:`team/manager.rs` 双屏障/峰值并发测试证明两车道独立(worker=1 串行、explore=4 同发);`tests/team_runtime.rs` 与 `config/mod.rs` 断言默认值。
- **内置并行模板(默认开启)**:`SubAgentConfig.parallel_template`(默认 `true`,`/config` 可切,`ApplyPolicy::CapabilityReprepare`,镜像 `/think` 实时开关模式)。开启时 `resolve_external_subagents`(`coding/src/parts.rs`)自动挂载三个外部代理角色——`explorer`(codex / read-only)、`builder`(claude-code / accept-edits)、`reviewer`(codex / read-only)——并把 worker 车道并发下限提到 4;显式 `[[subagent.external]]` 同名条目优先(覆盖内置角色);daemon/headless 传 `allow_dangerous_context=false`(bypass 降级 fail-closed)。接入点:CLI/TUI(`cli/main.rs` 传 true)、clix(`code.rs`)、daemon(`kernel_runtime.rs` 传 false);ACP 通道(`acp/engine.rs`)用 `PrepareOptions::default()` 不挂外部角色。

## 当前架构事实

coding agent 目标调用链:

```text
CLI / TUI / daemon / background / ACP / clix code
                    |
                    v
       CodingRuntimeHandle / DriverCommand
                    |
                    v
                CodingRuntime
                    |
                    v
           rustcode-kernel Agent
```

- `CodingRuntime` 是 coding agent 运行时所有者;driver 不应重建第二套 live agent 生命周期。
- kernel `AgentCommand/AgentEvent` 是运行时执行边界。coding 产品 driver 用 `CodingRuntime`;其他业务 driver 可驱动其 L2 已装配的 kernel agent,但不得另建第二生命周期 owner。
- 上游 core legacy `AgentClient`/v1 engine/`rustcode-bridge` 已退役;生产代码不得重建同名兼容层。历史 core JSON 只由 daemon 私有 DTO 单向导入。
- `rustcode-kernel`/`rustcode-capabilities`/`rustcode-coding` 生产依赖必须保持 core-free。
- native `SessionManager/SessionMeta/SessionSnapshot/PresentationFile` 是唯一 session 持久化模型。

## IM 渠道 (2026-09-23 落地,改这块前必读)

IM 接入让用户在钉钉/飞书/企业微信的聊天里驱动本项目 agent:消息转发给渠道绑定的
project,回答回发同一会话。首发平台**钉钉 Stream 长连接**(客户端外连 WebSocket,
**零公网/零隧道依赖**;协议取自官方 dingtalk-stream SDK 一手材料,未臆断)。
参考 AgentCore 对照分析与分期方案见 `docs/plans/2026-09-23-im-integration-design.md`;
持续任务(schedule/loop/wakeup)见 `docs/plans/2026-09-23-continuous-agent-design.md`。

- **分层**:传输/协议/分片/续聊在 `crates/rustcode-cli/src/im/`(`mod.rs` trait +
  `dingtalk.rs` 适配器 + `bridge.rs` 分片与去重 + `dispatch.rs` 并发调度 +
  `commands.rs` 聊天命令 + `runner.rs` 单消息管线);进程级接线(`CliAgentRunner`
  调 headless capture)在 bin 侧 `im_runner.rs`,因 `run_native_headless` 是 bin 的
  `pub(crate)`——**lib 不准反向调 bin**。**并发语义(2026-09-29 起)**:每通道一个
  reader 任务 + 每 chat 一个 worker(单 chat 串行,会话绑定不被并发写)+ `Semaphore`
  全局并发上限(默认 3);`ImAdapter` 全方法 `&self`(DingTalk socket 在内部
  `tokio::sync::Mutex`),适配器经 `Arc` 共享;审批经 `ChatMailbox` 复用本 chat 队列,
  不再自行驱动 `next_message`(修复"审批等待吞掉他人消息")。
- **网关握手单一实现**:`capabilities/src/im_probe.rs`(feature `im = ["egress"]`,
  HTTP-only 不拉 WS 栈,出站走 `build_http_client` 单一工厂)。CLI 适配器委托它,
  daemon 测试路由也消费它——**禁止再写第二份握手**。WS 栈全仓只此一条
  (`tokio-tungstenite 0.24`,与 tunnel 同版本线,勿再引第二套)。
- **`rustcode im` 子命令**:`serve/add/list/check/remove/register/unregister/setup`
  (2026-09-23 起;`serve` 是前台服务循环,`--platform`/`--project` 过滤,
  run() 内联分发保退出码同 Schedule 模式)。管理处理器在 bin 侧 `im_admin.rs`。
  **2026-09-29 修订**:`serve` 不再是单渠道串行循环——多通道并行 serve(每通道独立
  任务),断线重连为每通道指数退避 1s→60s(`dispatch.rs` 的 `serve_forever`,取代旧
  "1s/5s" 两档),未实现平台跳过并报告不致命;渠道级 `allow_senders` 发送者白名单
  (空=不限制,非空时在 `handle_message` 边缘拒绝并回发 `ImSenderNotAllowed`,
  validate 标记空项/重复项;配置入口:`add`/`setup` 的 `--allow-senders a,b`,
  setup 无此 flag 时向导追问一次、留空=任何人,由 `normalize_allow_senders_input`
  拆分裁剪);聊天命令 `/help` `/status` `/project` 即时应答、`/new`
  清绑定开新会话(`commands.rs`);慢回合(>8s)先发 `ImTurnProcessing`、失败回发
  `ImTurnFailed`(原始错误透传)。`/stop` `/cd` 刻意未做(见 `commands.rs` 注释)。
  - `setup` 三步向导(对标 AgentCore 流程:建机器人 -> 配渠道 -> 验证):
    平台+project(project 缺省取 cwd,须为已存在的绝对路径) -> 逐字段收集
    凭据并过 `normalize_credential_input` -> **复用** `handle_im_add` 保存 +
    `handle_im_check` 实测网关;`退出码 0 仅当保存与检查都成功**,否则 1 并给
    可操作提示(凭据失败时说明 add 只做结构校验、实测交给 check/serve,
    且环境变量须在 `rustcode im serve` 的运行环境里设置)。纯校验函数可测,
    测试**不碰** `$RUSTCODE_HOME`;支持 `--platform/--project` 与凭据 flag
    非交互驱动。
  - `add <platform> <project>` 按 `(platform, project)` **upsert**(平台拼写归一化,
    否则 `DingTalk`/`dingtalk` 会被 validate 判重复);整渠道**替换**而非合并字段
    (用户最后传的即所存,无陈旧字段残留;不传 `--allow-senders` 的 upsert
    同样把白名单清空回"任何人")。
  - **凭据归一化是安全卡点**(`normalize_credential_input`):只接受 `$VAR`/`${VAR}`
    引用或裸环境变量名(自动补 `$`);`${VAR:-default}` 回退写法**显式拒绝**——
    回退值本身就是明文密钥,接受它会击穿"明文不落盘";其余字面量一律拒绝。
  - `add` **刻意只做结构校验**(凭据展开检查要求本 shell 已设变量,而 add 是
    staging 步骤);凭据实测由 `check`(网关探针,与 daemon test 路由同一实现)
    与 `serve` 负责,`list` 只回显 `env:` 引用永不展开。
- 凭据运行时走 config 的 `env:VAR` 展开,总开关 env `RUSTCODE_IM_ENABLED`(默认关,
  显式 `=0` 压制配置,解析单点 `config::im::im_enabled_from`,禁止各自读 env)。
- **OS 服务注册**(`im_service_os.rs`,`im register/unregister`):把渠道注册为
  **常驻服务**而非定时器——`serve` 是长连接,timer 形状会每 tick 拉起重复进程抢
  同一条平台连接。三平台形状:launchd `KeepAlive=true`+`RunAtLoad=true`;
  systemd user unit `Restart=on-failure`+`RestartSec=5`+`WantedBy=default.target`;
  schtasks `/SC ONLOGON`(Task Scheduler 无崩溃自启,崩溃后等下次登录——已知限制,
  不是 bug)。服务名按 platform 拼(`rustcode-im-<platform>.service` 等),platform
  拼写经 `checked_platform` 白名单(小写字母/数字/`_`/`-`)才进文件名。
  `CommandRunner`/`run_checked`/`xml_escape` 复用 `schedule_os.rs`(单一实现,
  勿复制);register 前先 `resolve_project` 校验目录存在,否则单元会在每次登录
  crash-loop。重装已有服务时明确报 `ImAdminReRegistered`(静默成功会掩盖
  已有单元在跑)。
- **config `[im]` 段**:`[[im.channels]]`(platform/project/enabled/各平台凭据),
  `validate()` 拒绝未知平台、缺 project、缺凭据、重复 `(project, platform)`
  (不静默 last-wins),并接入配置加载告警路径;`skip_serializing_if` 保证未启用
  的老配置零变化。
- **身份映射**:`rustcode-config/src/im_store.rs`,存储
  `$RUSTCODE_HOME/im/bindings/<platform>-<sha256(chat_id) 前16hex>.json`
  (**文件名必须是 hash**:chat_id 来自网络不可信,拼路径会路径穿越)。
  `upsert_preserving_session` 是续聊核心:已有绑定保 `session_id`,只刷
  `updated_at`——丢了它 IM 对话每次都失忆。群聊按 `chat_id` 而非 `sender_id`
  映射(同群所有人同会话)。会话打 `SessionOrigin::Im`(`manager.rs`)。
- **daemon API**(`api_im.rs`,凭据只回显 `env:` 拼写、永不展开回显):
  `GET /im/channels`(列表)、`PUT /im/channels`(整表替换+服务端 validate)、
  `DELETE /im/channels/:index`(update 锁内重验索引)、`POST /im/enabled`(只翻总开关)、
  `POST /im/channels/test {index}`(网关握手探针,响应只含
  `ok/platform/message/endpoint_host?`;`endpoint_host` 剥查询串,**dial ticket
  与展开凭据绝不进响应**;404 索引越界/400 平台未知或凭据缺失/200+ok:false 测试失败)、
  外加既有只读 `GET /im/status`、`GET /im/overview`。写路径全走
  `update_config()` compare-and-write(providers 同款)。
- **client 标识**:`client_mode.rs` 的 `CLIENT_HEADER = "x-rustcode-client"` 是
  单一事实源(`resolve_client_mode`/`ClientMode::wire()` 互逆,有 round-trip 测试);
  IM 侧发 `channel` tag,使 daemon 把该请求计入可交互权限
  (`client_interactive_permission` 白名单含 `Channel`)。**新增 client 类型改这里,
  别在中间件里再写字面量**。
- **WebUI**:侧栏设置菜单「IM 渠道」入口 -> `ImChannelsDialog`
  (`SettingsDialogs.tsx`),API 在 `webui/src/api.ts`(`getImChannels`/
  `putImChannels`/`deleteImChannel`/`postImEnabled`/`testImChannel`),文案键
  `im.*` + `settings.menuIm` 双语;「测试连接」对**已保存**配置实测
  (服务端读盘,非表单草稿),保存/删除/重排后旧判定作废。配置改动需重启
  `rustcode im` 进程(启动时读盘),面板有 restartHint 提示。
- **WebUI IM 记录栏目**(只读查看,2026-09-23 落地,2026-10-01 增强):侧栏 `ImGlyph`
  入口(含折叠态图标栏),仿 MCP 栏目的**懒加载 + 计数徽标**;三级面包屑
  `平台 -> 项目 -> 会话`(`webui/src/lib/imRecords.ts` 纯函数 + 单测),
  点击叶子会话走既有 `resolveSession` -> `onSelect` 复用会话查看器。
  **2026-10-01 增强(纯客户端,零后端改动)**:① 未读圆点——`lib/imUnseen.ts` 比对
  树内最新 `updated_at` 与 localStorage 的 last-seen mark(`rustcode.im.lastSeen`,
  关闭弹层时写 `markImSeen()`),展开态与折叠 rail 的 IM 入口都渲染 `.im-unseen-dot`;
  ② 平台行状态药丸——`imPlatformStatus()`(configured+enabled→enabled / configured
  但关→disabled / 未配→unconfigured)在平台名旁显示三色药丸,顶部加
  `可用渠道 n/total` 摘要行;③ 面包屑加 `‹` 返回键(`.im-back`,32px 触达 +
  focus-visible 环,与 `.im-crumb` 共用焦点规则);④ 渠道配置弹窗凭据字段收进
  `.im-cred-section` 虚线分组(标题写明 $ENV 引用契约),测试连接结果带
  `[OK]/[FAIL]` 标记与 endpoint_host 的底色行。新类契约钉在
  `lib/imChannelsStyles.test.ts` 第二个测试。
  **2026-10-01 第二批(对标 WorkBuddy 助理文档,会话来源标识 + 删除确认增强)**:
  ⑤ 会话 IM 来源标识——`SessionOrigin`(`manual/scheduled/im`,serde 小写)从
  `SessionMeta.origin` 经 `CatalogEntry.origin`(capabilities 新字段,legacy-only
  聚合读 Manual)带出到 daemon `SessionSummary.origin`(**加性 wire 字段**,旧
  webui 忽略未知键、旧目录条目读 manual),webui 会话行对 `origin === 'im'` 渲染
  `.session-origin-badge` 药丸(title 解释三平台);⑥ 删除渠道确认文案补齐影响
  说明(平台侧机器人仍在但消息不再接收、会话历史保留、其它渠道不受影响,
  对标 WorkBuddy「解绑后的影响」节)。**刻意不做**:daemon 侧查 OS 服务状态
  (daemon 与 `rustcode im serve` 可能不同机,语义不成立)、IM 弹层内解绑按钮
  (记录面板 2026-09-23 裁决「只读,无增删」,翻案需用户确认)、微信/QQ 平台
  (无一手协议文档,按铁律不臆断)。
  后端 `GET /im/bindings?platform=&project=&session_id=` 返回
  `{enabled,total,platforms:[{platform,known_platform,configured,channel_enabled,
  binding_count,project_count,last_active_at,projects:[{project,binding_count,
  session_count,last_active_at,bindings}]}]}`——**platforms 取「config 已配渠道」∪
  「im_store 实际绑定」的并集**,否则配置过但从未收到消息的渠道会从侧栏消失
  (应显示 binding_count=0);排序确定性(平台名升序/项目路径升序/绑定按
  updated_at 降序);纯函数 `build_im_bindings_response` 承载分组与过滤,handler
  只做读盘,测试完全不碰 `$RUSTCODE_HOME`。**只读,无增删**。
- **审批边界**:IM turn 背后有人(只是异步),`strict_unattended=false`,
  模式封顶 `AcceptEdits`(禁 `auto`)。P-IM2 交互式审批往返**已落地(2026-09-23)**:
  `run_native_headless` 收 `Option<&mut dyn ApprovalPort>`(main.rs Request 臂的
  决策序:skip_permissions 放行 -> strict 拒绝**不问** port -> 有 port 则一切升级
  **含 bash** 走聊天(legacy 的 bash 静默放行不得绕过可应答的人)-> 无 port 才回落
  legacy 规则);lib 侧 `im/approval.rs` 的 `ImApprovalRelay` 把 `ApprovalRequest`
  渲染成聊天卡片、轮询回复(`y/allow/允许`、`always/总是`、`n/deny/拒绝`,
  **严格全字匹配**,散文不解析)、120s 超时 fail-closed(刻意短于 kernel 默认 300s,
  让用户先从我们这里看到结果);exit 2(有拒绝)时把 agent 的解释文本回发聊天而非抛错。
  `-p` 与 schedule 路径传 `None`,行为不变。飞书**仅配置面**,适配器未实现
  (其长连接机制未取得一手文档,按铁律不臆断),serve 时显式报"未实现";
  企业微信已实现 WebSocket 长连接适配器(`im/wecom.rs`),serve 时正常接入。

## 持续任务 / 调度求值 (2026-09-25 起,改这块前必读)

分期方案与未开工项见 `docs/plans/2026-09-23-continuous-agent-design.md`(五期 P0–P3,
**严格串行** D4);本节的现状条目以代码为准。

- **`next_run()` 是调度求值的唯一实现**(`crates/rustcode-config/src/schedule.rs`),
  消费点两处:`crates/rustcode-cli/src/schedule_cmd.rs:456`(`schedule list` 的"下次运行")
  与 `crates/rustcode-tuix/src/event_loop/commands.rs:4996`(TUI `/schedule` 行)。
  两者都把 `None` 渲染成 `-`,**所以求值失败是静默的**——改这里必须同时看两个渲染点。
- **Cron 求值是手写的,刻意不引 `cron` crate**(决策 D1,最小化依赖):支持 `*`、`a`、`a-b`、
  `a,b`、`*/n`、`a-b/n`,限 `分 时 日 月 周` 五段;**不支持** `@daily` 等宏与 `MON` 等星期名
  (解析失败返回 `None`,即回落到 `-`)。星期 `0` 与 `7` 都表示周日,内部归一到 0。
- **dom 与 dow 都是 `*` 以外时走 OR 规则**(Vixie 语义):`0 9 1 * 1` = 每月 1 号**或**每周一,
  不是"每月 1 号且是周一"。只限制其一则是 AND。弄反会让任务静默少触发。
- **weekday 对齐靠 `civil_from_days` + `day_of_week`**(Hinnant civil 算法,周日=0)。
  `epoch / 86400` 的天索引**推不出星期几**,历史 bug 就是 `Weekly` 忽略 `weekday`、
  把"每周一 09:00"显示成"明天 09:00"。`weekday` 取值 1..=7(1=周一),与
  `schedule_os.rs` 的 OS 注册口径一致;越界(0 / >7)返回 `None`。
- **无 DST 处理**:全按 UTC 日/时算术。展示与 tick 判定够用,**精确触发仍归 OS 调度器**
  (systemd `OnCalendar` / launchd / schtasks,见 `schedule_os.rs`)。不要为了"更准"在这里加本地时区。
- **搜索有界**:`MAX_SEARCH_DAYS = 366 * 8`,`0 9 30 2 *`(2 月 30 日)这类永不发生的表达式
  返回 `None` 而**不会**死循环。
- **P0 已落地**(2026-09-25):上述 cron 求值 + weekly 对齐;`next_run_cron_is_none_in_phase1`
  这条"承认缺陷"的测试已改写为真实值断言。config `--lib` **365/0**。
- **P1 运行台账已落地**(2026-09-25):`RunRecord`/`RunStatus`/`RunTrigger` 落在
  `schedule.rs`,记录存 **`<task-id>/runs/<run_id>.json`**(D2 布局;既有 `list_in()` 按
  扩展名过滤天然不会把该目录当任务定义,有专项回归测试钉住)。读写面:
  `save_run`/`list_runs`(新在前)/`latest_run`/`prune_runs(keep)`,默认保留
  `DEFAULT_MAX_RUN_HISTORY = 20`。`run_id = <secs>-<nanos 九位>`——**字典序即时间序**,
  连续运行必不同。`ScheduleTask` 新增 `#[serde(default)] last_run_id`(旧任务 JSON 照常解析)。
- **台账写入是 best-effort 契约**:`run_task`(cli `schedule_cmd.rs`,**bin 侧模块**——
  `cargo check --lib` 不编译它,验证要 `cargo check -p rustcode` / `cargo test -p rustcode --bins`)
  在启动前写 `Running`、终态回写 `finished_at`/`exit_code`/`session_id`/`summary`
  (capture 末行截 200 字)。**退出码是 OS 调度器唯一的失败信号,台账失败绝不能影响它**
  (`tests/schedule_run_exit_code.rs` 钉住)。
- **残留(如实登记)**:OS 调度器与手动 `schedule run` 共用同一命令行,这两条路径的
  `trigger` 一律记 `Manual`;`Daemon` 变体由 P2 tick 使用;`Im` 变体由 2026-09-29 起的
  IM 聊天台账使用(`im/runner.rs`,每条消息一条,`best-effort` 不影响回合,存储布局
  与定时任务一致:`im/runs/<platform>-<sha256(chat_id) 前 16>/runs/<run_id>.json`)。
  **`OsScheduler` 变体仍空置**(留给未来显式标记)。
  另:设计文档 §4.1 的 `skipped_because_of` 字段**未新增**,超窗原因折进 `summary`
  (记录在案的偏差,避免扩大 `RunRecord` 的加性面)。
- 消费面:`rustcode schedule history <id> [--limit N]`(空/无记录双语提示;`status` 是
  running/success/error/cancelled/skipped 机器 token 不译)+ TUI `/schedule` 每任务行下的
  `最近运行` 摘要行。
- **P2 已落地**(2026-09-27):`[schedule]` 配置段(`enabled` / `daemon_tick` /
  `tick_interval_secs` / `catch_up_window_secs` / `max_run_history`,**默认全关**;
  `skip_serializing_if = "ScheduleConfig::is_default"` 保证未触碰时**不写回**用户 config.toml)
  + 5 个 `RUSTCODE_SCHEDULE_*` env(名字落在 `endpoints.rs`),单一解析入口
  `config::ScheduleConfig::resolved()`(env 显式值 > 文件 > 默认,随后夹取
  tick `[10,3600]`、history `[1,1000]`;`catch_up_window_secs = 0` 表示**永不判超窗**)。
  新增子命令 `rustcode schedule tick [--once]`(`--once` 供外部 cron / daemon 调用)。
- **单飞锁是 `run` 与 `tick` 共用的**:`<task-id>/.lock` + fs2 `try_lock_exclusive`,
  在**任何台账写入之前**获取;拿不到即跳过(busy),**绝不排队、绝不并发跑两次**。
  这把锁也是"daemon tick 与 OS 定时器同时到期"的唯一防线。
- **补跑语义是单一谓词** `schedule::within_catch_up_window(due_at, now, window)`:超窗
  **不执行**,写 `RunRecord{status: Skipped}` 并把 `last_run_at` 前移到 `now`(否则每个
  tick 都会重记同一次失约)。P3 恢复唤醒必须复用该谓词,不得另写一份比较。
- **陈旧 `Running` 回收**:`reap_stale_running(task_id, now)` 只在**拿得到锁**时把 `Running`
  改写为 `Error`(锁被活进程持有时返回 0),避免 history 永久显示"运行中"(违反"每次运行
  都到终态"不变量)。tick 在 claim 之前调用它。
- **daemon tick 的执行方式是子进程,不是进程内装配**:`ServerOpts.schedule_tick`(仅
  `rustcode daemon` 与独立 `rustcode-daemon` 置 true;进程内 `/webui` 与隧道服务器为 false)
  为真且配置 `enabled && daemon_tick` 时,每 `tick_interval_secs` 在"有 due 且未被锁持有"
  时拉起 `<rustcode> schedule tick --once`。理由:`spawn_native_cli_runtime` /
  `run_native_headless` 在 CLI bin 侧,daemon **不得**依赖 `rustcode-cli`(L3↔L3 禁止);
  子进程正是 OS 调度器同款入口,全仓只有**一份**"运行定时任务"实现。可执行文件定位:
  `current_exe()`(名为 `rustcode`)、`rustcode-daemon` 取同级 `rustcode`;可用
  `RUSTCODE_SCHEDULE_TICK_BIN` 覆盖重命名安装。
- **双触发防护是双向的**:`daemon_tick` 为真时 `schedule add` 打印显式警告(该任务同时注册
  在 OS 调度器上,两侧都会触发);`schedule sync --unregister-os` 是一次性迁移开关——
  它**刻意不走 reconcile**(走 reconcile 会把刚卸下的任务立刻重装回去)。
- 门禁(config `--lib` **383/0**、cli `--bins` **131/0**、daemon `--lib` **320/0**、
  `cargo fmt --check` 三 crate 干净、clippy 对本次改动文件 0 新增命中)。
  **P2.5(DAG + agent 派生 + 事件触发) 已落地**(核心算法随 e6ba396e/9db5d18e 落地；2026-10-11 补齐人类侧 CLI 编排：`schedule add --depends-on/--triggers` 保存前环检测、`schedule validate` 只读校验、`schedule list` 显示依赖；同日补齐 TUI `/schedule` 写操作（add + validate）)；WebUI 只读路由仍属 G13 其余子项，未开工；P3(可持久化唤醒) 仍未开工。

## 架构方向

- 单一状态所有权、清晰依赖方向、可验证兼容性;已删除的 core 不得以 facade、兼容 crate 或复制状态所有者方式回流。
- driver 负责输入/展示/传输/本地操作;coding runtime 负责业务生命周期;kernel 只负责中立 agent 循环;capabilities 提供可复用能力实现。
- 问题修复必须检查同一状态所有权、协议边界和受影响 driver,优先修共同根因。

## Runtime 生命周期不变量

涉及 submit/steer/cancel/approval/request/compact/provider reload/session resume/fresh/undo/cd/goal/loop/shutdown 时,必须检查:

- live `AgentHandle`、config、parts、provider、session binding、generation、pending request、snapshot broker、controller 是否仍由单一 runtime owner 管理。
- session id、working目录、snapshot、provider 选择、审批 grant、gateway affinity、持久化目标在重建前后是否保持。
- build/prepare/assemble/restore 任一步失败时是否显式失败/回滚,而非静默 fresh、空 snapshot、noop handle 或假成功。
- pending approval/request 在 cancel/reload/session switch/shutdown 时是否 fail-closed。
- 旧 generation 迟到事件是否污染 replacement runtime。
- 每个 accepted operation 是否都有 success/error/cancel/replace/shutdown 终态。

涉及 turn completion 或 compaction 时,先复核 `LifecycleHooks::turn_complete`、kernel 终止路径与 `rustcode-capabilities` compaction 实现;无证据证明 seam 缺失前不得新增重叠 hook 或第二压缩状态机。

## 历史兼容面维护

`rustcode-core` 已退役;后续兼容只允许围绕仍保留的单向 importer 与明确 wire DTO:

1. 明确当前数据/状态的唯一 owner;
2. 找全持久化格式与兼容入口;
3. 历史格式只能作边界清晰、可测试的单向 importer;
4. importer 消费者归零后删除对应 DTO/转换/测试;
5. 禁止恢复 legacy writer、双向转换、运行时 fallback 或新 core facade。

**[2026-09-09] codingplan 退役带来的持久化语义变更**(用户裁决 Q2' 授权;config.toml 的 schema
与键名完全不变,旧文件照旧解析,不迁移、不改写用户磁盘):

1. **账号折叠消失** —— 每个 providers 表键各自投影成同名账号,不再按 wire format 折叠成共享合成
   账号;逻辑账号 id 由「分组 id」变为「provider 键名」,引用旧分组 id 的 UI/日志/后续任务需改用键名。
2. **旧 AtomGit 前缀兼容消失** —— 磁盘上已有的 AtomGit 系列键仍能正常加载可用,但降为普通自定义
   provider:不再只读、不再折叠、不再被登录流自动接管。
3. **内置 effort 回退消失** —— 未持久化 reasoning_effort_levels 的模型不再被注入内置档位,现返回
   「不限制」(五档全开),用户已持久化的档位也不再被夹取。默认构建下原网关判定恒为假,故对绝大多数
   用户无实际差异。
4. **签名网关识别消失** —— 没有任何 base_url 会被判为托管/签名网关,所有 provider 一律纯 bearer
   鉴权;三个 RUSTCODE_CODINGPLAN 系列环境变量变为无效(设置后被直接忽略,不报错)。

没有任何 config.toml 键被删除、改名或迁移,也不存在静默 fresh:以上变化全部发生在只读投影层与
解释层。行为对照与测试落点见 .codebuddy/artifacts/2026-09-09-codingplan-removal-eval/03-impl/T-23.md。

## 编码约束 (fork 硬性)

- [STYLE] 严禁 Unicode Emoji;状态/日志/注释/输出一律 ASCII 标签。
- [ASYNC] 保持 tokio async/await 一致性;async 链路禁止阻塞 I/O。
- [SECURITY] 严禁硬编码真实 API Key/Token/敏感内部端点;默认配置与测试用 `env:VAR` 或占位符。
- [STREAMING] LLM client 必须原生支持 SSE 流式与非流式;Anthropic 与 OpenAI chunk 差异统一映射为内部 `StreamEvent`。
- [ERROR] 用 `thiserror` 定义模块级强类型错误,顶层用 `anyhow` 包装;禁止裸 `.unwrap()`/`.expect()` 导致 panic(测试与明确不变量处除外)。
- [DEP] 清理遥测后同步检查 `Cargo.toml`/`Cargo.lock`,最小化 `reqwest`/`tokio` 等共用依赖 feature。
- **[I18N] 用户可见文案一律走 `rustcode-config` 的 i18n 目录**(`src/i18n/{messages.rs,en.rs,zh_cn.rs}`),**默认语言是简体中文**。`Msg` 变体在两个语言文件里都有 arm,漏一个就编译不过——**parity 由编译器强制,这就是这套设计的目的**,不要绕开它:
  - **禁止新建 `fn l(en, zh)` / `if zh {...} else {...}` 之类临时双语 helper**,也不要在 `format!` 里直接写中文散文。需按终端能力选语言时用 `t_with(locale, msg)`。
  - **Rust 侧三件套的边界(改错地方会制造跨层污染)**:L0 `rustcode-kernel` **零文案**——它只发结构化枚举(`RetryReason` / `AgentNotice` 等,带 `machine_token()` 与英文 diagnostic),**不得调 `t()`**;本地化在 L2 `rustcode-coding` 的单点 chokepoint(`localize_agent_notice` / `retry_reason_label` / `localize_kernel_event`)和 driver 边缘完成。kernel 之外各层按此分层,别把中文塞回低层。
  - **不译的固定面**:机器码 / `code` 字段与稳定 token、工具名与 JSON 键值、HTTP 方法与路径、配置键名与路径、模型面文本(persona、工具描述与结果)、CLI 命令名与 shell 示例、`y/yes/always/n` 判定 token、各文件格式约定。**原始错误串与 `{error}` 一律原样透传**,只在外面包一层本地化前缀。
  - 细节(锁的两种用法、改文案后要跑整个 crate 的 `--lib` 等)见「环境约束与已知坑」。

## 修改前检查

涉及 runtime 生命周期、公共协议、持久化、安全边界、跨 crate 依赖或兼容面退役时,开始修改前必须:

1. 记录当前 branch、commit SHA 和 worktree 状态;
2. 搜索目标符号的生产方、消费者、持久化点和转换边界;
3. 查看相关文件近期 Git 历史,确认任务未已实现或改变方向;
4. 写明状态 owner、目标边界和失败语义;
5. 若为退役任务,写明预计删除的旧 surface,而非仅新增内容。

## 验证与交付

- 修改过程中运行最小相关测试;一个逻辑单元完成后跑受影响 crate 测试。
- 纯文档/注释/格式修改可不跑测试,但必须检查 diff 与文档内部一致性。
- runtime/协议迁移按实际影响覆盖 CLI/TUI/daemon/headless/background/session resume/approval/cancel/provider reload/持久化兼容;不受影响入口无需机械重复验证。
- 退役任务最终说明必须含:验证基线、四态、实际删除项、仍保留的 importer/legacy surface、测试结果、唯一下一步。

## 门禁 (AGENT-D)

```text
G1  cargo fmt --check
G2  cargo clippy --workspace --all-targets -- -D warnings
G3  cargo test --workspace
G4  ./scripts/test-headless.sh                    (需先 cargo build)
G5  python3 scripts/acp_smoke.py
G6  grep -riE "sentry|posthog|segment|google-analytics|googletagmanager|mixpanel|amplitude"
    --include=*.rs --include=*.toml   必须 0 命中(rustcode-telemetry 已删除)。
    注意该正则会把英文单词 `segment`(路径段/正文分段)与第三方 MCP 推荐文档
    (skills/.../mcp-servers.md 中的 "Sentry MCP")算成命中,属误报,须人工判定。
    `telemetry` 字样不作为 G6 判据——残留见 OBJECTIVE-2 的三类守卫清单。
G7  grep -rni "atomcode" crates/ scripts/ .github/   0 命中(描述已退役 core 的
    历史注释除外,须逐条人工确认确属历史名)。`atomgit` 字样仅允许三类:
    (1) opt-in `atomgit` Cargo feature(capabilities/src/atomgit/、tools/atomgit*、
        以及 persona/parts 里 `#[cfg(feature = "atomgit")]` 的工具装配/人设注入);
    (2) 旧 `AtomGit-*` provider 前缀兼容(is_codingplan_provider_name /
        LEGACY_CODINGPLAN_PREFIX,旧配置键仍需识别,勿删);
    (3) fork 自己的发行主页 gitcode.com/SecLab/RustCode。
G8  grep -rni "atomcode" docs/architecture.md   0 命中(描述已退役 core 的历史
    小节除外;AGENTS.md 本身保留重命名映射表与历史名引用,不参与此门禁)
```

**[G7 条文修订 2026-09-09] 上面代码块第 (2) 类豁免已作废;执行 G7 时该类一律以本节为准。**

**改门禁前必读**:G1–G3 三行是**可执行真值**,但 **G6/G7/G8 代码块的字面受 `scripts/check-zh-docs.py` 的 AC-4 code span 判据冻结,不得直接改动块内文本**——需要修订时按上面 G7 的做法,在块外写一节修订说明覆盖块内条文。

上方代码块受文档门禁冻结(scripts/check-zh-docs.py 的 AC-4 code span 判据不允许改动其字面),
故修订以本节形式落地:读到代码块第 (2) 类「旧 AtomGit- 前缀兼容…旧配置键仍需识别,勿删」时,
必须替换为本节结论。依据是用户裁决 Q1=B 与 Q2'(裁决原文见
.codebuddy/artifacts/2026-09-09-codingplan-removal-eval/STATUS.md 的「用户裁决」节)授权彻底
移除 codingplan:该类点名的两个豁免符号 is_codingplan_provider_name 与
LEGACY_CODINGPLAN_PREFIX 已随之删除(实测 crates 下 rs 文件对 codingplan 不区分大小写命中
7 行 / 4 个文件,均不含这两个符号),旧 AtomGit- 前缀兼容逻辑不再存在。故 atomgit 字样现只
允许两类:(1) opt-in 的 atomgit Cargo feature —— 即 capabilities/src/atomgit/、tools 下的
atomgit 系列工具,以及 persona/parts 里按该 feature 门控的工具装配与人设注入;
(3) fork 自己的发行主页 gitcode.com/SecLab/RustCode。原第 (2) 类若再出现命中,一律判为残留
而非豁免。两条 grep 模式本身(atomcode)不变,G7/G8 判据不受影响。

**[SUPERSEDED 2026-09-09] 本文件中所有「codingplan 相关面按 fork 铁律保留、门控不删除」的结论整体作废。**
被推翻的结论包括:codingplan Cargo feature/cfg 门控、`LEGACY_CODINGPLAN_PREFIX`/`is_codingplan_provider_name`、签名网关识别器 `is_codingplan_llm_gateway` 及三个 `RUSTCODE_CODINGPLAN_*` 环境变量、Cp 前缀 i18n 族、扩展侧 `/codingplan/setup` 客户端方法——均已于 2026-09-09 删除,详见 `docs/archive/`。
**边界(勿扩大解读)**:托管 QR 登录流**已随 `rustcode-auth` 删除**——`platform_server()` 与
`managed_login_available()` 一并移除,OAuth 扫码登录屏不再有可达入口(`onboarding_wizard.rs`
明示 "QR sign-in fast path is gone with managed `/login`");`render/qr.rs` 的 QR 渲染器保留,
现仅服务于 `/app` 移动端配对(`AppPairQrBlock`,`event_loop/commands.rs`),与平台身份无关。
下方各轮次记录保留原文作为沿革,与本节冲突时一律以本节为准;被裁决直接点名的条目已就地标注。
刻意保留的 codingplan 残留之一是卸载清理项(cli/src/uninstall/paths.rs 与 scripts/uninstall.sh、
scripts/uninstall.ps1 中的 codingplan_sync.json 文件名),理由同上文保留旧 telemetry 目录名的先例:
那是真实存在过的历史文件,删清理项会让老用户残留孤儿文件。
i18n 三件套(messages.rs / en.rs / zh_cn.rs)的 Cp 前缀变体与 kernel 注释已在本次同步期间随 i18n
收尾任务落地,实测这两处均 0 命中。crates 下现存的 codingplan 字样为 7 行 / 4 个 rs 文件
(2026-09-09 实测,不区分大小写),全部属于下列三类刻意保留,不得当残留清理:
① 卸载清理项(见上,cli/src/uninstall/paths.rs 两处);
② 负向回归断言(cli/src/main.rs 两处,断言补全脚本与 login 帮助文案里不出现该字样);
③ 上游 403 错误体识别与其测试夹具(capabilities 的 provider/mod.rs 一处、openai_compat.rs 两处)。
另有 crates/rustcode-daemon/README.md 的历史小节(已就地标注"已于 2026-09-09 移除")。
早先记在 ③ 的 capabilities/src/provider/error.rs 与 cli/src/vision.rs 两处现已 0 命中。
全量验证(T-31)尚未完成,最终残留清单以测试工程师的报告为准。

**[CHECK] CI 已补齐**:`.github/workflows/ci.yml` 已创建,在 push/PR 到 `main`/`dev` 时触发 G1(`cargo fmt --check`)、G2(`cargo clippy --workspace --all-targets -- -D warnings`)、G3(`cargo test --workspace`)三个核心 job,并补齐 G4(`headless-smoke`)、G5(`acp-smoke`)、G6/G7(`no-telemetry`)、G8(`no-stale-naming`)四个 CI job。`ci.yml` 共 **9 个 job**——上述 7 个(覆盖 G1–G8)之外还有 `branch-protection`(见上文四层保护 1)与 `release-gate`(见四层保护 4),别把 `ci.yml` 记成只有门禁那 7 个。G2 已收紧为 `-D warnings`(clippy warnings 已全部收敛为 0)。`build.yml` 仍只管 release 构建。
   注意仓库里有**两个** CI 入口,别只看一个:`check.yml`(`name: check`,push 到 `main`/`release/**` + 任意 PR + 手动触发)另跑一套——`gate` job(`cargo check --workspace --all-targets` + `cargo test --workspace`)与 `lint` job(`cargo fmt --all -- --check` + `cargo clippy --workspace --all-targets -- -D warnings`,两步都**无** `continue-on-error`,即都阻塞)。**注意 `lint` job 的显示名写作 "fmt (blocking) + clippy (report only)" 是过期措辞**:实测 clippy 步骤没有任何豁免开关,`-D warnings` 会真红,别据 job 名以为 clippy 可忽略。两份工作流的重叠命令以 `ci.yml` 为对外口径;`check.yml` 里的 `cargo test --workspace` 不带 `-j 1`(CI runner 内存足够),**本地复现其红必须自己补 `-j 1`**,否则会撞上本文件的 8GB cgroup 限制而拿到假红。另外 `.github/workflows/` 下不全是工作流:`create_tag_release.py` 是被 `build.yml` 调用(6 处)的 Release 上传脚本,读 `RUSTCODE_RELEASE_*` env、缺省用脚本内置默认(即本 fork 自己的发行主页),别把它当成本仓库的 workflow 入口。

### 门禁执行要点

- **G1 会因未提交的 WIP 而红**——先 `git status` 看清是谁的改动,别把别人(或并发会话)的未格式化文件当成自己的问题;格式化用 `cargo fmt -p <包名>`,裸 `cargo fmt` 会波及全工作区。注意 **cli 的包名是 `rustcode`**。
- **`trust_key_golden_matches_core_algorithm` 已不再是恒红**。历史上它因 `project_trust_key` 用 `std::collections::hash_map::DefaultHasher` 而被判"跨工具链不稳定、铁律禁改",但现实现已换成**固定 golden**(`"e07a86b0ce8a1c59"`),实测通过。本文件下方多处把它记为「唯一失败 / 文档化已知红」的条目**均已过期**,若它变红请当作真回归排查,不要以"已知红"为由跳过。
  另注意该测试是 `#[cfg(unix)]` 且**位于 `mcp` feature 之后**(`mcp` 非默认 feature)——`cargo test -p rustcode-capabilities --lib` 根本不编译这个模块,要复现/验证必须 `--features mcp`。
- **G3 必须 `-j 1`**(见「环境约束与已知坑」的内存与端口两条),且 `--no-fail-fast` 才能拿到完整失败清单。
- **纯格式证明用去空白比对**:`git diff -w` **不能**用来证明格式改动无语义影响(它不忽略 rustfmt 的换行合并)。正确做法是剥离**全部**空白字符后比对字符序列(`''.join(text.split())`)。

## 已知剩余项 (follow-up, 非重命名必须)

- ~~`extensions/` 旧名~~ — **已清零**(vscode/jetbrains 均已改为 rustcode,见 OBJECTIVE-5)。`site/` 静态文档站此前残留大量 `gitcode.com/SecLab` install/clone/npm-scope/marketplace 链接与 `gitcode.host`/`gitcode.com` CDN 截图、`referral.html` 邀请奖励 SPA(硬编码厂商 ACS 后端)——**已于 2026-08-31 全部去平台化**(见下方发行链路条目):install 改"发行渠道获取 + `RUSTCODE_RELEASE_BASE=...`"、clone 改 `example.com`、npm scope 统一 `@rustcode/rustcode`、marketplace 改自有渠道、CDN 图改内联 SVG/data-URI、`referral.html` 替为中性占位页、`search-index.{zh,en}.json` 经 `node build-search-index.mjs` 重生成;站内颜色 emoji(✅/❌/📋/📎/💬)一并 ASCII 化。站内剩余 `*.rustcode.dev` 导航链接是本项目**自有重命名域名**(品牌),非厂商主机,保留。
- `cargo clippy --workspace --all-targets -- -D warnings` **已全绿**:存量告警由 2026-09-29 的 `fad6fd5c` 收敛完毕,且未用全局 allow 兜底。CI 的 clippy job 即以此为判据(无 continue-on-error),**新增代码不得引入任何 warning**。另注:`ci.yml` 的 `KNOWN_RED_TESTS` 仍列 `trust_key`,而该用例自 2026-09-25 起在 `--features mcp` 下已转绿,属待清理的陈旧白名单。
- **[CHECK] `mcp::registry::tests::trust_key_golden_matches_core_algorithm` 当前是绿的**(2026-09-25 复测:加 `--features mcp` 单跑 `ok. 1 passed`)。它历史上被记为"跨工具链不稳定的文档化已知红",但那个判断是**误诊**——golden 值 `e07a86b0ce8a1c59` 是改名前的字面量 `/tmp/rustcode-trust-golden` 的哈希,重命名改了字面量却没动常量;`crates/rustcode-capabilities/src/mcp/registry.rs:1509-1524` 的注释与 `crates/rustcode-config/src/util.rs:107` 的 `stable_project_hash` 姊妹测试已把这条钉死。**下方沿革里所有把它记为「唯一失败 / 已知红」的条目均已过期**;CI 的 `KNOWN_RED_TESTS` 白名单里仍列着它(空匹配不影响判定),别据此以为它必红。另注意该测试是 `#[cfg(unix)]` 且**在 `mcp` feature 之后**(`mcp` 非默认)——`cargo test -p rustcode-capabilities --lib` 根本不编译这个模块,复现/验证必须 `--features mcp`。
- **[DONE] `rustcode-capabilities` lib 存量红测试已收敛**(2026-08-31):
  - `cc_hooks::tests::turn_complete_payload_alignment`:测试自身缺陷——同一 `&&` 链中两个 `grep` 共享 stdin,首个 grep 抽干管道致第二个必失败;改为先 `cat > payload.json` 再对文件断言。
  - `tools::read::tests::large_{non_code,symbolless_code}_..._bounded_page`:断言停留在旧 300 行分页,实现已为 1500 行页(`DEFAULT_READ_LIMIT`);夹具改为 1600 行并对齐 `Continue with read_file({"limit":1500,"offset":1501})` 格式。
  - `subagent/claude_code`、`subagent/codex` 在全 workspace 高并发下偶发 `SpawnFailed("Text file busy (os error 26)")`(overlayfs/容器内新写脚本 execve 的 ETXTBSY 竞态,Go fork/exec 内置重试而 Rust std 没有):新增 `process_utils::spawn_retrying_etxtbsy`(8 次退避重试),接入 `subagent::proc::ManagedChild::spawn` 与 `cc_hooks::run_command_hook`。
- **[DONE] `rustcode-tuix` lib 存量红测试已全部修复**(2026-08-31,多 agent 协作):从 2008 passed / 65 failed 收敛到 **2053 passed / 0 failed**(`cargo test -p rustcode-tuix`;`rustcode-review` 100/0)。根因是平台中立化重构时 TUI 渲染串被**机械 ASCII 化**:Unicode 排版字形(分隔符 `·` U+00B7、省略号 `…`、输入尖括号 `❯`、菜单 `▸`、工具圆点 `●`、spinner `◐/⠋`、状态 `⚠/ⓘ/⏸`、树形 `└`、箭头 `→/↑/↳`、勾叉 `✓/✗`)被改成 ASCII 占位,而上游测试断言的是 Unicode。修复原则(遵循 `glyph.rs` 政策):**渲染器在 `unicode_symbols` 分支恢复 Unicode**,dumb terminal / legacy conhost / `LANG=C` 仍由 `glyph::downgrade_glyphs` / `ascii_for` 降级为 ASCII;测试夹具是 `en_US.UTF-8 xterm-256color`(`caps_with_color()` 推得 `unicode_symbols=true`),故断言对齐到 Unicode,**测试未被削弱**。注意 `·` U+00B7 刻意**不在** downgrade 表里(几乎所有终端都能渲染,无条件透传)。刻意保留 ASCII 的只有:替换表情符号的方括号标签(`[+]/[-]/[*]/[!]/[INFO]/[Y]es`)与 config 层 tagged 模板(`TurnSummary`/`LoopRound`/`[x]` 停止/拒绝等)。`rustcode-review/src/review_tool.rs` 同款 `·` 分隔符一并恢复。此批红测**不是默认中文改动导致**——断言英文串的测试均显式 `i18n::test_lock()` + `set_locale(Locale::En)`。
- **[DONE] 平台中立化收尾 + headless provider 预检**(2026-08-31,多 agent 协作):
  - **真实 bug 修复(G4 T5b)**:headless `-p` 在无 provider 或 `--provider <不存在>` 时,`ProviderBootstrap::Required` 会让 `provider_factory.build()` 以空 `base_url` 的 OpenAI 适配器"真空成功",随后在 reqwest 处报含义不清的 `relative URL without a base`。现于 CLI headless 路径加 `headless_missing_provider_message()` 预检:解析后 `runtime_cfg.model.is_empty()` 即 bail,给出可操作报错(指名请求的 provider、指向 config 路径、提示无参启动做交互配置),判定与 TUI onboarding 一致。新增单测 `headless_missing_provider_message_fires_only_without_resolved_model`;G4 T5b 由"reqwest 报错"变为"provider lookup 失败 exit=1"。
  - **docker 中立化**:`Dockerfile-Daemon-Tosslib` 基础镜像从内网 `swr.cn-north-4.myhuaweicloud.com/gitcode-be/...` 改为公共 `debian:bookworm-slim`;三个 Dockerfile 硬编码的 aliyun APT 源改为**默认空、按需 `--build-arg APT_MIRROR=` 注入**(默认走 Debian 官方源);`docker-compose.yml`/`docker/README.md` 内网镜像仓库地址改 `your-registry.example.com/...` 占位、"GitCode App" 改中性"移动端 agent 应用"、`⚠️` 改 `[WARN]`;`docker/config-example.toml` 默认 provider 从 openrouter 改为 `my-provider` + `api.example.com` 模板。
  - **扩展/前端/夹具**:`extensions/vscode` `/config` 帮助片段、`webui` 模型输入框 placeholder、`extensions/jetbrains` SSE 测试夹具 URL 从 deepseek 改为 `your-model-id` / `api.example.com`;`crates/rustcode-coding/examples/run_task.rs` 去掉 DeepSeek 默认端点,`RUSTCODE_BASE_URL`/`RUSTCODE_MODEL` 改为必填(未设则退出并提示);i18n 的 Base-URL 引导提示改 `api.example.com`。
  - **凭据/平台文档**:`docs/dev-env-setup.md`、`DEVENV.md` 原为 Huawei Cloud EulerOS + CodeArts 专用笔记,且**硬编码了疑似真实的 `CODEARTS_CLI_AK/SK`**(已全仓清除,grep 0 命中)。重写为平台中立:适用范围改通用 Linux/macOS,删 CodeArts/arkcli 等厂商云 CLI 步骤,tokenhub/hwdevspace/`openpangu` 网关示例改 `gateway.example.com` + `${MY_PROVIDER_API_KEY}` 环境变量注入,修正 `cargo run -p rustcode-cli`(包名实为 `rustcode`)为 `cargo run` / `-p rustcode`;`scripts/dev-env-quickstart.sh` 的 `✅` 改 `[SUCCESS]` 并同步修正 cargo 命令;`docs/codex-claude-config-analysis.md` 的 tokenhub 端点一并中立化。
  - **预设中立默认**:`provider_preset.rs` 的厂商预设(deepseek/openai/anthropic/qwen/ollama 等)与 `docs/config.example.toml` 的多 provider 示例都是**第三方 BYO 自带密钥**配置,正是"只保留第三方配置"目标要求**保留**的,不算平台绑定;平台绑定特指签名网关/托管端点(已统一为 example.com 占位或 `RUSTCODE_*_BASE_URL` 显式 env)。但预设**显示顺序**原先把 `taotoken`(某商业 token 转售商)放在索引 0,TUI 的 `preset_idx_by_id` 防御性 fallback(`unwrap_or(0)`)也会落到它身上。已把两个通用 `*-compatible` 自带端点预设移到 `PRESETS` 最前(索引 0 = openai-compatible),厂商预设随后;新增测试 `generic_endpoints_lead_the_registry` 锁定"索引 0 必须是中立自定义端点",TUI fallback 注释同步。`preset_or_compatible` 对未知 id 本就回落到 `OPENAI_COMPATIBLE`。
  - **运行时无厂商默认**:全仓排查确认生产代码路径**没有**硬编码默认 model/provider/base_url 会把用户导向某厂商——无配置时 headless 预检直接 bail(见上),预设全为 opt-in 手选;`retained.rs` 等测试夹具里的 `glm-5`/`deepseek-v4-flash` 仅作渲染显示数据,`vision.rs`/`kernel_runtime.rs`/`provider_factory.rs`/clix `SAMPLE` 里的厂商模型名均在 `#[test]` 内且端点为 `example.test`/`127.0.0.1` 桩,非默认值、不影响行为。
  - `.gitignore` 里 `.codeartsdoer/` / `codearts.zip` 是**防凭据入库的保护性忽略规则**,保留。
- **[DONE] 全仓 emoji ASCII 化扫尾**(2026-08-31,多 agent 并行):
  - **文档(子 agent)**:脚本化把 `docs/` 下 ~49 个 md 的装饰性/状态 emoji 转 ASCII——表格 `✅/❌→[+]/[-]`、编号完成清单 `✅→[x]`、banner `⚠️→[!]/[WARN]`、装饰 `✨/🎉→[*]`,并剥掉残留 U+FE0F;fenced 代码块与 TUI 字形设计稿受保护,表格管道数逐一核对不变。`hooks.md`/`hook-architecture.md`/`async-webhook-{summary,guide}.md`/`hook-expansion-summary.md` 等通用文档已 0 装饰 emoji。
  - **扩展/前端(子 agent)**:vscode/jetbrains 扩展与 webui 共 12 文件——`📋⚙🗑✎📄📁🔧⬆⚡☕📝🌐🐛🧪💬🧠🔍🔌🔟` 等图形 emoji 全部删除或改 ASCII 标签(`[#]/[X]/[EDIT]/[F]/[D]/[=]/[*]/[KEY]/[~]/[!]`),U+FE0F 残基清零;JetBrains 齿轮菜单生产标签在 `RustCodeBundle*.properties`(9/10 此前已迁移,本轮补齐 `gear.settings`),测试 `GearMenuLabelsTest.kt` 同步锁定到实际标签。
  - **顶层/CI(主 agent)**:`README.md` 与原中文 README 的贡献 bullets 与捐赠行、`extensions/vscode/README.md` 能力 bullets、`.github/workflows/build.yml` 步骤标记 `🔟→[10]` 均 ASCII 化;捐赠行顺带去掉"Coding Plan 免费"这类托管服务口径。
  - **刻意保留(有界例外)**:① TUI 终端状态点**设计稿**(`docs/superpowers/{plans,specs}/2026-07-03-terminal-status-glyph*.md` 与 `...-round-cap-checkpoint.md`)里的 `🟢/🟡/🔴` 是该彩色状态点特性的**规格主语义**(实际渲染为 `●` + ANSI 色),ASCII `[+]/[-]` 无法表达颜色,故保留——仅此 3 个视觉规格文件、仅这 3 个彩色圆点;② 排版类标记 `✓/✗/⚠(无 FE0F)/→/·/●/❯/☐/☑(线框)` 在浏览器/JCEF/终端等 unicode 能力端与 TUI 字形政策一致,保留;③ `tab-title-truncation.test.ts` 的 `🎉` 是被测输入;④ AGENTS.md 里 backtick 包裹的字形名是字形政策文档引用。新增 UI/文档一律用 ASCII 标签,不要再引入图形 emoji。
- **[DONE] 发行/安装/打包/CI 功能面去平台化**(2026-08-31,多 agent 协作):此前的中立化聚焦 LLM/relay/marketplace 运行时;本轮清掉**发行链路上仍硬编码的厂商主机/账号**,原则统一为"发行主机一律由 env / 运营方注入,构建里不带厂商默认":
  - **安装器** `scripts/install.sh`、`scripts/install.ps1`:删掉硬编码 `gitcode.com/SecLab/RustCode` 的 `REPO_BASE`/`REPO_LATEST_API` 与 `v5.0.2` 兜底 tag;改 `RUSTCODE_RELEASE_BASE`(必填,未设则 fail-closed 打印可操作指引)、`RUSTCODE_RELEASE_LATEST_API`(可选,用于 latest 自动探测)、`RUSTCODE_VERSION`。**删除 referral/invite 代码块**(写 `~/.rustcode/pending_invite` + install_uuid):遥测上报路径随 telemetry crate 删除后已无任何 Rust 读取方(grep 0),纯平台增长残留。`install.ps1` 失实注释 `crates/rustcode-core/...` 改 `rustcode-cli`;uninstall.sh/uninstall.ps1 头部 `curl|sh`/`irm` 厂商 URL 改本地/发行渠道口径。
  - **release 上传** `.github/workflows/create_tag_release.py`:删硬编码 `API_HOST=https://api.gitcode.com`、owner `bangxu`;改 `--api-host`/`--owner` 或 `RUSTCODE_RELEASE_API_HOST/OWNER/REPO/ACCESS_TOKEN`(GitLab-v5 兼容 releases/upload_url 方言),缺失即列出缺什么并退出。
  - **CI** `.github/workflows/build.yml`:删 4 处 "Add hosts" 步骤(macOS/linux/windows/distro-pm-check)——它们把 `api.gitcode.com`/`file.gitcode.com` 用 sudo 钉到厂商 IP `159.138.147.37`,是厂商 DNS 绕行;发行主机改为运营方注入后这些无意义。上传步骤只从 `secrets.RUSTCODE_RELEASE_ACCESS_TOKEN` 取令牌——**GitHub Secret 名必须带 `RUSTCODE_` 前缀且与工作流逐字一致**,无前缀的 `ACCESS_TOKEN` 是错的;API host / owner / repo **不由 Secret 注入**,走 `create_tag_release.py` 的默认值或 `RUSTCODE_RELEASE_API_HOST/OWNER/REPO` env。
  - **打包脚本** `packages/npm/scripts/build_npm_package.sh`、`packages/homebrew/scripts/package-tar-gz.sh`:GitCode v5 API/下载根与 `SecLab/RustCode`、`GITCODE_TOKEN/OWNER/REF/VERSION/JQ_URL` 全部改 `RUSTCODE_RELEASE_*`(API_HOST/OWNER/REPO/REF/ACCESS_TOKEN/DOWNLOAD_BASE/VERSION),缺关键项 fail-closed;去掉无关的 `ghfast.top` 代理镜像;日志 `↓/⚠` 改 ASCII `[*]/[!]`。
  - **元数据** 根 `Cargo.toml` 的 `repository`、`packages/npm/package.json` homepage/repository、`packages/npm/README.md` 链接 → example.com / 发行渠道口径(npm scope 统一为真实的 `@rustcode/rustcode`)。
  - **维护者脚本** `scripts/scheduled-dev-sync.sh`:PR 的 host/slug 严格从 `origin` remote 推断,**不再回退** `SecLab/RustCode`/`gitcode.com`;推断不出则打印"在你的远程仓库 Web 界面手工建 PR";token 改 `RUSTCODE_PR_TOKEN`。
  - **Rust 夹具/注释**:`rustcode-config/src/config/mod.rs` issue-353 注释去 URL;`rustcode-tuix/src/modals/qr.rs` 两个**非门控** QR 渲染冒烟夹具 `acs.atomgit.com` → `example.com`。(括号内原记的三处刻意保留已于 2026-09-09 失效:`event_loop/commands.rs` 的 `acs.atomgit.com/login` 与 `monitor.rs` 的 AtomGit provider 夹具已随 `#[cfg(feature="codingplan")]` 测试一并删除,`endpoints.rs:407` 是"api-ai.gitcode.com 视为外部"的**负向中立回归断言**也随签名网关识别器一并删除;三处现均无命中。)
  - **文档/元数据(子 agent)**:README(中英)、extensions vscode `package.json`+README、jetbrains `docs/jetbrains.md`、`rustcode-clix/README.md`(签名网关段改"可选托管网关 + 默认 BYO")、seed skill `SKILL.md`/`skills-reference.md` 市场 URL、`rustcode-codingplan/Cargo.toml` 注释——grep 0 残留。
  - **文档站(子 agent)**:`site/` 46 个 html(install/clone/npm-scope/marketplace/CDN 图片/login 口径)中立化,`site/referral.html`(硬编码厂商 ACS 后端的邀请奖励 SPA)替为中性占位页并摘除入链;`search-index.{zh,en}.json` 由 `cd site && node build-search-index.mjs` 重新生成(不手改 JSON)。
  - **G6 复核**:产品内 **0 个 telemetry SDK 依赖/调用**(无 sentry/posthog/... crate 或依赖)。唯一 `sentry` 字符串命中是 seed skill `references/mcp-servers.md` 的**第三方 MCP 目录**——`@sentry/*` 作为"用户项目用了 Sentry 就推荐 Sentry MCP"的栈探测启发式(与同表 `@aws-sdk/*`/`@supabase/*`/GitHub MCP 同类),是外部工具文档,非本产品遥测;判为**已复核的假阳性**,保留。
  - **验证**:G1 `cargo fmt --check` 通过;`cargo check --workspace --all-targets` Finished(仅存量 warnings:capabilities dead_code、tuix `usage_render` unused_parens、cli 未用 `SessionId` 导入,均非本轮引入);tuix qr 7/7、config fallback 3/3 通过;install/uninstall/packaging/sync 脚本 `sh -n`/`bash -n` 通过;`create_tag_release.py` py_compile 通过;`scripts/`、`packages/`、`.github/` 厂商主机 grep 清零。
- **[DONE] "不与任何模型/平台绑定" 复核(2026-09-01,有证据,非断言)**:针对目标里"不与任何模型有关联、只保留第三方 BYO 配置、零遥测",逐面排查确认产品**不默认、不背书、不私连任何厂商**:
  - **运行时无厂商默认**:无配置时 headless 走 `headless_missing_provider_message()` 直接 bail(见上轮);TUI/daemon 新建 provider 面板 `protocol_preset_idx(OpenAi) = "openai-compatible"`,`default_base_url: None`、表单起点为中立兼容端点,不预填任何厂商 URL(`provider_panel.rs`)。
   **2026-09-29 修订**:新建 provider 表单起点改为**本地 Ollama**(协议=ollama、
   base_url 预填 `http://localhost:11434`、无 API key 字段)——首发用户多先跑本地
   模型且 Ollama 免 key;`←/->` 仍可切到 OpenAI/Anthropic 兼容协议,预填值只填
   空字段、永不覆盖已输入内容。厂商 preset(deepseek/openai/anthropic/qwen/zhipu/moonshot/… )全是**用户自带 key 手选的第三方 BYO 配置**,中立 `openai-compatible`/`anthropic-compatible` 居 PRESETS 最前(测试 `generic_endpoints_lead_the_registry` 锁定索引 0 中立)。
   - **模型排序(2026-09-29)**:`ModelProfileConfig` 新增 `added_at`(unix 秒,
     serde default),`/model` 与 provider 面板共用
     `Config::logical_model_ids_by_recency()`——新添加的自定义模型置顶
     (added_at 降序),同刻/旧档(0)回退 (account, model) 分组序;重命名保留原
     戳记。TUI、webui(daemon)、openrouter 接入全部插桩。
   - **修复"正在获取模型列表..."永久挂起(2026-09-29)**:发现线程只经自己的
     mpsc 回传,而事件循环仅在 `wake_rx`(一次性启动检查)触发时才 poll,结果
     无人消费。面板打开时注入 `ctx.wake_tx`(`attach_wake`),worker 送达后 ping
     唤醒,循环的 wake 臂即 poll 并进入发现结果页;有真实本地服务器 + 阻塞等待
     ping 的回归测试。`taotoken`(token 转售商,曾是 invite/referral 漏斗终点)现为非默认、`ModelSource::Manual` 的可选项,且代码里已无任何 affiliate/referral/invite 端点(pending_invite 写入侧随安装器一并删除)。
  - **模型相关代码是"兼容性适配"非"背书"**:`persona.rs model_needs_firm_execution`(deepseek/qwen 弱模型加严 reviewer 指令)、`reasoning.rs` 按模型派生 thinking 策略、`openai_compat.rs` 仅在 `is_openrouter_url` 时发 OpenRouter 归属头——都只在**用户已选用**某模型时调整行为,不引导用户去用某厂商;保留。
  - **webui / 扩展无绑定**:webui、VS Code(`daemon/client.ts`)、JetBrains(`RustCodeDaemonClient.kt`)只连本地 daemon(`http://host:port`),默认模型取用户配置里 `is_default`;无硬编码厂商端点、无分析 SDK;文档链接指向自有品牌域 `docs.rustcode.dev`(保留)。webui `SettingsDialogs` 账号名占位 `my-deepseek` 改中立 `my-provider`。
  - **零遥测(再证)**:全部 `package.json`(webui/extensions/site)无 sentry/posthog/mixpanel/amplitude/segment/gtag 依赖;webui/site/extension HTML 无 beacon/gtag/sendBeacon 追踪脚本;生产 .rs 无 `/metrics|collect|track|events|ingest|analytics|report|beacon` 上报端点;`rustcode-telemetry` crate 不存在。唯一 `sentry` 字符串是 seed skill `references/mcp-servers.md` 的第三方 MCP 推荐目录(与 GitHub/AWS MCP 同类),假阳性。
  - **示例配置是第三方模板**:`docs/config.example.toml`/`docker/config-example.toml` 演示第三方 BYO(`api_key="sk-..."` 用户自带、deepseek/glm 为可选第三方;原 codingplan 网关示例段已于 2026-09-09 删除,现存的 `gateway.example.com` 占位只作第三方自建网关示例),属"只保留第三方配置"目标要求保留,不视为绑定。
- **[FIXED] i18n 文案测试对齐中立口径**(2026-09-01):上轮把 `Msg::CpOfficialBuildRequired` 改写为"第三方 BYO 或用带 CodingPlan 支持的发行版本"后,两个 i18n 内容测试仍断言旧厂商口径关键词(en 要求 `official`+`releases`、zh 要求 `官方`+`releases/发布`)——`cargo test -p rustcode-config --lib` 因此 2 failed。开放构建无"官方 releases"主机,旧断言绑定了厂商框架;改为断言**中立解决路径**:en 含 `bring your own key` + `distribution`,zh 含 `第三方提供商` + `发行`(`en_/zh_official_build_required_guides_byo_or_distribution`)。这是按去厂商化后的正确文案重新瞄准,非削弱断言。修正后 `rustcode-config` 328 passed / 0 failed。**教训:改 i18n 文案后跑整个 crate 的 `--lib`(内容测试散落在 en.rs/zh_cn.rs 末尾的 `codingplan_crypto_tests` 等模块),不要只跑受影响功能测试。**
- **[DONE] 多 agent 复核校准:首启引导 / 文案 / egress / 文档站中立化**(2026-09-01,多 agent 协助方案逐条 triage 并落地):
  - **[SUPERSEDED] 首启引导已无托管登录分支**:`platform_server()` / `managed_login_available()` / `/login` 命令已随 `rustcode-auth` 删除,`onboarding_wizard.rs` 的 `SetupChoice` 仅含 `Manual`/`Skip`(中立构建恒为 BYO);`welcome_tips.rs` pinned tip 改置顶 `/provider` 而非 `/login`。原 2026-09-01 记录(托管/中立两套 bullet、9 个 onboarding + welcome_tip 单元测试、9 处欢迎屏 vterm 断言重瞄 `/provider`、`event_loop/commands.rs` locale 竞态补 `i18n::test_lock()`)作沿革保留,详见 `docs/archive/`。
  - **"official build / 官方版本" 口径中立化**(en+zh):`CpUpgradeRequired`、`ProviderInitSourceBuild`、`GatewayAuthUnavailable`、`CmdProviderUnsupportedBuild`、`StatusOfficialBuildRequired`、`ProviderPanelManagedAccountHint` 去掉 "official releases / official binary / 官方版本 / 免费网关 / 官方 CodingPlan 账号",统一为"用带网关(托管签名)支持的**发行版构建**,或用 `/provider` 配第三方 BYO provider";`ProviderInitSourceBuild` 不再谎称"source build / 免费网关"。`i18n/mod.rs` 的 `GatewayAuthUnavailable` 测试只断言 `gateway/网关` + 回显 url,改后保持绿。
  - **clix 签名网关报错去厂商举例**:`rustcode-clix/src/main.rs` 把 "a closed-source overlay in the official binary" 改为"只在某些发行版构建中提供的闭源覆盖层",举例 `--provider openrouter` 改为通用 `--provider <name>`(选中具名 `[providers.<name>]` 表项,或 `RUSTCODE_API_KEY/BASE_URL/MODEL`)。
  - **egress 单一工厂补齐**:`rustcode-daemon/src/api_provider.rs` 模型发现(fetch_discovery_body)不再 `reqwest::Client::builder()` 自建,改 `rustcode_capabilities::egress::{build_http_client,HttpClientSpec}`(timeout/skip_tls_verify/user_agent 映射到 spec),与 provider/web/mcp/atomgit 共用同一 TLS 信任根 / proxy / UA / redirect 策略;egress 由 daemon 已启用的 `mcp` feature 拉入。
  - **seed skill 去硬编码 registry + 修 sudo 误导**:`rustcode-automation-recommender/SKILL.md` 把 `npx skills` / `skills.sh` 从"默认在线路径"降级为"发行版**可选**的社区 registry CLI 示例",删除全部硬编码 `https://skills.sh/` 链接;安装失败提示里"权限不足尝试 sudo"改为**明确禁止 sudo 写 `~/.rustcode`**(root 属主文件会破坏后续非 root 运行初始化,与 fork 铁律一致)。
  - **README(中英)**:PowerShell 安装示例补 `$env:RUSTCODE_RELEASE_BASE`(`install.ps1` 未设即 fail-closed,与 bash 示例对齐);uninstall 示例删掉 `uninstall.sh` 根本不读的 `RUSTCODE_RELEASE_BASE`;en README 中文小标 `**平台 Issues.**` → `**Platform issues.**` 并与站点一致加"附带托管平台支持的发行版"限定(中英都补,`platform_issue` 是 opt-in 平台工具的文档通用名);赞赏/社区二维码 `<img src="https://example.com/assets/...">`(example.com 永不托管,必裂图)换文字占位。
  - **site**:`index.html` 下载按钮从可点的 `example.com` 死链 `<a target=_blank>` 改为 `aria-disabled="true"` 非导航 `<span role=button>` + tooltip + `.dl-note` 双语说明(`RELEASE_BASE` 仍用于 binary tab 的 curl 文档示例,非死变量);`docs/en/login.html` stale meta("Three ways…CodingPlan / plain OAuth / API key")改两路 BYO 默认口径;`docs/{en,zh}/slash-commands.html` 的 `rustcode-channel.git` → 通用 `<marketplace>.git`;`build-search-index.mjs` 的 `GROUPS` 从"中文名硬编码进两种语言"改为 `{zh,en}` 双语标、`groupOf(slug,lang)` 按语言取(en 索引不再漏中文组名;顺带把 stale `运维` 对齐侧栏 `side.g.ops` 实际值 `问题/Help`),`cd site && node build-search-index.mjs` 重新生成 `search-index.{en,zh}.json`(不手改 JSON,0 个 heading id 注入)。
  - **验证**:G1 `cargo fmt --check` 通过(顺带 fmt 了 `parts.rs` 的 `parallel_template` 块);`cargo check --workspace --all-targets` Finished(仅存量 warning:cli `acp/discovery.rs` 未用 `SessionId` 导入,非本轮引入);默认成员全量 `cargo test` **2593 passed / 0 failed**(此前全量跑曾暴露上述 8 个欢迎屏 vterm 测试 + 1 个 todo locale 竞态红,均已改/修);`rustcode-tuix --lib` 全量 **2055/0**、`rustcode-config --lib` 328/0、`rustcode-clix` 44/0、`rustcode-daemon api_provider` 18/0;site 内联脚本 `new Function()` 语法检查 0 错误;搜索索引 en/zh 组名分别为 `Overview / Get Started / Usage / Advanced / Help` 与 `概览 / 开始 / 使用 / 进阶 / 问题`。
- **[DONE] 第二轮文档站/文档中立化校准(2026-09-01,多 agent 复核方案逐条落地,纯文档站/README,零 Rust 改动)**:
  - **落地页向导不再预选托管免费额度**(`site/index.html`):模拟首启向导第 3 步从三行(CodingPlan `class="opt sel"` "免费额度 · 推荐" + 手动 + 跳过)改为**两行 BYO**——手动配置预选(`wiz.s3.manual`/`.manual.hint`="自带 API Key · 推荐")+ 暂时跳过(`wiz.s3.skip`/`.skip.hint`);删除 dict 里 `wiz.s3.o1/o2/o3` 旧键。欢迎 bullet `wiz.s1.b3` 从"通过 CodingPlan 获取免费额度"改"自带 API Key,无需注册账号/Bring your own API key -- no account or signup"。
  - **删除托管计划导航/页脚入口**:header nav 与移动端抽屉里指向 `https://docs.rustcode.dev/models` 的 "Coding Plan" `<a class="nav-cp">/class="cp">` 两条链接、footer `ftr.links` 里 CodingPlan 锚点(静态 HTML + dict zh/en 三处)全部移除;随之删干净失效 CSS——`.hdr-nav a.nav-cp*`(8 行)、`.mb-drawer a.cp`/`a .free-badge`(浅色变体共 4 行)、dict 键 `nav.codingplan`;`@keyframes dotPulse` 仍被 hero badge `.dot` 使用,保留。`feat.platform.d`/`plug.platform.d` 里 OAuth 字样已是"发行渠道**可选**提供…开源默认构建 BYO"的正确门控口径,保留。
  - **M1 快速开始文档改为 BYO 默认**(`site/docs/{en,zh}/getting-started.html`):banner 第三条 "Free tokens via CodingPlan/通过 CodingPlan 获取免费额度" → "Bring your own API key — no account or signup/自带 API Key,无需注册账号";Step 3/3 配置转录从 3 项(1. CodingPlan 推荐领免费额度)改为 **2 项**(1. 手动配置 provider 推荐自带 Key,2. 跳过),`<ul>` 首条改为手动 `/provider` 推荐路径并列出 Claude/OpenAI/DeepSeek/GLM/Qwen/Ollama,另加一段说明"内置托管服务的发行版可能额外显示一键登录行(等价 `/login`),开源默认构建无此行、默认自带 Key"——与真实二进制 `setup_choices()` 的 2/3 行门控一致。
  - **S1 斜杠命令文档门控**(`site/docs/{en,zh}/slash-commands.html`):`/login` 表格行从"推荐·一条命令 OAuth + 领免费额度"改为"**仅发行版本/Distribution builds only**……开源默认构建无此命令,用 `/provider` 自带 Key";`/provider` 行改标 **推荐** 并写明第三方预设 + 自定义 OpenAI 风格接口 + 无需注册;`/cost` 行的 `/usage` 说明改"发行版查询托管账号额度,开源构建不可用、`/cost` 即全部用量";`/status` 去 "CodingPlan 用量" 改"provider 与鉴权状态(发行版另显托管账号用量)";`/whoami` 加"仅发行版本";`/logout` 从"清除 OAuth token"改"清除托管账号凭据(BYO 的 API Key 仍存配置)";`/reload` 括号里"另一个终端的 /login"改"provider/凭据变更";`/app` 中继行加"内置托管中继的发行版…开源默认构建不支持";典型工作流标题 "First launch — one-click onboarding/第一次启动-一键接入" 改 "bring-your-own-key/自带 Key",转录从 `/login`+CodingPlan claimed 改 `/provider` 三步(加账号→粘 Key→加模型)+ `/model`,末尾补"发行版也可 `/login` 一键 OAuth"。
  - **S2 daemon HTTP 文档与代码对齐**(`site/docs/{en,zh}/headless-daemon.html`):"Auth / CodingPlan" 小节改名 "认证与托管账号(仅发行版本)" 并加一段:开源默认构建无托管端点,BYO 走上文 `POST /providers` 或 `config.toml`;该构建里 `/auth/*` 路由虽注册但 OAuth 无法完成(无服务可登,`auth::start_login()` 对空 `platform_server` 报错返回 500),`/codingplan/*` 路由由 `#[cfg(feature="codingplan")]` 门控、**不参与编译返回 404**(`lib.rs::codingplan_routes()` 空 router 证实)。**[2026-09-09 补注]** 该 cfg 门控、codingplan_routes() 与整个 Cargo feature 均已随裁决 Q1=B 删除,daemon 不再有这些路由(不是 404 门控,而是不存在);本轮改的那两个 site 文档页仍保留门控口径与 codingplan 端点表,**尚未同步**,已登记为后续文档清理项(本任务只改 AGENTS.md)。修正一处**事实错误**:原表称 `rustcode codingplan` 作为隐藏别名保留——实际 CLI 补全测试 `main.rs:4339` 断言 `!script.contains("codingplan")`,该别名已移除,文档改为"CLI 没有单独的 `rustcode codingplan` 命令";并补登 `/codingplan/usage/summary`、`/codingplan/usage/daily` 两条仅发行版路由(此前漏列)。
  - **S3 README**:原中文 README 第 94 行的智谱 GLM 行去掉虚构的"（RustCode Pro 套餐专属模型）"(不存在任何付费套餐;en README 本就平铺 GLM-4/5/5.2),与 en 对齐。
  - **NIT 批**:(N1)两份 README "会话与登录/Sessions & Login" 的 OAuth/SSO bullet 加"仅发行版本/distribution builds only"并新增首条"第三方供应商(BYO)——配置自己的 base_url+api_key,无需注册,开源默认方式";README 斜杠命令表 `/login` 行从"claim CodingPlan free models"改"登录托管服务(仅发行版;BYO 用 `/provider`)"。(N4)`docs/zh/login.html` 单薄 meta("登录方式 — RustCode 文档。")补成与 en 同义的丰富描述;该页正文已是 BYO 默认 + 托管登录门控,无需改。(N6)安装占位符统一中立域:`site/index.html` unix/win 安装命令 `https://your-host/...` → `https://example.com/your-host/...`,README(en/zh)PowerShell 与 bash 的 `RUSTCODE_RELEASE_BASE=https://<host>/...` → `https://example.com/your-host/...`(与同仓 `git clone https://example.com/<your-org>/...` 及站点 `RELEASE_BASE` 口径一致;`api.deepseek.com/v1` 等是**真实第三方 BYO provider 端点示例**,属正确用户文档,保留)。(N7)README 隐私/遥测节链接补齐:en Privacy bullet 原只链 ORIGINAL_LICENSE/UPSTREAM_CREDITS,补上 `docs/telemetry.md`(zh `零遥测` bullet 本就链该文件),中英对齐。(N5)`site/index.html` 无 JS 静态兜底与 i18n dict 对齐:静态 `step2.t` "配置 API Key" → "配置 provider"、`step2.d` 换成 dict 的富文本"Claude/OpenAI/DeepSeek/GLM/Qwen/Ollama 等第三方 API 任一 · 自带 Key";dict `wiz.s3.skip.hint` en 残片 "explore first" → "Set up later"(配 zh 稍后再说)。(N3)`build-search-index.mjs` 的 GROUPS 进阶组补 `headless-daemon` slug——该页被 webui/webui-remote-access 链接引用、此前却不在任何组里,索引阶段被 `skip ungrouped` 丢弃且拿不到 heading id 注入。
  - **搜索索引重生成**:`cd site && node build-search-index.mjs`(不手改 JSON)——en/zh 各 **21 pages**(headless-daemon 现入索引),各向 1 页注入 heading id(即 headless-daemon:h1/h2/h3 获 `id` 保证搜索 `#anchor` 可滚动);`search-index.{en,zh}.json` 随内容更新。
  - **未改/刻意保留** —— **[SUPERSEDED 2026-09-02,见第三十二轮]**:README 与 docs 里 `atomgit_atomcode/atomcode` 仅出现在 fork 归属声明与 ORIGINAL_LICENSE/UPSTREAM_CREDITS(合法历史出处,G7/G8 逐案豁免)。**该「保留 README 与 features/platform-neutralization」的结论已被第三十二轮用户裁决推翻**:这两个 README 与 `docs/{features,platform-neutralization}.md` 正文中的上游 slug 已清除(改述为「上游项目」,并保留指向归属文档的链接);**仅** `LICENSE`、`docs/{UPSTREAM_RUSTCODE_LICENSE,UPSTREAM_CREDITS,THIRD_PARTY_NOTICES,ORIGINAL_LICENSE}.md` 保留完整 MIT 归属原文——那才是 MIT 的合规落点,README 点名上游 slug 并非 MIT 要求。"关于可选的 CodingPlan 网关(闭源签名)" 小节原判为对 opt-in 发行版能力的正确门控说明而保留——**该小节已于 2026-09-09 改写为「关于曾经可选的托管网关(已于 2026-09-09 移除)」,不再描述任何可用能力**;`atomgit` cargo feature 仍是刻意保留的 opt-in 开关;而 `#[cfg(feature="codingplan")]` 块与 `LEGACY_CODINGPLAN_PREFIX` 识别器原记「按 fork 铁律**不动**」——**该结论已于 2026-09-09 被用户裁决 Q1=B / Q2' 推翻,两者均已删除**。本轮零 `.rs` 改动,G1–G3 不受影响。
- **[DONE] 第三轮多 agent 校准:斜杠命令发现面按构建门控(2026-09-01,代码复核 MED 落地,含 Rust 改动)**:
  - **问题(代码复核 agent MED)**:上一轮文档把门控口径写进了文档,但 `rustcode-tuix/src/commands.rs` 的命令发现面只按静态 `hidden` 标志过滤、**从不查 `platform_server()`**——中立构建里 `/help`、`/` 斜杠菜单、Tab 补全、ACP `available_commands` 仍展示 `/login`("Sign in with OAuth and claim CodingPlan models")与 `/usage`("Show CodingPlan usage",该行 `acp: true`,此前**确实**被广告给 ACP 客户端),即首启引导 `setup_choices()`/欢迎 pinned tip 已消除的"死路托管推销"在命令发现面残留。
  - **修复**:`commands.rs` 新增 `const MANAGED_ONLY_COMMANDS: &[&str] = &["login", "logout", "whoami", "usage"];` 与 `fn command_visible(cmd) -> bool`——静态 `hidden` 恒隐藏;名字 ∈ MANAGED_ONLY_COMMANDS **且** `!crate::modals::onboarding_wizard::managed_login_available()`(即空 `platform_server` 的中立构建)时隐藏。五个发现面全部改走该谓词:`matching_prefix`(斜杠菜单)、`help_text` 两处(最大列宽计算 + 输出循环)、`acp_commands`(ACP v1/v2 广告与 ACP `/help` 同源)、`complete_commands`(Tab 补全)。**派发表 `find()` 不查可见性**:四个命令在中立构建仍可手动输入执行(走既有 BYO `LoginManagedUnavailable` / 本地用量提示),只是从所有发现面消失——与 onboarding 2/3 行门控同一谓词,dispatch 与 discovery 分离。
  - **测试**:`help_text_lists_all_commands` 的分支条件 `if c.hidden` → `if !command_visible(c)`(注释说明隐藏别名与中立构建的托管命令都不进 `/help`);新增 `neutral_build_hides_managed_account_commands`——断言中立 `/help` 不含四个托管命令、`matching_prefix` 不浮现它们、ACP 不广告 `/usage`、Tab 补全不浮现 `/login`,且 `/help` 必含 `/provider`(BYO 领路)。
  - **验证(全绿)**:G1 `cargo fmt --check` 通过(rustfmt 重排了两处长行);`cargo test -p rustcode-tuix --lib` **2060 passed / 0 failed**;`cargo test -p rustcode acp::commands` 3/0(既有 `acp_catalog_is_sorted_and_filtered` 本就禁 `login`/`logout`/`whoami`——它们 `acp: false`,`parse_slash_command("/login")` 恒 None;门控后 `usage` 在中立构建也退出 ACP 广告,托管发行版仍保留);`cargo clippy -p rustcode-tuix --all-targets` 在 `src/commands.rs` **零 warning**(`event_loop/commands.rs` 的存量 `io_other_error`/大枚举变体告警非本轮引入)。
  - **代码复核 agent 干净判定(留档)**:硬编码托管主机全清(所有 `HOSTED_*` 常量为空;`is_codingplan_llm_gateway()` 仅在显式 `RUSTCODE_CODINGPLAN_LLM_BASE_URL` 时为真,否则一律 `bearer_auth(api_key)`);HTTP egress 单一工厂基本干净(leaf `rustcode-updater`/`rustcode-auth` 无法依赖 capabilities 属结构豁免,LLM 适配器打用户自供 base_url 豁免);遥测 SDK grep 为零;默认中文在全部回退点(`locale.rs` Default、`i18n/mod.rs` 静态/resolve/poison 三处、persona 注入、webui `i18n.ts` DEFAULT_LANG='zh')成立;无明显裸 unwrap/expect 风险。
  - **LOW 不改(留档)**:webui `SettingsDialogs.tsx` 硬编码 `https://pgy.oray.com`(蒲公英 Oray 虚拟局域网远程访问说明链接)——客户端从不请求该地址,性质同 Ollama 下载页这类第三方工具文档链接,复核 agent 自标 "awareness only";与 `webui-remote-access` 文档的蒲公英方案一致,保留。
  - **刻意保留**:`BUILTIN_COMMANDS` 里 login/usage 的静态 `desc` 与 i18n `CmdDescLogin`/`CmdDescUsage`(zh_cn.rs/en.rs)文案仍提 CodingPlan——它们只在托管发行版渲染(中立构建命令已从发现面隐藏,`cmd_desc_i18n` 无 Neutral 变体),当时判为对 opt-in 托管能力的准确描述、与 codingplan 门控块同属保留开关而不动。**该保留结论已于 2026-09-09 被裁决 Q3 推翻**:`#[cfg(feature="codingplan")]` 块已删除,这两条文案里的 CodingPlan 品牌字样也已随 i18n 收尾任务清除(实测 zh_cn.rs/en.rs 中 codingplan 0 命中);两个 managed 版消息变体**本身仍在**(与各自的 Neutral 版一起按托管登录谓词选版),只是不再提品牌。
> **[SUPERSEDED — 历史记录,非当前行为]** 第四轮至第九轮(以及第十一轮 11A–11D、第十三轮 `api_auth.rs` 登录轮询错误体等子项)记录的「托管登录 / 托管账号门控」工作,涉及 `rustcode-auth` crate、`crates/rustcode-daemon/src/api_auth.rs`、`auth::managed_login_available()`、`rustcode_config::endpoints::platform_server()`、`AuthStatusResponse.managed_available` 字段与「第七轮扩展门控」等——这些代码已在 2026-09-09 的「移除托管登录」裁决中整体删除(`api_auth.rs` 已不在 daemon crate,`managed_login_available()` / `platform_server()` 不再存在)。以下条目仅为沿革记录,**不再描述任何现存行为**;其中「501 不可重试契约」「命令可见性过滤(隐藏但可派发)」等设计结论若仍有参考价值,有效的是结论本身,而非被删代码。

- **[DONE] 第四轮多 agent 校准:同一谓词贯通 daemon/WebUI/TUI 的托管账号门控(2026-09-01,承接第三轮 TUI 命令门控,补齐剩余两个用户面)**:
  - **背景**:第三轮把 TUI 斜杠命令发现面门控后,代码面排查发现 **WebUI 与守护进程 API 仍无条件推销托管登录**——`useAuth`(webui `LoginButton.tsx`)每 2s 轮询 `/auth/status`,侧栏底部恒显"登录/Sign in"按钮;中立构建点击后 `POST /auth/login/start` 对空 `platform_server` 必返 500(死路,且无任何用户反馈);WebUI 自己的斜杠命令表(`lib/slashCommands.ts`)还把 `/whoami` 列进菜单/`/help`;TUI 的 `/whoami` 与 provider `AuthenticationRequired` 状态提示一律输出"使用 /login 进行认证"(中立构建无 login 可用)。
  - **单一谓词落地**:`rustcode-auth/src/oauth.rs` 新增 `pub fn managed_login_available() -> bool`(对**原始** `rustcode_config::endpoints::platform_server()` 判空——不能用 `platform_base_url()`,sanitize 空串会产出 `"http:"` 非空;`pub use oauth::*` 自动导出)。TUI `onboarding_wizard::managed_login_available()` 改为**委托**该谓词(此前直接查 config),`commands::command_visible`/onboarding/daemon/WebUI 从此同源,杜绝漂移。
  - **daemon**:`api_auth.rs` 的 `AuthStatusResponse` 新增 `managed_available: bool`(3 个构造点:status 有凭据/无凭据、logout 后),值取 `auth::managed_login_available()`;新增 `neutral_build_reports_managed_unavailable` 测试(起 `auth_status()` handler 断言 JSON `logged_in=false`、`managed_available=false`、谓词一致)。
  - **TUI 文案中立变体**:`rustcode-config` i18n 新增 `Msg::CmdWhoamiNotSignedInNeutral`(en:"This build has no managed account -- use /provider to add a bring-your-own-key provider";zh:"此构建无托管账号 -- 用 /provider 配置第三方供应商(自带 API Key)");`onboarding_wizard` 新增 `pub(crate) fn not_signed_in_msg()` 按谓词二选一;3 个旧 `CmdWhoamiNotSignedIn` 调用点全部改走它——`build_whoami_text()`(`/whoami` 输出,TUI arm 与远程执行共用)、`provider_unavailable_announcement()`、状态栏 provider-waiting 提示(event_loop/mod.rs 两处)。新增 tuix 测试 `neutral_build_whoami_points_at_provider_not_login`(断言中立文本含 `/provider` 且不含 `/login`)。
  - **WebUI**(React/Preact):(1)`LoginButton.tsx` 的 `useAuth` 读取 `managed_available` 并暴露 `managedAvailable`;中立构建首次轮询拿到 false 后**停止 2s 定时轮询**(状态不可能翻转为登录),`startLogin()` 加 `!managedRef` fail-closed 守卫。(2)`Sidebar.tsx` 侧栏底部账号区(头像 chip / 登录按钮整块)与设置菜单"退出登录"行均按 `auth.managedAvailable` 门控,中立构建完全不渲染。(3)`lib/slashCommands.ts`:`SlashCommandDef` 加 `managedOnly?: boolean`(`/whoami` 标记),新增 `visibleCommands(managedAvailable)` 过滤;`buildHelpText(t, managedAvailable)` 与斜杠菜单改用可见列表;`SlashHandlers` 加 `managedAvailable` 字段;**dispatch map 仍建自全量 `FRONTEND_COMMANDS`**——手敲 `/whoami` 依旧执行(服务端返回中立文案),与 TUI"隐藏但可派发"一致。(4)`Chat.tsx` 挂载时一次性 fetch `/auth/status` 取 `managed_available`(fail-closed false),`advertisedCommands` memo 接入两处菜单构建与 handlers。(5)新增 4 个 webui 单测(中立列表隐藏 whoami/`/help` 双语门控/菜单过滤/显式键入仍可派发),既有 fakeHandlers 全部补 `managedAvailable` 字段。
  - **文档**:`site/docs/{en,zh}/headless-daemon.html` 的 `GET /auth/status` 行补述 `managed_available` 字段语义(false 时 WebUI 隐藏账号入口);搜索索引重新生成(en/zh 各 21 页)。
  - **验证(全绿)**:`cargo fmt --check` 通过;`cargo check --workspace --all-targets` Finished;`cargo test -p rustcode-tuix --lib` **2061/0**(新增 1)、`-p rustcode-daemon --lib` **304/0**(api_auth 8/0,含新增)、`-p rustcode-config --lib` **328/0**(i18n 双语 arm 齐全);clippy 在本轮改动区域**零新增告警**(新测试的 `assert_eq! bool` 已按 clippy 改 `assert!`;onboarding_wizard/oauth 既有存量告警位置远离改动);webui `tsc --noEmit` 0 错误、`npm test` **221/0**(新增 4)、`npm run build` 成功后按铁律 `cargo clean -p rustcode-daemon` 再 check(dist 嵌入刷新)。
  - **刻意保留**:WebUI `cmd.whoami.none`("未登录/Not signed in")无 login 推销,仅显式键入时出现,保留;`SettingsDialogs.tsx` 的托管 provider 徽标 `settings.officialCodingPlan` 由 daemon 数据门控(`provider.requires_login`/`account.managed`,中立构建无此数据),保留;上一轮记录的 pgy.oray.com LOW 仍维持 awareness-only。**[2026-09-09 补注]** WebUI 侧的品牌字样已由并发进行的 WebUI 清理改动清除:徽标 JSX 与 officialCodingPlan 键已删除,managed 模型引导文案已去品牌,Chat 面注释亦已中性化;残留只有 app.css 里那条 provider-managed-badge 样式类。**托管徽标的能力本身(按 managedAvailable 数据门控)仍保留**,本条"保留"结论对能力面依然成立,只是不再有品牌名。该状态取自工作区实测(含未提交的并发改动),最终以 T-31 全量验证为准。
- **[DONE] 第五轮:CLI 子命令发现面门控 + 补全脚本口径(2026-09-01,承接第三/四轮,补齐最后一个 Rust 驱动面)**:
  - **问题**:第三/四轮把门控谓词(`rustcode_auth::managed_login_available()`)贯通了 TUI 命令发现面、daemon `/auth/status`、WebUI,但 **CLI 二进制自身的 `--help`/clap 子命令与 shell 补全脚本**仍无条件列出 `rustcode login`/`logout`(about 文案推销 OAuth 托管登录),中立构建用户照做即死路;`completion_command()` 直接用未门控的 command 树生成 5 种 shell 补全。
  - **修复**(`crates/rustcode-cli/src/main.rs`):`build_i18n_command()` 计算 `let managed = auth::managed_login_available();`,中立构建对 `login`/`logout` 两个子命令 `.hide(true)` 并把 `login` 的 about 换成 `Msg::CliAboutLoginNeutral`(en:"Managed sign-in (distribution builds only) -- this open build uses bring-your-own-key providers; configure config.toml";zh 同义),`logout` about 改"安全 no-op"口径;`status` 不隐藏、about 用新增 `Msg::CliAboutStatus`("Show current provider and sign-in status/查看当前供应商与登录状态")。`completion_command()` 改为从 `build_i18n_command()`(门控后的同一棵树)生成补全。**dispatch 不门控**:手敲 `rustcode login` 仍可执行并打印中立 about(hidden != removed,与 TUI/WebUI "隐藏但可派发"一致)。顺带修一处既有文案 bug:`{oauth}` 占位符原样泄漏到 login about。
  - **测试**:(1)新增 `neutral_build_hides_managed_login_subcommands`——`find_subcommand("login")/("logout")` 存在但 `is_hide_set()`、login about 含 `config.toml` 不含 `CodingPlan`、`status` 未隐藏(注意 clap 4.6 `get_about()` 返回 `Option<&StyledStr>`,断言前 `.map(|s| s.to_string())`)。(2)`completion_scripts_cover_all_supported_shells` 原来的扁平 `!script.contains("login")` 断言误伤合法的 `mcp login`/`mcp logout`(MCP server OAuth,与托管登录无关,五种 shell 都应出现)——改为逐行上下文跟踪器:bash 函数头(`() {`)、zsh `curcontext=` 行(如 `:rustcode-mcp-command-$line[1]:`)、elvish/powershell map 路径(`&'rustcode;...` / `'rustcode;...{`)作为上下文标记,任何含 `login/logout` 的行必须处于 mcp 上下文(行内或上下文标记含 `mcp`/`github-oauth`)。
  - **i18n**:新增 `Msg::CliAboutLoginNeutral` 与 `Msg::CliAboutStatus`(en.rs/zh_cn.rs 双语 arm 齐全);`rustcode-config --lib` **328/0**。
  - **运行时验证**:`rustcode --help` 不再出现 login/logout/codingplan;`rustcode login --help` 仍可派发并打印中立 about。CLI 测试套件全绿(含两个新/改测试)。
- **[DONE] 第六轮:daemon 托管登录中立失败契约从 500 改可操作 501(2026-09-01)**:
  - **问题**:第四轮给 `GET /auth/status` 加了 `managed_available` 字段,但中立构建里 `POST /auth/login/start` 仍走到 `auth::start_login()` 对空 `platform_server` 报错,返回**通用 HTTP 500 `login_start_failed`**——客户端无法区分"服务暂时挂了(可重试)"与"此构建根本没有托管登录(永远别重试)",扩展端只能显示死路错误。
  - **修复**(`crates/rustcode-daemon/src/api_auth.rs`):新增 `pub(crate) fn managed_login_unavailable_response()`——HTTP **501** + JSON code **`managed_login_unavailable`**、`retryable: false`、消息指向第三方 BYO provider 配置;`auth_login_start` handler 在 spawn_blocking 之前 `if !auth::managed_login_available() { return managed_login_unavailable_response(); }`(fail-closed,与谓词同源)。`/codingplan/*` 路由仍由 `#[cfg(feature="codingplan")]` 门控、中立构建 404,不动。**[2026-09-09 补注]** 该「不动」结论已被裁决 Q1=B 推翻:路由、cfg 门控与 api_codingplan 模块已整体删除;本轮的 501 managed-login-unavailable 契约本身与 codingplan 无关,仍有效。
  - **测试**:`neutral_build_login_start_returns_actionable_501`(起 handler 断言 501、`json["code"]=="managed_login_unavailable"`、`retryable==false`、消息含 "third-party provider")。`rustcode-daemon --lib` **305/0**。
  - **文档**:`site/docs/{en,zh}/headless-daemon.html` 的 `POST /auth/login/start` 行补述中立 501 契约(zh:"开源构建中会快速失败,返回 501 与错误码 managed_login_unavailable(不可重试),提示客户端引导用户改用自带 API Key 的第三方供应商配置");搜索索引已重新生成(en/zh 各 21 页,索引含 `managed_login_unavailable`)。
- **[DONE] 第七轮:两个 IDE 扩展按 `managed_available` 门控托管登录 UI(2026-09-01,多 agent 扩展审计方案逐条 triage;VS Code 全验证,JetBrains 仅源码级——本机无 JDK/gradle)**:
  - **VS Code**(`extensions/vscode/`,host tsc 0 错、webview tsc 0 错、`npm run test:webview` 全组 0 失败、`npm run build:webview` 成功):
    - **wire/host**:`src/daemon/types.ts` 的 `AuthStatusResponse` 加 `managed_available?: boolean`(旧 daemon 缺字段 → fail-closed);`src/auth/status.ts` 加 `managedLoginAvailable(auth)`(`=== true` 判定);`src/chat/provider.ts` 持有 `_managedLoginAvailable`(初始 false fail-closed,`_sendSetupState` 轮询 `/auth/status` 时赋值),`_startLogin()`/`_setupCodingPlan()` 在不可用时早返回并广播 setupError(新中立文案 `_managedLoginUnavailableMessage()`,`vscode.l10n.t()`),`/login` 手敲回中立提示、`/logout` 回"此构建无托管账号"、`/whoami` 未登录分支按谓词二选一;webview HTML locale 注入从硬编码 `'en'` 改为 `vscode.env.language || 'zh-cn'`(与 Rust ZhCn 默认对齐)。
    - **webview(Preact)**:`state/types.ts` 的 `AuthStatus` 加 `managed_available?`(snake_case 直出);`WelcomeScreen.tsx` 加 `managed` 谓词——账号步骤/loginUrl 块/同步按钮/"手动添加"折叠开关全部 `{managed && ...)}`,中立构建手动 provider 表单默认展开;`baseUrl` 初值从预填 `https://api.openai.com/v1` 改空串(不预选厂商);models 步副标题用新 `setup.addProviderHint`。`SlashPicker.tsx` 的 `SlashCommand` 加 `managedOnly?`,`/login`/`/logout`/`/whoami` 标记后按 `state.auth.managed_available` 过滤(派发路径不变,手敲仍达 host)。`i18n.tsx` 加 `setup.addProviderHint` zh/en;`l10n/bundle.l10n.zh-cn.json` 加 3 条中立文案。
    - **测试**:`webview-ui/test/auth-status.test.ts` 加 4 个 `managedLoginAvailable` 断言(true/false/undefined/缺字段全 fail-closed)。顺带修一处**既有** tsc 错误:host 会 post `{type:'runtimeInfo',provider,model}` 但 webview `ExtensionMessage` 联合缺该变体(已用 git stash 证实为先存),补上。
    - **npm 环境注记**:npmmirror 镜像的 `y18n@5.0.9` tarball 是幻影(404,真版本止于 5.0.8),`npm ci` 必败;解法是把坏 lock 移走后 `npm_config_registry=https://registry.npmjs.org npm install --no-audit --no-fund` 重生成 `package-lock.json`(已落地)。
  - **JetBrains**(`extensions/jetbrains/`,**源码完成,未编译验证**——本机 EulerOS aarch64 无 JDK、无缓存 gradle 发行包,不声称绿灯):
    - `RustCodeDaemonTypes.kt` 的 `AuthStatusResponse` 加 `managedAvailable: Boolean = false`(缺字段 fail-closed);`RustCodeDaemonClient.kt` 的 `authStatus()` 解析 `raw.jsonBoolean("managed_available") ?: false`。
    - `RustCodeChatPanel.kt` 持有 `private var managedLogin = false`,`renderSetupSnapshot` 里 `snapshot.auth?.managedAvailable == true` 赋值;齿轮菜单的 login + CodingPlan 设置项(含分隔线)`if (managedLogin)` 包裹;`showCommandMenu` 的 `/login` 行同理;welcome-action `"login"` 与手敲 `/login` 在不可用时改发 `managedLoginUnavailableMessage()`(新 bundle key `login.unavailable`,en + `RustCodeBundle_zh.properties` 的 `\uXXXX` 转义中文)。
    - `JBCefMessageView.kt`:`showWelcomePage(language, loggedIn, managedAvailable = false)` 贯穿到 `welcomeContent`,zh/en 文档文案按谓词二选一(托管:平台登录说明;中立:齿轮菜单 Provider -> Create Provider BYO 指引),`showLogin = !loggedIn && managedAvailable`;welcome HTML 品牌标记 AtomCode 时代残留 `<span class="home-mark">A</span>` 改 `"R"`。
    - `EditorAtomCodeActions.kt` 重命名为 `EditorRustCodeActions.kt`(内部 object 本就叫 `EditorRustCodeActions`,无残留引用);README 斜杠命令清单修正为实际接线的 `/review` + 门控的 `/login`,删掉虚构的 `/codingplan /explain /fix /test /refactor /docs /optimize`。
  - **两个审计 agent 的刻意保留/LEAVE 项(留档,勿再报)**:扩展侧 `/codingplan/setup` 客户端方法/类型原记为托管发行版 API 的保留开关(门控不删除,同 `atomgit` cargo feature 铁律),**该结论已于 2026-09-09 被裁决 Q5 推翻**——两侧扩展的 codingplan 调用面已随 VS Code / JetBrains 清理任务删除(实测 extensions 目录仅剩 jetbrains CHANGELOG 的一条历史条目);OAuth 传输本身不涉 codingplan,保留;`requires_login` 驱动的 ModelSelector 徽标、legacy-null fail-closed 分支、example.com 夹具、127.0.0.1:13456 默认、零遥测(两扩展依赖仅 gson/kotlinx 与 dompurify/marked/react,无分析 SDK)均判干净。**延后 SHOULD-FIX 候选**:JetBrains 硬编码 zh/en 字符串迁入 bundle(含 `SlashCommand` 描述硬编码中文、`managedLoginUnavailableMessage()` 用无 locale 重载——与齿轮标签一致跟随 JVM locale 而非 `welcomeLanguage`,属既有模式)、PRIVACY.md 中立措辞、ASCII 符号巡查。
  - **JetBrains 独立编译审计(general-purpose agent,逐条核)**:**无 BLOCKER,判定 "COMPILE-VERIFIED BY INSPECTION"**——`showWelcomePage/welcomeContent` 新旧调用点参数顺序全对(外部唯一调用 `RustCodeChatPanel.kt:373` 传 `(welcomeLanguage, loggedIn, managedLogin)`);`jsonBoolean` 定义在 `SseParser.kt:104`(同包 internal 扩展)可解析;`RustCodeBundle.message(key)` 单参重载存在(locale 内部按 JVM 解析);`login.unavailable` 双语 properties 键齐(16/16 parity)、zh 文件纯 ASCII 转义;改动区括号平衡;`managedLogin` 字段声明即 false(fail-closed),首启 welcome 在 snapshot 到达前渲染=隐藏托管 UI;门控在 Kotlin 侧烘焙进 Gson payload(`showLogin`/`docsText`),JS 不引用未填充字段;jetbrains 目录 `atomcode/atomgit` grep 零命中;`EditorRustCodeActions.kt` 重命名无悬挂引用(plugin.xml 只注册 Action 类、无 per-file sourceSet、git 纯 rename);唯一既有 pictograph U+2713 为允许的单色符号。
- **[DONE] 第八轮多 agent 校准:残余"死路 /login"文案清零(2026-09-01,跨面 sweep agent 报 4 项,逐条 triage 全落地;含 Rust+webui 改动)**:
  - **背景**:第七轮后 very-thorough sweep 专查"中立构建仍会显示、且未被谓词门控的托管登录/注册/免费额度文案",报 HIGH 1 + MED 2 + LOW 2;另确认一大批 LEAVE(CLI/TUI/onboarding/WebUI 侧栏/`/auth/status` 已门控;`ChatAuthExpired`/api_provider "managed by /login" 错误只在 signer/`selection_is_managed()` 成立时触发;MCP `/mcp login` 是第三方 server OAuth 合法 BYO 功能;`UsageCodingPlanOnly` 本身已是中立文案)。**[2026-09-09 补注]** 该 usage-only 消息变体已随 i18n 收尾任务退役(config i18n 实测 0 命中),该 LEAVE 项无对象。
  - **(HIGH)daemon `/status` 的 Login 行**:`crates/rustcode-daemon/src/commands.rs::render_login_line_from_stored_auth()` 此前无条件渲染 `StatusLoginNotSignedIn`("not signed in (run /login)"),webui `/status` 与 CLI status 透传该文本——TUI 等价处(`event_loop/commands.rs` status 渲染)早已按谓词返回空串,daemon 漏网。修复:函数开头 `if !rustcode_auth::managed_login_available() { return String::new(); }`(`assemble_status` 直接拼接空串,输出干净)。新测试 `neutral_status_omits_managed_login_line`:谓词为 false 时函数返回空,且 `exec_status()` 组装文本不含 `/login`(注意 `CommandResult` 只 derive `Serialize` 无 `Debug`,测试用 `if let ... else { panic! }` 不能 `{other:?}`)。
  - **(MED)TUI `CmdProviderUnavailable` 七处调用点**:`"Provider is unavailable. Use /login to sign in or /provider..."` 在提交拒绝/steer 失败/队列排空失败/goal/loop 启动失败/status bar 提示里无条件出现。新增 `Msg::CmdProviderUnavailableNeutral`(en:"Use /provider to configure a third-party provider with your own API key";zh:"请用 /provider 配置第三方 Provider(自带 API Key)")与 `onboarding_wizard::provider_unavailable_msg()`(按 `managed_login_available()` 二选一,与既有 `not_signed_in_msg()` 同构);mod.rs 5 处 + commands.rs 2 处(goal/loop `StartGoal/StartLoop` dispatch 失败)全部改走该 helper;其中提交拒绝 match 的 `AuthenticationRequired` 臂改走 `not_signed_in_msg()`(与 status bar 臂 28388 行既有行为对齐,托管构建显示未登录、中立显示 BYO),`None` 臂走 `provider_unavailable_msg()`。
  - **(MED)`SubmitHeldUntilLogin` 排队提示**:`event_loop/mod.rs` 首条提交在 `AwaitingProvider && !AuthObservation::is_available()` 时提示"run /login 后自动发送";中立构建无登录系统,该条件不可能因"未登录"成立——加 `managed_login_available()` 合取,中立构建回落已有的 `SubmitHeldUntilProviderReady`("provider 尚未就绪,消息已排队,就绪后自动发送",文案本就中立),无需新消息。
  - **(LOW-MED)WebUI 模型设置弹窗 intro**:`settings.modelsIntro` 原文"Official CodingPlan models are managed by your login/官方 CodingPlan 模型由登录状态同步管理"在 `ModelConfigDialog` 无条件渲染。拆为两条:base `modelsIntro` 改中立 BYO 文案(双语),新增 `modelsIntroManaged`(托管同步说明),组件 `useAuth()`(复用 `LoginButton.tsx` 导出的轮询 hook,无循环依赖——LoginButton 仅依赖 preact/settings)取 `managedAvailable`,仅 true 时追加渲染托管句。顺带删除两个**死键** `cmd.status.body`/`cmd.status.notLoggedIn`(全仓 grep 无引用,/status 走 daemon 文本;死键里含 "login {login}" 段,防止将来接线泄漏)。
  - **(LOW)TUI 欢迎提示池 `/usage` 死路**:`render/welcome_tips.rs` 的 `POOL` 常量无条件含 `/usage`("view token usage & quota")提示——第三轮已把 `/usage` 从中立构建所有发现面隐藏(手敲只回 `UsageCodingPlanOnly` 不可用通知;**2026-09-09 补注:该 Msg 变体已随 i18n 收尾任务退役,隐藏行为本身不变**),提示池却仍随机广告它。新增 `const MANAGED_ONLY_TIP_CMDS: &["/usage"]` 与 `tip_allowed()`(谓词同源 `onboarding_wizard::managed_login_available()`),`choose_pool_indices` 过滤候选、`tips_from_indices` 对缓存索引防御性过滤;新测试 `managed_only_tips_never_surface_in_neutral_build`(64 个种子,新鲜选择与缓存解析两路都不得出现 `/usage`)。
  - **VS Code 死代码清理(审计 SHOULD-FIX 落地)**:删除 webview 死组件 `webview-ui/src/components/ProviderSettings.tsx`(零引用的旧设置浮层,唯一引用是过期构建产物 `webview/webview.js`——esbuild 输出、git 未跟踪,重建即刷新;删后 `settings-overlay` class 在新 bundle 中 0 命中)。随之移除 `ChatProvider.tsx` 中**无消费者**的 5 个 context action 包装(`startLogin`/`cancelLogin`/`setupCodingPlan`/`refreshSetupState`/`setDefaultProvider`——唯一消费者就是该死组件;WelcomeScreen 用本地 `postMessage` 直发,host 消息处理不受影响):接口成员、`useCallback` 定义、value 条目三处同删,留注释说明 setup/login action 刻意不做 context 方法。
  - **验证**:`cargo fmt --check` 通过;`rustcode-config --lib` 328/0、`rustcode-tuix --lib` **2062/0**(新增 1)、`rustcode-daemon --lib` **306/0**(新增 1);`cargo clippy -p rustcode-tuix -p rustcode-daemon -p rustcode-config --all-targets` 0 新增告警;webui `tsc --noEmit` 0 错、`npm test` **221/0**、`npm run build` 成功后按铁律 `cargo clean -p rustcode-daemon`(dist 嵌入刷新);VS Code 扩展 host + webview `tsc` 双 0 错、`test:webview` 11/11 组通过、`build:webview` 成功;全工作区 `cargo test --workspace --no-fail-fast` 复跑 **5472 passed / 1 failed**,唯一失败为文档化已知红 `mcp::registry::tests::trust_key_golden_matches_core_algorithm`(DefaultHasher 不稳定,铁律禁止改)。
  - **刻意保留(sweep LEAVE 留档)**:`ProviderPanelManagedAccountHint`(仅选中托管账号时显示)、`CpOfficialBuildRequired`/`StatusOfficialBuildRequired`(仅 `is_codingplan_gateway(base_url)` 且 signer 缺失的误配边缘)、api_provider.rs 五处 "managed by /login"(仅 `selection_is_managed()/account_is_managed()` 成立)、`ProviderInitNeedsLogin` 与 webui `settings.contextWindowLocked` 死消息/死键(不可达,留待清理)、MCP OAuth `/mcp login`(第三方 server 登录,合法 BYO)、clix 签名网关报错(上轮已中立)。**(第八轮 LEAVE 中的 api_provider 五处、`ProviderInitNeedsLogin` 族、provider_panel 两条 hint 已在第九轮收尾。2026-09-09 补注:is_codingplan_gateway 与整个签名层已删除,上述两条 Cp 前缀消息与 clix 签名网关报错现已不可达,随 i18n 收尾任务一并退役。)**
- **[DONE] 第九轮多 agent 校准:门控谓词一致性审计 + 纵深防御/死代码/边缘文案收尾(2026-09-01,general-purpose 高努力审计 agent 报 0 BLOCKER + 6 NIT,全部 triage 落地)**:
  - **审计结论 "GATE CONSISTENCY CLEAN"**:第八轮全部改动逐条核验 PASS——daemon login 行空串拼接干净、`provider_unavailable_msg()` 七处调用点无遗漏(零直接 `Msg::CmdProviderUnavailable` 引用)、`SubmitHeldUntilLogin` 合取正确、welcome tips `tip_allowed()` 覆盖新鲜选择与缓存索引两路、i18n 双语 arm 穷尽匹配编译期保证、webui zh/en 字典 380/380 键 parity(死键确认删除)、VS Code ChatProvider/ProviderSettings 删除面干净、WelcomeScreen 所有 postMessage 调用点均在 `managed_available === true` JSX 内、Kotlin `?: false` fail-closed 一致;漂移审计:`platform_server()`/`platform_base_url()` 直接读取点除 oauth.rs/endpoints/welcome_tips 三处特许外**为零**;`ChatAuthExpired` 仅 signer 存在时触发、`codingplan_sign` /login 错误需网关+signer、`StatusCp*`/`CodingPlanSetupFailed` 在 `#[cfg(feature="codingplan")]` 后、ACP 命令广告经 `command_visible` 过滤。**[2026-09-09 补注]** 本条中的签名层、Cp 前缀状态消息与 setup 失败消息、该 cfg 门控均已删除,相关核验对象不再存在;命令可见性过滤的结论仍有效。
  - **NIT1(纵深防御真 bug)**:`rustcode-auth/src/oauth.rs::start_login()` 守卫误用 `platform_base_url().is_empty()`——该函数把 `""` sanitize 成 `"http:"`,条件**恒 false**,中立错误永不返回(调用方上游已门控故零用户可见影响,但防线失效)。改为 `if !managed_login_available()`(同文件谓词,RAW 值+trim);错误文案改中立 BYO 指引(不再提 `/login`);顺带修正谓词文档注释里 `platform_server().is_empty()` 的陈旧描述为 `.trim().is_empty()`。
  - **NIT2(单一事实源)**:`welcome_tips.rs::pinned()` 直接读 `platform_server().is_empty()`(无 trim,与谓词漂移;不可达但违反对齐),改委托 `onboarding_wizard::managed_login_available()`(与 `tip_allowed` 同源)。
  - **NIT3(死消息清理)**:`ProviderInitFailed{detail}`/`ProviderInitNeedsLogin`/`ProviderInitSourceBuild`/`GatewayAuthUnavailable{base_url}` 四个 Msg 变体**零生产引用**(渲染点在 commit 59d4c284 "retire legacy engine bridge" 中移除,仅剩两个 i18n 测试引用)——messages.rs 声明、en.rs/zh_cn.rs arm、mod.rs 两个测试及随之失活的 `has_cjk` test helper 全删(config 328→326)。**Cp 前缀签名族当时判为保留**(`CpOfficialBuildRequired`/`CpAuthRequired`/`CpSignStaleClockSkew`/`CpSignReplayPersisted`/`CpSignVersionTooOld`/`CpUpgradeRequired`):是闭源发行构建(`codingplan-crypto` overlay)的 i18n 契约,有专门 `codingplan_crypto_tests` 双语守护且文案已中立化(断言含 BYO/distribution 指引)。**该保留结论已于 2026-09-09 被裁决 Q3 推翻:闭源发行构建的签名 overlay 与闭源桩已删除,Cp 前缀全族按裁决随之退役,i18n 三件套中的这些变体与其双语守护测试模块均已删除(实测 0 命中);唯一残留是 tuix 的 render/retained.rs 里一处测试注释仍引用已删除的 Msg::CpLocked 模板名,已登记为后续清理项。** 原文结论(已作废):按"门控不删除"铁律不动。
  - **NIT4(边缘可达死路文案)**:daemon `api_provider.rs` 五处 403 `"CodingPlan providers are managed by /login"` 按名/网关检测触发,中立构建仅当用户手写 `RustCode*` 保留名 provider 时可达——新增 `managed_provider_locked_message(action)` 按谓词二选一(托管:原文案;中立:保留名说明 + 改名/自带 api_key 指引),modify/replace/edit×2/delete 五处全切,陈旧注释同步;tuix `provider_panel.rs` 两条提示栏(`ProviderPanelManagedModelsHint` 含 "managed by /login"、`ProviderPanelManagedAccountHint` 提托管账号)新增 `*Neutral` arm(双语,键位提示尾部不变),两个渲染点按谓词选择,删除保护注释改中立。新测试 daemon `managed_locked_message_is_neutral_without_service`(4 个 action 全断言无 `/login` 且含 `api_key`)。
  - **NIT5(marketplace 插件 git 认证提示)**:`plugin/marketplace.rs::auth_required_message()` 可信主机+未登录臂提示 `/login`——可信域名默认空(`HOSTED_TRUSTED_DOMAINS: &[]`),仅 `RUSTCODE_TRUSTED_HOSTS` 显式 opt-in 可达;修复为 `!host_is_trusted(url) || !managed_login_available()` 均回落 SSH/git 凭证指引(与不可信主机同文案),文档注释补中立分支;新增 `relogin_hint()`,clone/pull 注入凭证重试仍失败的两处 bail 改用它——覆盖"中立构建残留旧发行版 `auth.toml` 导致 `auth_retry_args` 返回 Some、重试失败后提示 /login"这条**此前可达**的死路。新测试 `auth_required_message_neutral_build_never_pitches_login`(谓词 false 时两类 URL 均无 `/login` 且给 SSH 路径)。
  - **NIT6**:`rustcode-auth/src/lib.rs` Windows-only save-auth 错误上下文 `"please use /login again"` → `"please sign in again"`(该路径仅门控登录流可达;措辞改构建中立)。
  - **文档同步(第八轮文档审计 finding 5 收尾)**:`crates/rustcode-daemon/README.md` CodingPlan 节改标"仅发行版本"——`/codingplan/*` 位于 `#[cfg(feature = "codingplan")]` 门控后,默认构建不编译(404),引导走 `POST /providers`/`config.toml` BYO;源码树 `api_codingplan.rs` 注释补 cfg 说明。与 `site/docs/{zh,en}/headless-daemon.html` 既有口径一致。**[2026-09-09 补注]** 该 README 小节已再次改写为"CodingPlan(已于 2026-09-09 移除)",并注明 api_codingplan 源文件与 codingplan feature 已删除;此处"仅发行版本"的口径仅作沿革。
  - **验证**:`cargo fmt --check` 通过;`cargo clippy --workspace --all-targets` exit 0;config 326/0、auth 42/0、capabilities 默认 823/0 且 `--features plugin` 978/0(新增 1)、tuix 2062/0、daemon 307/0(新增 1);全工作区 `cargo test --workspace --no-fail-fast` **5472 passed / 1 failed**,唯一失败仍为文档化已知红 `trust_key_golden_matches_core_algorithm`(DefaultHasher 不稳定,铁律禁止改)。期间 `/workspace` 磁盘 100% 满,删除可弃的 `target/debug/incremental`(15G)恢复,不影响产物正确性。
  - **LEAVE/deferred**:JetBrains 硬编码 zh/en 字符串迁移 bundle(SlashCommand labels 等;本机无 JDK/gradle,仅源码级审计);webui `settings.contextWindowLocked` 死键(零引用,留待顺手清理)。
- **[DONE] 第十轮:默认中文落地——全用户面 i18n 接线(2026-09-01,多 agent sweep 报告 B/M/L 系列逐条落地)**:本轮不改门控/架构,只把此前各轮新增的 `Msg` 变体**接到调用点**,并补齐遗漏面。范围:spinner/done 标签池与后缀(B1-B4/L10,tuix render)、CLI 首启升级流接既有 `Upgrade*` arm(B6/L6)、TUI `event_loop`/commands 文案(M1-M14,L1-L5/L8)、五个 modal(proxy_picker/plugin_manager/file_viewer/session_picker/`proxy.rs` 汇总,M15-M19)、CLI 各面(daemon 启动、headless 标签、login 状态、mcp/hooks/plugin、schedule、uninstall frontend,M21-M29)、`rustcode-review` 未完成文案(B5)、**clix `rustcodex` 全量(M30)**。
  - **本地化边界(本轮统一口径,后续照此)**:人类可读的报告骨架/活动行/banner/状态/提示走 `t(Msg)`;**不译**:稳定 ASCII 标签(`[rules]/[scope]/[coverage]/[retry]/[ok]/[x]/[+]/[yolo]/[stdin error]/[agent terminated]/[error]/[warn]` 等,标签留在调用点、标签后的句子进 arm)、模型面文本(persona、review task、文件 checklist、VERIFY_LENS)、工具名/JSON 键值(含 `--json` 信封文案)、持久化 token、键入式判定 token(`y/yes/always/n`)、斜杠命令名、`StopReason {:?}` 调试 id、优先级 id P0-P3、shell 命令示例、trace 节标记。en arm 逐字保留原英文(冒烟核对 byte-for-byte),zh arm 新写;默认 `Locale::ZhCn`。
  - **clix(M30,本轮主体)**:`rustcode-config` 新增约 85 个 `Clix*` 变体(messages.rs + en.rs/zh_cn.rs 双语 arm 穷尽,编译期保证 parity);`rustcode-clix/src/{main.rs,code.rs}` 全部人类面接线——`review()` 的 stdin 冲突/仓库定位/规则注入/trace banner/token 行/scope 过滤/coverage 六道诊断/最终结论/bail/warn、`render_findings()` 报告头、ReviewRun 工具流、config/task/prompt/diff/gh/git 全部错误上下文;`code()` 交互 REPL 的会话行/准备行/turn 结局/压缩/审批/yolo/slash 帮助与记忆命令;`sessions()` 列表行(保留 `{:<28}`/`{:<4}` 列宽)。**locale 引导**:clix 无 `--lang`,在 `main()` 的 `bootstrap_home()` 后、`Cli::parse()` 前用 `load_config_selection(None,None)` + `resolve_initial_locale(None, language)` + `set_locale()`(缺/坏配置忽略,子命令自己会再报错),`code()/sessions()` 读各自配置后再设一次。断言英文的测试一律 `test_lock()` + `set_locale(Locale::En)`(clix 3 处;review 见下)。冒烟实测:zh/en 双语下空 diff、签名网关 bail(中立措辞"受管网关/第三方供应商",env 名与 `--provider` 不译)、`[rules]` 标签、sessions 空/行、code 缺 provider bail 均正确;en 输出与原字面一致。
  - **两个 clap i18n 坑(CLI batch M,留档防复发)**:① clap 内置 `help` 子命令只在 `build()`(parse 时)实例化,对未 build 的 `Command` 调 `mut_subcommand("help", ..)` 会 panic("Command `help` is undefined")——`build_i18n_command()` 不要碰 help,其 about 留 clap 默认;② `try_print_shell_completion()` 在 i18n 帮助块之前用裸 `Cli::try_parse()`,其 `Err(e) => e.exit()` 会打出英文 derive 帮助——按 `error.kind()` 拆分:`DisplayHelp/DisplayHelpOnMissingArgumentOrSubcommand/DisplayVersion` 返回 false 落到 i18n 渲染器,其余才 `exit()`。
  - **顺带修一个真实 locale 竞态**(`rustcode-review/src/fanout.rs`):`finalize_output_is_unchanged_after_the_split` 断言两次顺序渲染**逐字节相等**却未持 `test_lock()`,并发 `pin_en()` 测试可在两次渲染之间(甚至单次 render_deep 的多个 `t()` 调用之间)翻转全局 locale,产出"zh 头 + en 身"的混合串(全量跑偶发红,单跑绿)——与第九轮 `todo_command_text_with_and_without_list` 同类。补 `let _g = pin_en();`。**教训复现:凡断言本地化输出(尤其实质性相等/包含英文 prose)的测试必须持锁钉死 locale。**
  - **验证**:`cargo fmt --check` 通过;`rustcode-config --lib` **327/0**、`rustcode-clix` **44/0**、`rustcode-review --lib` **100/0**(连跑 5 次不复发);全工作区 `cargo test --workspace --no-fail-fast` **5473 passed / 2 failed**——2 个失败分别是文档化已知红 `mcp::registry::tests::trust_key_golden_matches_core_algorithm`(DefaultHasher 不稳定,铁律禁改)与上述 fanout 竞态(已修,修复后等效 5474/1)。期间 `/workspace` 两次 100% 满致链接器失败,清 `target/debug/incremental`(可弃缓存)恢复。
  - **LEAVE/deferred(留档,勿再报)**:clix clap derive 文档串(`ReviewArgs/CodeArgs` 的 about/arg help)仍为英文——独立低频 bin,无 `build_i18n_command` 等价物,后续可仿 CLI 做 mutate;ACP stderr 诊断(操作者面、低优先);session log 标记;clix 模型面文本(review task/persona);`schedule_os.rs` 底层诊断串。
- **[DONE] 第十一轮:剩余用户面 i18n 收尾——daemon/auth/updater/config 诊断 + TUI 用量弹窗/向导 + 桌面通知 + WebUI 前端(2026-09-01,11A–11G 七批次)**:第十轮接完 TUI/CLI/clix 主流程后,本轮 sweep 此前未覆盖的用户面:
  - **11A–11D(Rust 后端各面)**:daemon 启动横幅与致命行(11A);daemon Web/API 错误面——`api_auth/api_codingplan/commands/api_provider/live_api/lib.rs` fs 诊断(11B);auth `oauth.rs` 交互式登录提示(11C);capabilities MCP 配置/注册表与插件市场错误(11D,含 `mcp::config` JSONC 改写拒绝测试钉 En)。
  - **11E(tuix)**:用量弹窗全量接线——`Usage*` 族变体;表头用 `pad_left/pad_right` 闭包按 `crate::width::display_width` 手动补 CJK 列宽(Rust `{:<n}` 按字符数填充会让中文错位,列宽 26/10/9/7 保持)、日历月/周标签、图表标题 `UsageTokensPerDay`、连续天数 `UsageDays{n}`、sparkline 元信息行 `UsageSparkMeta{pct,reqs,tokens}`(tokens 由调用方预 humanize,717016 → `717.0k`);引导向导四屏步骤指示器改 `OnboardingStepIndicator{current,total}`(draw_panel 测试传字面量 "Step 3/3" 作输入数据不受影响)。托管专属 QR 扫码屏正文(微信扫码/CodingPlan 额度)保留硬编码中文——中立构建被 `managed_login_available()` 门控不可达。
  - **11F(updater/CLI/config/daemon)**:新增约 30 个变体——updater 自更新全链路(替换恢复、备份保留/删除失败、无 release/无 target、manifest/download HTTP 状态、短下载、校验和不匹配、exe 无父目录、安装目录不可写,`UpgradeDirNotWritable` 保留字面 `sudo rustcode upgrade` 命令示例);CLI `parse_plugin_spec` 空规格/半空规格;CLI `upgrade` 新增独立 `parse_already_latest_versions`(与 TUI event_loop 那份逐字一致,抽版本号后渲染 `UpgradeAlreadyLatest`——**ALREADY_LATEST body 是固定英文解析契约,不译**);config 遗留 provider 迁移错误 + 8 条账号/模型校验诊断 + 3 条模型解析错误(反引号 TOML 键/ID 在两语中逐字保留);daemon `resolve_chat_provider` 两条 bail。updater 的 `.context()` io 诊断与 `PACKAGE_MANAGED` 留英文(低层诊断/机器契约)。
  - **11G(WebUI 前端,本轮主体)**:`webui/src/i18n.ts` 在既有 zh 默认字典 + en `Record<MsgKey,string>` 之上新增**无 React 依赖查表器**:`resolveI18n(lang,key,params)`(查表回落链 table→zh→key 与 `{name}` split/join 插值的唯一实现)、`readStoredLang()`(读 `'rustcode.lang'` localStorage,与 settings.tsx 同一契约;无 storage/未知值回落 `DEFAULT_LANG='zh'`)、`translate(key,params)`(组件树外模块每次调用实时读语言);settings.tsx 的 `t()` 收敛为 `resolveI18n(lang,..)` 薄包装(语言切换仍经 React 重渲染)。新键:`notify.title.*/notify.status.*`(10 个,浏览器完成通知,文案与 Rust `notify.rs` 对齐)、`login.*` 5 个(**合并删除 LoginButton.tsx 内联 `L` zh/en 对象**,`labels` 返回形状不变)、`at.loading/at.noFiles`(@ 文件弹层)、`chat.dismiss`(persistence warning 的 aria-label)、`sidebar.accountFallback`、`userInput.ownAnswer`、`cwd.removeProject`、`settings.modelIdPlaceholder/providerNamePlaceholder`。接线点:`lib/notifications.ts`(title/statusForStopReason)、`Chat.tsx`(Loading/No files found/Dismiss)、`Markdown.tsx`(marked renderer 在组件树外拼 HTML 字符串,Copy/Copied 复用既有 `copy.copy/copy.copied`;onClick 写回同理)、`Sidebar.tsx`(账号 title 回落 'account')、`UserInputCard.tsx`(两处硬编码"输入自己的答案…")、`CwdPicker.tsx`("移除此项目")、`SettingsDialogs.tsx`(两处 model-id / 一处 provider-name placeholder)。
  - **node --test 模块解析坑(留档防复发)**:非 React 模块的值导入必须带 `.ts` 扩展名(`import { translate } from '../i18n.ts'`)——`node --experimental-strip-types` 无打包器解析,此前 lib 模块跨文件只有 `import type`(擦除后无运行时解析)侥幸不带扩展名;tsconfig 开 `allowImportingTsExtensions`(vite 同样解析显式扩展名)。断言英文镜像文案的 notifications 测试改为在 stub localStorage 里 `setItem(LANG_STORAGE_KEY,'en')` 钉死语言(无 storage 时 translate 回落 zh,会打破英文断言)。新增 `src/i18n.test.ts` 6 个守卫:zh/en 键集 parity、默认 zh、插值、无 storage 回落、持久化偏好读取(含未知值)、所有值非空字符串。
  - **桌面通知 TUI 侧同步本地化**(capabilities `notify` feature,与 WebUI `notify.*` 对齐):新增 `NotifyTitle{Done,Cancelled,Failed,Stopped}`/`NotifyStatus{...}`/`NotifyRounds{n}`/`NotifyTools{n}`/`NotifyApprovalTitle`/`NotifyApprovalBody{tool}` 共 12 个变体;`notify.rs` 两个 text builder 接线;4 个断言英文 prose 的测试经新增 `en_locale()` 助手(`test_lock()` + `Locale::En`)钉死。
  - **刻意不译(LEAVE,勿再报)**:WebUI `https://api.example.com/v1` 与 `sk-...` placeholder(格式示例,两语相同,example.com 为中立 fixture 域)、`{p.type}` provider 协议名(openai/anthropic/ollama,等同配置值不译)、`tokens`/`k tokens` 后缀(zh 字典既有约定保留英文 tokens,见 `cmd.cost.body`)、`api.ts` console throw(开发者面)、updater `.context()` io 诊断与 `PACKAGE_MANAGED`/ALREADY_LATEST body(机器/解析契约)、托管专属 QR 屏正文(中立构建不可达)。
  - **验证**:WebUI `npm run typecheck` 0 错、`npm test` **227/0**(原 188 含 notifications 文件加载失败;修复后全量)、`npm run build` 通过并按规约 `cargo clean -p rustcode-daemon`(cargo 不追踪 `webui/dist/`);Rust 侧 `cargo fmt --check` 通过,config 327 lib 测试、capabilities notify 15/0,全工作区 `cargo test --workspace --no-fail-fast` 89 个测试二进制全绿,唯一失败为文档化已知红 `mcp::registry::tests::trust_key_golden_matches_core_algorithm`(DefaultHasher 跨工具链不稳定,铁律禁改);clippy 无新增警告(仅既存平台死代码 `parse_scutil_proxy`/`windows_shell_label`)。locale 竞态教训同第十轮:凡断言本地化输出/英文 prose 的测试一律 `test_lock()` 钉 En(本轮 tuix usage 6 处、updater 3 处、daemon/config/mcp 各 1 处、notify.rs 4 处)。
- **[DONE] 第十二轮:多 agent sweep 校准落地——webui 死键/漏译清理 + TUI 用户输入面板/plain 渲染器/模型选择器/CLI 崩溃钩子 i18n(2026-09-01,三 agent sweep 报告 triage)**:
  - **sweep 结论(校准基线)**:**中立性 agent 判 CLEAN**——零遥测 SDK、`HOSTED_*` 端点默认全空、`atomgit` 仅作默认关闭的 cargo feature/模块保留、OpenRouter 归因头属合法 BYO 且 Referer opt-in;webui agent 报 29 个死键与 3 处真漏译;Rust agent 报 TUI/CLI 一批按 `unicode_symbols` 错分语言的内联串。
  - **webui(先落地)**:`i18n.ts` zh/en 两表**删 29 个死键(58 行)**(attach.imageSoon/filepicker.noFiles/settings.title 等全零引用键,含 `time.*` 六个——`formatMsgTime` 输出原始 `YYYY-MM-DD HH:MM:SS`);新增 `mcp.trustFailed` 并接入 Sidebar.tsx 两处 MCP trust 回落;`Chat.tsx` 模块级 `messageFullText`(复制按钮,组件树外)由硬编码 `参数:`/`输出:` 改 `translate('tool.args')/('tool.output')`;第二处 `'account'` 回落改 `sidebar.accountFallback`。tuix `provider_panel.rs` 两处陈旧 "atomgit" 注释改中立措辞(guard 断言 `!ids.contains("atomgit")` 本身保留)。
  - **Rust 本轮主体:TUI 用户输入面板语言错分修复**。`retained.rs` 面板此前按 `self.caps.unicode_symbols`(终端**字形能力**)选中英文——UTF-8 英文用户被喂中文、ASCII 终端靠这个标志才幸免;改为 `let lang = if unicode { current_locale() } else { Locale::En }`:**语言跟 locale,仅当终端根本不能渲染 CJK(legacy conhost/哑管道)才回落英文**。新增 18 个变体并接线:`UserInput{TextPlaceholder,OwnAnswer,SubmitRow,SubmitLabel,HintSingle{n},HintMultiple,HintText,BatchNav{index,total},ReviewTitle,Answer{answer},Unanswered,SubmitAll{answered,total},HintSubmit,HintBatch}`、`PlainAgentsStatus{finished,total,failed}`、`ModelPickerEmpty{NoProviders,NoMatch,Query{query}}`、`CliCrash{Header{info},Report}`(en arm 与原逐字一致)。
  - **plain.rs**(管道/legacy 渲染器):新增 `prose_lang()`(同 lang 规则);子代理状态行 `Agents: x/y finished . z failed`、`[Error: …]`(复用既有 `ErrorPrefix`/`[错误：]`)、`(cancelled)`(复用既有 `Cancelled`/`（已取消）`)、custom-answer 占位(此前**无条件硬编码中文**)、`+ Submit` 行(此前**无条件英文**,改 `+ 提交`/`+ Submit`)。**model_picker.rs**:三处空态(未配置 provider/无匹配/查询无匹配)接 `t(Msg)`(该文件首个 i18n 接线)。**CLI main.rs 崩溃 panic hook**:`RustCode crashed: …` 横幅与发行渠道反馈指引本地化(钩子早于任何子系统,默认 locale 即中文,符合预期)。
  - **测试锁定(教训复现)**:断言本地化输出的 5 个 tuix 测试补 `test_lock()` + `set_locale(ZhCn)`(user_input_panel_renders_all_three_modes、custom_answer_cursor、active_custom_answer、empty_text_answer、user_input_batch_navigator);断言英文的 ascii-caps 渲染**无需锁**(ascii 终端 lang 强制 En,与全局 locale 无关)。**vterm 双宽坑留档**:测试 VirtualTerminal 给 CJK 字符补占位空格(`选 择`),断言不能用整词中文,要按 ASCII 片段 + 单个 CJK 字素(`r.contains("1-3") && r.contains('选')`)。
  - **刻意不译/DEFERRED(勿再报)**:`Tab: …`(键位名前缀)、`[Image #N]`(两渲染器一致的回显视觉契约,注释明示按用户输入匹配);welcome 横幅 `RustCode {model} {dir}`(品牌名+值,无 prose);daemon HTTP 错误体(`lib.rs`/`live_api.rs` CRUD 错误,被 WebUI 当字符串消费且 WebUI 自有键);`coding/src/runtime.rs` 的 `RuntimeError`/`ProviderUnavailableReason` Display(L2 跨 crate 错误契约,进 anyhow 链,需调用点分析);`config_panel.rs` + `settings.rs` 的 `label_en/label_zh` 成对内联(量大且已按 locale 工作);file_viewer/diff_viewer/rewind 的 `l(en,zh)` 助件(功能正常,纯收敛项);session_picker 预览标签、ACP stderr 诊断、clix clap derive 串(第十轮 LEAVE)、vision.rs 原因串、uninstall pid 行。
  - **验证**:`cargo fmt --check` 通过;`rustcode-config` 327/0、`rustcode-tuix` **2063/0**、`rustcode`(cli)lib 116/0 + 集成各绿;全工作区 `cargo test --workspace --no-fail-fast` 全绿,唯一失败仍为文档化已知红 `mcp::registry::tests::trust_key_golden_matches_core_algorithm`(DefaultHasher 不稳定,铁律禁改);`cargo clippy` 无新增警告(retained/plain 附近警告逐条核对为既存 doc 缩进/manual_clamp 等);`scripts/test-headless.sh` 通过(5 项网络 skip)。期间 `/workspace` 一度 100% 满致链接器失败,清 `target/debug/incremental` + `examples`(纯缓存)恢复。
- **[DONE] 第十三轮:第二次多 agent 校准 sweep——中立性复核 CLEAN + WebUI 零硬编码 + daemon 实时线/登录轮询错误体与 TUI 内联双语对收口入 i18n 目录(2026-09-01,三 agent 并行 sweep)**:
  - **sweep 结论(校准基线)**:① **中立性 agent 再判 CLEAN**——零遥测 SDK/依赖(webview.js 的 `amplitude` 是 React DevTools 的 SVG 属性;extension 命中均为 "zero telemetry" 隐私声明;`tracing` 仅本地文件/stdout),`HOSTED_*` 端点默认全空,`atomgit` feature 与模块 `#[cfg]` 关闭(**2026-09-09 补注:同句的 `api_codingplan` 模块与其 `#[cfg(feature="codingplan")]` 门控已删除,该模块不再存在**),locale 三个回落点 + WebUI 默认 zh 无漂移,产品字符串零彩色 emoji(仅 ✓✗⚠☰ 等单色标记,合规)。② **WebUI agent:用户面硬编码 CJK = 0**;13 个 finding 全 LEAVE(`https://api.example.com/v1`/`sk-...`/`~/...` 是两语相同的格式示例占位,第十一轮已 LEAVE;`tokens`/`ms` 单位后缀约定保留英文;`(1/3)` 纯数字标点;`[EDIT]/[X]/[#]/[D]/[F]/[<]/[*]` 是 ASCII 图标标签;api.ts throw/console 开发者面;服务端数据不译)。
  - **唯一中立性 nit(已修)**:`tuix/src/event_loop/oauth_poll.rs` 模块文档与 `OauthEvent::Authorized` 注释里 3 处 "AtomGit OAuth/consent" 改中立措辞(managed-login OAuth / in-browser consent)。模块本身非 cfg 门控但事件只在托管登录流产生(中立构建不可达),与既有 QR 屏 LEAVE 同性质——仅改注释。
  - **Rust LAND(29 个新变体)**:
    - **daemon 实时线错误体(`live_api.rs`,WebUI 聊天面可见,原封不动英文直发)**:`Live{Compact,ProviderReload,ProviderDeactivation,SnapshotRestore,Undo}Failed{error}` 五个包装(内层 error 保留原始诊断,前缀本地化);`ProviderUnavailable` 事件原先 `reason.to_string()` 直发英文 Display——改为边界 match 三变体 → `LiveProviderNotConfigured/AuthRequired/UnsupportedBuild`(UnsupportedBuild 措辞中立:managed signing gateway/distribution build/第三方 Provider;WebUI 面用 "in Settings" 而非 `/provider`)。daemon `lib.rs` ChatEvent 压缩失败包装同改 `LiveCompactFailed`。locale 语义:daemon 进程 locale(默认 zh),与既有 57 处 `DaemonProv*` 同一先例;彻底跟随 WebUI 语言需发机器 code,列入 deferred。
    - **daemon 登录轮询错误体(`api_auth.rs`)**:`login_session_gone/login_poll_unavailable/login_exchange_failed/auth_persist_failed` 四个英文 body → 新 `DaemonApiLogin{SessionGone,PollUnavailable,ExchangeFailed}` + `DaemonApiAuthPersistFailed`;两处 `login_task_failed` 复用**既有** `DaemonApiLoginTaskFailed`(逐字一致)。稳定 `code` 字段不动(机器契约)。
    - **TUI 内联双语对收口(event_loop/mod.rs,原 `match current_locale()` 绕过目录、无编译期 parity 保证)**:`SessionResume{Cancelled,Cancelling}`、`Rewind{NoPoints,CatalogLoadFailed{error},Failed{error}}`、回退成功横幅拆 5 变体(scope 三词 `RewindScope{Conversation,Code,ConversationAndCode}` + `RewindSuccessMain{scope,prompt}` + `RewindSuccessFiles{n}` + `RewindSuccessEnd`——句末点号 locale 相关(. / 。),files 后缀可选)、`MoreFilesHint{hidden}`(modals/mod.rs diff/view 面板底部);`ImageCacheDropped{n}`——**原硬编码中文独占**(`[Image #{}] 缓存已丢失，已从消息中移除`,en 用户也见中文),en arm 新写;TUI Provider 重载失败三段诊断 `ProviderReloadFailed{error}`/`ProviderReloadSupersededNote`/`ProviderRollbackFailed{error}`(世代竞态/CAS 回滚说明,前缀+两段诊断全本地化)。
  - **LEAVE/deferred(留档,勿再报)**:`api_codingplan.rs` 全部(codingplan feature 门控)——**2026-09-09 补注:该文件已随裁决 Q1=B 删除;下文并列的 event_loop 两处含 CodingPlan 字样的自动配置失败文案也已不存在(crates 下 codingplan 0 命中),但托管 QR 登录流本体仍在门控后保留,见第十九轮补注。本 LEAVE 项自然消解**;event_loop 两处 "CodingPlan 自动配置失败…/login"(QR 托管登录流,中立构建 `managed_login_available()` 门控不可达,沿用第十一轮 QR 屏 LEAVE 先例);daemon `lib.rs` SESSION_* 删除会话错误体(WebUI 已按 `code` 映射自己的 i18n 键,raw body 仅回落);daemon 通用 "Failed to list/create sessions: {e}" 包装(内层低层诊断);**`RuntimeError` Display 本体不改**(L2 错误类型进 anyhow 链/日志;用户面已在 TUI `provider_unavailable_announcement()` 与本轮 live_api 边界两处收口);ACP `commands.rs` 的 "undo failed"/"compact failed"(ACP 编辑器协议面,第十轮 LEAVE);glob 工具输出 "[N more files not shown]"(模型面工具结果);`config_panel.rs` label_en/label_zh 与 `settings.rs` SettingSpec 双标签、file_viewer/diff_viewer/rewind 的 `l(en,zh)`、session_picker 预览标签(均**功能正常、已按 locale 接线**,仅未集中到 Msg 枚举,纯收敛项);WebUI 占位/单位/标签 13 条(约定 LEAVE)。
  - **验证**:`cargo fmt --check` 通过;config 327/0、daemon 307/0(+1 集成)、tuix **2063/0**;全工作区 `cargo test --workspace --no-fail-fast` 全绿,唯一失败仍为文档化已知红 `trust_key_golden_matches_core_algorithm`(铁律禁改);clippy 无新增警告(命中项逐条核对为既存 legacy_convert/too_many_arguments/items_after_test_module 等);`test-headless.sh` 与 `acp_smoke.py` 通过。本轮零测试断言旧串(内联对之前无字符串级测试覆盖),故未新增 locale 钉;改动面均经现有集成测试路径。磁盘两次 100% 满致链接失败,清 `target/debug/incremental`+`examples` 恢复。
- **[DONE] 第十四轮:daemon 实时线全线本地化(修中英混排 bug)+ VS Code 扩展 l10n 接线 + JetBrains 插件资源包级本地化(2026-09-01,接续多 agent sweep)**:
  - **Rust LAND(17 个新 Msg 变体,config i18n 目录 en/zh 双语 arm 编译期 parity)**:
    - **daemon `live_api.rs` SSE 实时面 10 处接线**(WebUI 聊天面可见,原英文直发):会话自动命名失败 `LiveApiSessionNamingFailed{error}`;运行时早停 `LiveApiRuntimeStoppedEarly`;**修复混合语言 bug**——ProviderRetry 警告原 en 文案里嵌中文片段(`"API error {reason}，{backoff_secs} 秒后重试（…）..."`),两 locale 用户均见错串;现 `LiveApiProviderRetry{reason,backoff_secs,attempt,max_attempts}` 双语正确;流恢复 `LiveApiStreamRecovered` / 流超时安全续写 `LiveApiStreamTimeout{attempt,max_attempts}`;输出上限自动续写 `LiveApiOutputLimit{attempt,max_attempts}`;运行时停止 `LiveApiRuntimeStopped{reason}` + `LiveApiRuntimeStoppedForcedSuffix`(`" (forced)"`/`"（已强制停止）"`;机器 `stop_reason:"runtime_stopped"` 字段不动);事件序列化失败 `LiveApiEventSerializationFailed{error}`;非 JSON 对象帧 `LiveApiEventNotObject`;流滞后 `LiveApiStreamLagged{skipped}`;活回合中切模型 `LiveApiActiveTurnModelSwitch`(`active_turn:true` 标志保留);空目标条件 `LiveApiGoalConditionEmpty`(`accepted:false` 保留);批准原因 `PermissionReasonRequiresApproval`(由 LiveApiRequiresApproval 改名,位置中立供 live_api 与 lib.rs 共用)。
    - **daemon `lib.rs` 平行投影**:`Agent::ProviderRetry`/`Agent::OutputTruncationRecovery` 两臂同改新变体;`ChatEvent::PermissionRequest` 原因走 `PermissionReasonRequiresApproval`;提前停止后会话保存失败 `eprintln!` → `DaemonSessionSaveEarlyStopFailed{error}`;panic hook 在 default_hook 前打印 `DaemonPanicHook{loc,msg}`(headless stderr 可见)。
    - **测试钉**:`chat_projector_keeps_output_truncation_recovery_visible` 加 `test_lock()` + `set_locale(Locale::En)`(断言英文 arm;默认 locale 为 ZhCn)。
  - **VS Code 扩展(`extensions/vscode`)**:`daemon/process.ts` 4 串(版本不匹配/daemon 未找到/端口无响应 `{port}`/dev 构建警告 `{path}`)+ `chat/provider.ts` 7 处(回合停止确认失败 `{message}`、附件过大 `{size} KB`、非法批准决定、登录超时/登录状态 `{status}`、会话加载失败 ×2)包 `vscode.l10n.t()`;`l10n/bundle.l10n.zh-cn.json` 68→78 键(英文源串为键);`npx tsc --noEmit` 通过。
  - **JetBrains 插件(`extensions/jetbrains`,本轮重头——原仅 ~16 个 gear/login 键,自定义 Swing 组件大量硬编码英文且有硬编码中文残留)**:plugin.xml 声明 `<resource-bundle>messages.RustCodeBundle</resource-bundle>`,12 个 action 的 text/description 全改 `%action.<id>.text/.desc`;`RustCodeBundle.properties`(en)+ `RustCodeBundle_zh.properties`(zh 值全 `\uXXXX` ASCII 转义,Python 生成)扩至 ~190 键,覆盖 action/statusbar(10,`{0}` 参数)/settings + context.level/titlebar/toolwindow/tab/turn/editor/chat(~45)/dialog(~20)/permission(6)/form(14)/input(10,含 "↑ Send"/"⏹ Stop" 单色标记)/chips/queue/intention(7,标题+模型 prompt)/time(5)/toolcall/image/slash/command/webview 各族;~15 个 Kotlin 文件接线(StatusBarWidgetFactory 10 tooltip 臂;RustCodeConfigurable 11 处;RustCodeContextLevel 加 `toString()` 走 context.level.* 键——**枚举常量名不动以保持久化**;ToolWindowFactory/ToolWindow 菜单;StreamEventHandler;EditorRustCodeActions;三个 SelectionIntention 标题与 prompt;RustCodeChatPanel ~80 处 feed/对话框/表单/权限框/时间格式/斜杠菜单;InputPanel/ContextChipsPanel/PromptQueuePanel;JBCefMessageView webview 不可用回落)。MessageFormat `{0}` 位置参数;本机无 JDK/gradle,**源码级静态校验**:键 parity 0 unused / 0 missing、properties 语法合法、CJK grep 仅剩有意保留的 welcomeContent 双语 map。
  - **LEAVE(留档,勿再报)**:工具结果通道文本(request_user_input 无答复、edit 复读提示、report_finding/todo/web_search 确认)——模型面工具结果;review_tool.rs 三处 "Review complete." 全在 `#[cfg(test)]` mock LlmProvider fixture;VL 标题标记(结构检测契约/测试 fixture);file_viewer/diff_viewer/rewind/session_picker/settings 的 `l(en,zh)`/label_en/label_zh 双标签(79 处,功能正常已按 locale 接线,纯收敛 backlog);lib.rs/webui.rs server-error eprintln(低层诊断);live_hub HubError Display("runtime has no session id" 等,L2 跨 crate 英文契约);SESSION_* 删除 HTTP body(WebUI 按 `code` 自映射);oauth.rs `start_login` 中立构建守卫消息(codingplan/托管登录门控路径)与 `.context()` 低层诊断;JBCefMessageView welcomeContent 中英并行 map(功能正常)。
  - **验证**:`cargo fmt --check` 通过;全工作区 `cargo test --workspace --no-fail-fast` 90 个测试目标全绿,唯一失败仍为文档化已知红 `trust_key_golden_matches_core_algorithm`(铁律禁改);config 327/0、daemon 307/0(+1 集成 token_auth +7 legacy_turn_boundary);clippy 296 警告,touched 文件命中项逐条核对均既存(items_after_test_module 指向有意保留的 codingplan_crypto_tests;print_literal 指向 daemon 帮助里刻意保留的 raw JSON 负载样例——机器样例按规则留英);`test-headless.sh` 2 过 5 网络跳过 0 失败;`acp_smoke.py` SMOKE OK;G6 遥测 grep 零真实命中(segment 均为路径段误报);本轮改动文件零 atomcode 残留。磁盘两次 100% 满致 cc 链接失败,清 `target/debug/incremental`+`examples` 恢复;smoke 两脚本仅需 CLI 二进制,故 `cargo build -p rustcode` 单包链接(daemon 包未在满盘下链接,不影响 gate)。
- **[DONE] 第十五轮:三 agent sweep(两 agent 撞 5 小时配额、余工手动完成)——VS Code manifest NLS 补点 + clix clap 参数帮助本地化 + JetBrains JCEF 内嵌聊天页硬编码中外文修复(2026-09-01)**:
  - **sweep 情况**:并行三个 Explore agent;VS Code manifest agent 完成并给出完整清单,clix/ACP 与 JetBrains 两个 agent 因 provider 5 小时配额(HTTP 429)中途终止,剩余排查全部手动 grep/triage 完成。
  - **VS Code 扩展 manifest(`package.json` + `package.nls[.zh-cn].json`)**:两处长处 manifest 内的品牌串未走 NLS——activitybar 视图容器标题与配置页标题硬编码 `"RustCode"`(line 94/134),改 `%rustcode.viewsContainers.activitybar.title%` / `%rustcode.configuration.title%`,两个 nls 文件各补 2 键(品牌串两语同为 RustCode);顺手把 zh 里 explain/fix/optimize 的 `.title` 从丢了“所选”的短文案补全为“解释/修复/优化**所选内容**”(`.shortTitle` 保持简短)。parity 校验 28 引用 = 28 en = 28 zh,零 missing/unused。
  - **clix(`rustcodex` 独立 CLI)clap 参数帮助**:既有 `build_i18n_command()` 只本地化了三个子命令的 `about`,参数 `--help` 全走英文 derive 默认。本轮把**交互型** `code` 子命令 14 个参数 + `sessions` 的 `--dir` 共 15 个帮助串本地化:新增 15 个 `ClixHelpCode*`/`ClixHelpSessionsDir` Msg 变体(messages.rs/en.rs/zh_cn.rs 编译期 parity),`mut_arg(...)` 链式接线,与主 CLI `rustcode` 的 `CliHelp*` 同一手法。随后补齐 `review` 子命令的 8 个常用连接/输出参数(repo/model/api-key/base-url/provider/config/json/stream-timeout;其中 6 个与 code 文案一致直接复用 `ClixHelpCode*`,仅新增 `ClixHelpReviewRepo`/`ClixHelpReviewJson` 两个变体)。**`review` 其余工程化 fuse/diff 源参数(--base/--staged/--pr/--diff-file/--max-rounds/--max-duration/--graph-max-files/--no-coverage/prompt 覆盖等)有意 LEAVE**——密集工程参考文档且内嵌 shell 示例(`gh pr diff`/`glab mr diff`/`--max-rounds 35` 等 locale 不变),已在函数 doc 注释标明。已运行时验证:`LANG=en_US.UTF-8` 出英文、`LC_ALL=zh_CN.UTF-8` 出中文,参数 id 全部有效(clap 遇错 id 会 panic)。
  - **JetBrains 插件 JCEF 内嵌聊天页(第十四轮 Swing 扫描漏掉的真问题)**:聊天消息由 JCEF 内嵌 HTML/JS 渲染,第十四轮只处理了 Swing 组件;内嵌在三引号 JS 模板字符串里的**实时聊天**标签此前对所有 locale 硬编码——中文 `"思考中"`/`"思考"`(英文用户也见中文)与英文 `"Done"`/`"rounds"`/`"tools"`/`"Image"`/`"Attached file"`(中文用户也见英文),且藏在 """...""" 模板里逃过了上一轮的单引号 CJK 字符串 grep。修法:`buildChatHtml()` 用 `gson.toJson(mapOf(...))` 从 RustCodeBundle 取 7 个 `jcef.*` 键(thinking/reasoning/done/rounds/tools/image/attachedFile)生成 `var UI={...}` 以 UTF-8 注入页面,JS 四处(thinking 指示、reasoning 预览、turn summary 的 Done/rounds/tools、附件回退 Image/Attached file)改读 `UI.*`。`ms`/`tokens` 按单位约定保持英文;welcome 页本就有双语 `welcomeContent()` map(语言切换按钮走 autoglottonym 中文/English,LEAVE)。properties 两文件各补 7 键(zh 值 `\uXXXX` 转义)。
  - **静态 parity(本机无 JDK,源码级)**:修正校验脚本的一个正则错误——IntelliJ 的 resource-bundle 引用是**单个前导 `%key`**(无尾 `%`,与 VS Code 的 `%key%` 不同),改正后 212 used = 212 en = 212 zh,零 missing、零 unused、en/zh 零差异。
  - **LEAVE(留档,勿再报)**:`JBCefMessageView` 的 welcomeContent 中英并行 map(功能正常、按 locale 出语,收敛入 bundle 纯属美观 backlog);`plugin.xml` 的 `<description>`/`<change-notes>`(长段 HTML marketplace 元数据、非运行时 UI 框面);clix `review` 工程参数帮助;clix `render_json(..,"No changes to review.")`(JSON 信封机器值,注释已明示留英,非 JSON 路径走 `ClixNoChanges`);ACP 面 CJK 全在开发注释/协议串(协议面 LEAVE,同前轮);webui 死键 `settings.contextWindowLocked` 复查已不存在,无需处理;clippy clix `large_enum_variant`(Cmd 枚举既有结构,本轮未触)。
  - **验证**:`cargo fmt --check` 通过(首轮 fmt 提示若干 mut_arg 行需折行,已 `cargo fmt` 修正);config 327/0、clix 44/0、tuix 2063/0(全工作区跑时 tuix 曾 1 例 timing 用例在满盘链接压力下失败,隔离重跑即绿,且本轮仅向 config 加变体、clix 不在 tuix 依赖树,逻辑上不可由本轮改动引发);全工作区 `cargo test --workspace --no-fail-fast` 链接成功后唯一失败仍为文档化已知红 `trust_key_golden_matches_core_algorithm`;clippy 无新增警告;`test-headless.sh` 2 过 5 网络跳过 0 失败;`acp_smoke.py` SMOKE OK(CLI 已用新 config 重新链接)。磁盘再次多次 100% 致 cc 链接失败,清 `target/debug/incremental`+`examples` 恢复。
- **[DONE] 第十六轮:收敛 TUI 模态(diff 面板 + 文件查看器)的本地 `l(en, zh)` 临时双语 helper 入编译期 Msg 目录(2026-09-02)**:
  - **问题**:`crates/rustcode-tuix/src/modals/diff_viewer.rs` 与 `file_viewer.rs` 各自定义了一个 `fn l(en: &'static str, zh: &'static str) -> &'static str`,按 `current_locale()` 二选一返回硬编码中英串。这是 t()/Msg 编译期 parity 体系的**漏网面**:新增/改文案不进 `messages.rs`/`en.rs`/`zh_cn.rs`,漏译不报错,且 grep `l("` 因多行调用与缩进极易漏点(本轮初次 grep 只命中 7 处,删 helper 后暴露出 ~30 处)。
  - **做法**:删除两个本地 `l()` helper;两个文件全部调用点改走 `t(Msg::...)`。共新增 **31 个**模态面 Msg 变体(`DiffPanel*`/`DiffScope*`/`FileViewer*` 三族:files-changed/renamed/no-changes/truncated/title/esc/bounded-snapshot/untracked/patch-limit/staged/unstaged/loading/footer-select/footer-scroll/worker-stopped/binary/metadata-no-hunks/initial-changes/uncommitted-changes + file-viewer 的 select/open-external/type-to-search/no-matches/footer/read-failed/not-regular/binary/not-utf8/truncated-marker/footer-back/footer-close),`en.rs`/`zh_cn.rs` 同步补 arm——缺 arm 即编译错,parity 由编译器强制。
  - **类型接线**:`DiffPanelSpan::new(impl Into<String>)` 直接收 `t(Msg)`(Cow 走 Into<String>);`notice_row`/`title_row(&str)` 收 `&t(Msg)`;footer 等 String 字段用 `t(Msg).to_string()`;diff scope 的 match 臂用 `t(Msg).into_owned()`、`Combined => String::new()`;截断标记为保留 ` · ` 分隔符用 `format!(" · {}", t(Msg::FileViewerTruncatedMarker))`(catalog 值仅 `truncated`/`已截断`,分隔符留在调用点);open-external 前缀 catalog 值去尾空格、在 `format!` 内补空格以对齐原输出;`file_viewer.rs` 新增 `use crate::i18n::{t, Msg};`(此前用全限定 `crate::i18n::t(...)`,本轮一并简化)。文案逐字与原 l() 字面量对齐(含标题里 `Initial changes  (…)` 的双空格对齐)。
  - **验证**:`cargo fmt --check` 干净;`cargo check -p rustcode-tuix -p rustcode-config` 全依赖链(auth/updater/capabilities/codingplan/review/coding/daemon/tuix)通过。逐 crate 测试全绿:config 327/0(+集成 7+3)、tuix 2063/0(+plugin_integration 1)、kernel 全绿、review 100/0、codingplan 27/0、capabilities 823/0(+各集成)、coding 429/0(8 network ignored)、clix 44/0、daemon lib 307/0、CLI lib 116/0。clippy 模态两文件零新增(`en.rs`/`zh_cn.rs` 各 1 条 `items_after_test_module` 指向**既有保留**的 `mod codingplan_crypto_tests`,非本轮 arm,属存量 ~420 警告)。G4 `test-headless.sh` 2 过 5 网络跳过 0 失败;G5 `acp_smoke.py` SMOKE OK(CLI bin 已用新 config 重新链接)。
  - **磁盘**:满盘再次致全工作区并发链接失败(`rustcode` CLI bin + `acp_end_to_end` + examples 同时链接溢出,`No space left on device`)。改逐 crate 跑 lib 测试、单独 `cargo build -p rustcode` 出 smoke 用 bin(591MB,链接成功)。CLI bin/examples/acp 集成这几个巨型链接目标在 40G 满盘下无法共存,但其 i18n 逻辑已由 CLI lib 116 测试与 G4/G5 smoke 覆盖,非本轮回归面。
  - **LEAVE(留档,勿再报)**:本轮无新增 LEAVE;既有 backlog 不变——webui 按语言下发机器错误码本地化(daemon->webui,架构级)、JetBrains welcomeContent 双语 map 收敛入 bundle(功能正常、纯美观)、`plugin.xml` 的 `<description>`/`<change-notes>` marketplace HTML、clix `review` 工程化 fuse/diff 源参数帮助(函数 doc 已标注)。多 agent sweep 待 provider 配额恢复(约 2026-09-02 03:04 后)。
- **[DONE] 第十七轮:继续收敛 TUI 模态临时双语面——rewind 回退面板(自有 `fn l` helper)+ session_picker 预览标签 + plugin_manager 市场卸载警告入 Msg 目录(2026-09-02)**:
  - **延续第十六轮的同类漏网面**:第十六轮清掉 diff/file 两个模态的 `fn l` 后,全 tuix grep `current_locale()` 做 triage——23 个调用点 11 个文件里绝大多数是**合法**用途(见下),真正的残留 ad-hoc 双语 TEXT 集中在 rewind/session_picker/plugin_manager 三个模态。
  - **rewind.rs(最大块)**:自带关联函数 `fn l<'a>(en, zh)`,且另有 3 处内联 `match current_locale()` 双语 `format!`。删 helper,15 个调用点改 `t(Msg::...)`;新增 15 个 `Rewind*` Msg 变体(target header / more-above / checkpoint / no-code-changes / files-changed / current / more-below / scope-title / 三个 scope 菜单标签 / unavailable / 两个 footer / start-failed)。**顺手修了一个潜在漏译**:current 行此前 `format!("{{}} (current)")` 对所有 locale 硬编码英文 `(current)`,本轮新增 `RewindCurrent`(en `(current)` / zh `(当前)`)。`row(impl Into<String>)` 直接收 Cow;`suffix` 的空串分支改 `"".into()` 以对齐 Cow 类型。
  - **命名冲突处理**:scope 菜单三个标签不能复用既有变体——目录里已存在 `RewindScopeConversation`/`RewindScopeCode`/`RewindScopeConversationAndCode`,其 arm 是**句中小写名词**(en `conversation`/`code`/`conversation and code`,zh `对话`/`代码`/`对话和代码`),供其它消息句内插用;而模态菜单标签是 `Conversation only`/`仅回退对话` 等不同文案。两者语义不同,故新增三个独立命名变体 `RewindScopeMenuConversation`/`RewindScopeMenuCode`/`RewindScopeMenuBoth`,既有名词变体不动(初版误命名为 `RewindScopeConversation/Code/Both` 撞 enum E0428,已纠正)。
  - **session_picker.rs**:删 `preview_loading_label()`/`preview_unavailable_label()` 两个本地 `-> &'static str` 双语函数,3 个调用点改 `t(Msg::SessionPreviewLoading/Unavailable)`(push_str 处加 `&`),新增 2 个 `SessionPreview*` 变体;补顶层 `use crate::i18n::{t, Msg}`。
  - **plugin_manager.rs**:市场卸载警告 `if zh {format!("  此操作将同时卸载该市场下的 N 个插件：")} else {format!("  This will also uninstall N plugins from this marketplace:")}` 改 `t(Msg::PluginUninstallMarketplaceWarning { count })(ANSI 黄色 wrap 用 Cow Display,输出不变),新增 1 变体。
  - **测试修复**:`bounded_target_window_keeps_default_current_row_visible` 此前依赖硬编码英文 `(current)`(任意 locale 都能断言到),本地化后默认 zh 出 `(当前)` 使英文断言失败;按本仓既有模式补 `let _g = crate::i18n::test_lock(); set_locale(En);`(同文件姊妹测试本就如此),测试改为确定性。
  - **triage 后判定为合法、明确 LEAVE 的 locale 用法(勿再当漏译报)**:`state.rs` 的 `thinking_label`/`done_label` 是按 slot 轮转的**同义词池**(zh/en 两池,跨语言 stall 检测,池选择是内容逻辑非漏译);`render/plain.rs prose_lang()` 与 `render/retained.rs` 两处 `let lang = if unicode {current_locale()} else {Locale::En}` 是 **ASCII 终端强制英文**闸(CJK 在纯 ASCII 终端无法渲染,`t()` 无终端能力感知故不能直接用;未来若要收敛需改用 `t_with(lang, …)`,属大块 backlog);language_picker/onboarding/event_loop 的 `English`/`简体中文` 是**语名 autoglottonym**(按本地化约定保留);海量 `set_locale(...)` 是测试 pin。
  - **验证**:`cargo fmt --check` 干净;config 327/0(+7+3)、tuix 2063/0(隔离重跑全绿);`cargo check -p rustcode-tuix` 全依赖链通过;clippy 模态改动文件零新增(session_picker:825 的 `unnecessary_cast` 是既有 `turn_count as usize` 代码、因删 16 行挪位,非本轮引入;en/zh 两文件的 `items_after_test_module` 仍指向既有保留 `codingplan_crypto_tests`);G4 `test-headless.sh` 2 过 5 跳 0 失败;G5 `acp_smoke.py` SMOKE OK(CLI bin 已重链)。
  - **下轮 backlog(已 triage)**:`config_panel.rs` 的 `fn label(self, zh, selection)` 是最大剩余临时双语面(整页设置项标签 + 标题 `配置 (N/M)`/`Config (N/M)`,独立成轮);`render/retained.rs:5385` 的三个 type-to-filter 占位串(`搜索会话...`/`搜索历史目录...`/`输入以筛选...`)走的是 raw locale 非 lang 闸、可直接进 Msg;retained 两处 lang 闸大块(user-input/permission 行)若收敛需 `t_with(lang,…)` 以保留 ASCII 回退;`event_loop effort_word()`(low/medium/high->低/中/高…)可评估入 Msg。满盘策略不变:逐 crate 跑 lib 测试、单独链 CLI bin 供 smoke。
- **[DONE] 第十八轮:config_panel 设置面板内联双语串入 Msg 目录(9 新变体)+ 区分结构化双语数据表(LEAVE)(2026-09-02)**:
  - **范围**:`modals/config_panel.rs` 的 `draw_payload`/`label` 里散有 ad-hoc `if zh {...} else {...}` 代码字面量。新增 9 个 Msg 变体并改走 `t(Msg::...)`:`ConfigPanelTitle{shown,total}`(`配置 (N / M)`/`Config (N / M)`)、`ConfigPanelResetHint{id}`(再次按 Delete 恢复提示)、`ConfigPanelFooter`(↑↓/Enter/Delete/Esc 键位提示)、`ConfigPanelRetryAttempts{model}`(zh 用全角（）：、en ASCII)、以及 5 个 apply-policy 生效时机短词 `ConfigPanelPolicy{Immediate,NextTurn,Reload,Reprepare,Restart}`(立即/now、下一轮/next turn、重新加载/reload、重建能力/reprepare、重启后/restart)。`title`/`hint` `.into_owned()` 出 String;`policy` 变 Cow,`format!("{{}} . {policy}")` 直接 Display。
  - **明确 LEAVE(结构性双语数据,非漏译)**:`rustcode_config::settings::SettingSpec` 的 `label_en: &'static str` + `label_zh: &'static str` 两个**非 Option** 字段,由 `SETTINGS` 静态表逐条填写(几十个设置项)。这与 `fn l(en,zh)` 散字面量不同:每条记录**强制同时**提供双语(缺字段即编译错),是字段级 parity 的表驱动 i18n(类比 webui 的 zh/en 字典),不是绕过目录的代码串。`config_panel::label()` 的 `Static(setting)` 臂仍按 `zh` 选 `label_zh/label_en`(保留),仅 `RetryMaxAttempts` 这一动态合成臂改走 Msg。把整张设置表搬进 Msg 枚举会增加几十个变体却不增强 parity 保证,判为无收益,不动。
  - **另 LEAVE**:`matches()` 里的 `"retry attempts current model"` / `"重试次数当前模型".contains(&query)` 是**跨语言搜索索引**(用户用任一语言输入都能命中该设置),非展示文案,双串必须并存。
  - **验证**:`cargo fmt --check` 干净;config 327/0(+7+3)、tuix 2063/0(+1);config_panel 无测试断言这些标题/提示/策略词(测试只查 `.id()` 与过滤行为),故无断言需随 locale pin;clippy `config_panel.rs` 零命中;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK。
  - **下轮 backlog(已 triage)**:`render/retained.rs:5385` 三个 type-to-filter 占位串(raw locale、可直接进 Msg);retained 两处 `lang` 闸大块(user-input/permission 行)收敛需 `t_with(lang, Msg::…)` 以保留 ASCII 终端强制英文回退;`event_loop/mod.rs effort_word()`(low/medium/high/xhigh/max -> 低/中/高/超高/最高)可评估入 Msg。modals 目录的 `fn l` 类临时双语面至此清零(diff/file/rewind/session_picker/plugin/config 六个模态全部走 Msg)。
- **[DONE] 第十九轮:provider_panel 自定义 provider 表单残留硬编码中文修复(英文用户见中文的半完成迁移,同第十五轮 JCEF 类 bug)(2026-09-02)**:
  - **发现方式**:第十六~十八轮清完 `fn l`/`if zh` 双语配对后,改用 **CJK 字符串字面量直扫** `modals/*.rs`(单语言残留,非双语配对)。`provider_panel.rs` 列表/toast/字段标签大体已走 `Msg::ProviderPanel*`,但**账号 add/edit 自定义 provider 表单**的若干 live 串(test mod 在 2344 行,故 1986-2253 全是生产代码)是**硬编码 zh-only**:英文用户在自定义 provider 表单里会直接看到中文。
  - **修复(10 个新 `ProviderPanel*` Msg 变体,en/zh 编译期 parity)**:账号表尾的 `＋ 添加自定义 provider`(`ProviderPanelAddAccountRow`,对标已有的 `AddModelRow`);空名称占位 `(必填)`(`ProviderPanelRequiredMark`,en `(required)`);字段标签 `名称`(`ProviderPanelFieldName`/Name)与两处 `协议`(`ProviderPanelFieldProtocol`/Protocol,add 与 edit 各一处);锁协议只读行 `  协议: {x} (锁定)`(`ProviderPanelProtocolLocked{protocol}`);add 表单 footer 带“名称必填；模型到模型页加”全角注(`ProviderPanelAddAccountFormHint`);edit 表单三态 footer(`ProviderPanelEditFormVendorLockedHint` 含 `CodingPlan 仅可改 base_url` / `ProviderPanelEditFormProtocolLockedHint` 厂商协议已锁定 / 可切协议的 `ProviderPanelEditAccountFormHint`);以及 `(该 provider 尚未配置)`(`ProviderPanelProviderNotConfigured`,en `this provider is not configured yet`)。en 串的 ←/↵ 用 `\u{2190}`/`\u{21b5}` 转义写入,渲染与 zh 字面量一致。`api_key` 字段标签是配置键名、保持原样。
  - **既有 LEAVE 复核**:表单里 `CodingPlan` 仅出现在 vendor_locked(托管网关锁 base_url)分支的 footer,该分支在中立构建不可达(托管 provider 不出现),但串保留且本就在 en arm 用 `CodingPlan` 名字(对标既有 `ManagedAccountHint`),本地化不改变可达性。**[2026-09-09 补注]** 该 LEAVE 已消解:vendor-locked footer 的消息变体连同托管 provider 锁一并删除(i18n 目录实测 0 命中),表单里不再有 CodingPlan 字样。
  - **另一个扫描命中面 LEAVE**:`modals/onboarding_wizard.rs` 964-1026 有一整块硬编码中文(微信扫码登录、领取 CodingPlan 免费额度等)——那是**托管 QR 登录流程**,经 `managed_login_available()` 在中立构建中**不可达**,属冻结的 opt-in 保留面(同 codingplan/atomgit),不本地化、不删除,留档。**[2026-09-09 补注]** 该 LEAVE **仍有效但类比对象要更新**:codingplan gate 已删除,可类比的冻结开关现只剩 atomgit Cargo feature;QR 登录屏本体(扫码文案与 tuix 的两个 qr 渲染模块)仍在托管登录谓词门控后,只是其中的 CodingPlan 品牌字样已随 i18n/文案收尾清除(crates 下 codingplan 0 命中)。
  - **验证**:`cargo fmt --check` 干净;live 区(2344 行前)CJK 字面量清零;config 327/0(+7+3)、tuix 2063/0(+1,provider_panel 测试断言本就 `|| en || zh` 双容忍,无断言需改);`cargo check` 通过;clippy provider_panel 零命中;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK(CLI bin 已重链)。
  - **进展提示**:CJK 单语直扫是 `fn l` 清理之后的必要补充——它抓的是**只写了中文/英文一边**的半迁移残留(第十五轮 JCEF、本轮 provider 表单同因)。剩余已知面:onboarding QR 流程(LEAVE)、`state.rs` thinking/done 同义词池、`render` 的 lang 闸大块(需 `t_with(lang,…)`)与 `retained:5385` 占位串、`effort_word()`。
- **[DONE] 第二十轮:菜单 type-to-filter 占位串入 Msg 目录并顺手修掉 ASCII 终端中文乱码隐患(3 新变体)(2026-09-02)**:
  - **范围**:`render/retained.rs` 约 5385 行,三种菜单(SessionList 会话列表 / DirectoryList 历史目录 / 其它通用过滤)的搜索框占位串原是一块裸 locale 代码字面量 `let zh = matches!(current_locale(), ZhCn); if ... {if zh {中文} else {English}}`。新增 3 个 Msg 变体 `MenuPlaceholderSearchSessions`(Search sessions.../搜索会话...)、`MenuPlaceholderSearchDirs`(Search saved directories or enter a path.../搜索历史目录或输入路径...)、`MenuPlaceholderFilter`(Type to filter.../输入以筛选...),en/zh 编译期 parity。
  - **关键改进(不止收敛,还修了一个潜在 bug)**:改成 `t_with(lang, Msg::...)`,其中 `lang = if self.caps.unicode_symbols { current_locale() } else { Locale::En }`。原裸 `current_locale()` 在**纯 ASCII 终端**(无 CJK 渲染能力)上仍会返回 ZhCn 并吐出中文占位串,终端里是乱码/问号;新 gate 与同文件 user-input 行、permission 行以及 `plain.rs prose_lang()` 既有的 ASCII 回退保持一致——CJK 在 ASCII-only 终端强制回落英文。普通 `t()` 不感知终端能力,故此处必须用 `t_with(lang, ...)` 而非 `t(...)`。
  - **本轮 LEAVE 复核(逐一直扫确认,非漏译)**:
    1. `event_loop/mod.rs effort_word()`(low/medium/high/xhigh/max -> 低/中/高/超高/最高,xhigh->extra-high,未知值原样透传)是**完整透传本地化器**,双语齐全且 unknown passthrough 安全,LEAVE。
    2. `state.rs` thinking/done 同义词池(思考中/Thinking 等多词轮换)同为完整本地化器,LEAVE。
    3. 对 `render/retained.rs` 生产区(第一个 `#[cfg(test)]` 后仍逐段核)做 CJK 字面量直扫,仅 3 处 live 命中,**全部无害**:(a) 2734 行 `name == "Uninstall" || name == "卸载"` 与 2920-2932 行 `status.ends_with("(installed)")/"(已安装)"/"(user)"/"(用户级)"/"(project)"/"(项目级)"/"(local)"/"(本地级)"` 等,是对**已本地化标签**做的**双语识别配对**(决定卸载行标红、已装行打勾),不是展示发射;已逐一核对生产者——`Msg::PluginMgrInstalledStatus` -> installed/已安装、`Msg::PluginScope{User,Project,Local}Short` -> user/project/local · 用户级/项目级/本地级,识别串与发射串完全吻合,LEAVE;(b) 10579/10580 行「继续审计代码改动」在 `mod tests` 内,是模拟用户中文 ghost-line 的测试夹具,LEAVE。
  - **验证**:`cargo fmt --check` 干净;config 327/0、tuix 2063/0;`cargo clippy -p rustcode-tuix` 无新增告警(retained.rs 命中的 1062/4129/10490 等均为既有 legacy io_other_error/.into() 类,无一条涉及 MenuPlaceholder/t_with/占位块);CLI bin 重链 OK(先清 incremental/examples 释放磁盘);G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK。
  - **下轮 backlog(已 triage,勿重复上报)**:retained.rs 两处大 `lang` 闸块(user-input 行约 4142、permission 行约 4579)与 `render/plain.rs prose_lang()` 的消费侧——这些**已正确做 ASCII 回退**,但内部仍是 ad-hoc zh/en 代码臂;收敛方式是 `t_with(lang, Msg::…)`(字符串存量较大,需批量建变体)。onboarding 托管 QR 登录流程(中立构建经 managed_login_available() 不可达)、SettingSpec label_en/label_zh 结构化双语表、webui zh/en 字典,均为冻结/结构 parity 面,LEAVE。
- **[DONE] 第二十一轮:/webui 与 /app 远程访问状态串硬编码中文收敛入 Msg(16 新变体)+ 证实 TUI render 路径已全收敛、跨 crate CJK 直扫 triage(2026-09-02)**:
  - **先证伪了一条 stale backlog**:摘要里挂账的 retained.rs 两处大 lang 闸块(user-input 行约 4141、permission/review 行约 4578)与 plain.rs `prose_lang()` 消费侧,实查**早已在前序轮次全部走 `t_with(lang, Msg::UserInput*/PlainAgentsStatus/ErrorPrefix/Cancelled…)`**(navigator「问题 i/N」= `Msg::UserInputBatchNav`)。4141-4720 区与 plain.rs 生产区(730 行前)零裸 CJK/零 zh 代码臂(仅 doc/comment 提及)。TUI 侧 `fn l(` 全仓为 0;残留 `current_locale()`/`ZhCn` 用途逐一核过:language_picker 高亮当前项、config_panel 的 SettingSpec 双语数据表(LEAVE)、state.rs thinking/done 同义词池(完整本地化器,LEAVE)、`effort_word()`(完整透传本地化器,xhigh->extra-high/超高,未知值 passthrough,LEAVE)、`LanguageSwitched` 的 `English`/「简体中文」**autoglottonym**(语种本名,任何 UI 语言下都这么写,LEAVE)、其余为 test。**modals + render 的 ad-hoc 双语展示面至此清零**。
  - **跨 crate CJK 直扫定位真 bug**:cli/daemon/clix 生产区 grep CJK 字面量——coding/capabilities 的绝大多数是 persona/工具描述/工具结果(模型面、默认中文、随快照持久化重放,按 scope 规则 STAY),cli/clix 命中除 `vision.rs` 外全是 test 夹具;真·半迁移在 **/webui 与 /app 远程访问**状态串:daemon `lib.rs ensure_server_and_open/stop_server/ensure_app_server` 与 tuix `event_loop/commands.rs` 的 /app handler 把中文 `format!` 直接返回/渲染(英文用户在 `/webui`、`/app` 看到整屏中文),而同文件早已 `use …i18n::{t, Msg}` 且 AppRemoteStopped 等就走 Msg。
  - **修复(16 新 Msg 变体,en/zh 编译期 parity)**:
    - Webui 面 8 个:`WebuiOpenedBrowser{url}`(已在浏览器打开/Opened webui)、`WebuiOpenManually{url}`(请手动打开/Open manually)、`WebuiBindFailed{host,port,error}`(webui 启动失败…端口绑定失败)、`WebuiRebindHint{bound_host,host}`(已在运行…先 /webui stop)、`WebuiLanWarning`、`WebuiNonLoopbackWarning`(两条 `[!]` 无 TLS/token 安全提示)、`WebuiStopped`、`WebuiNotRunning`。
    - **[SUPERSEDED] App 面 8 个** —— 移动端 App 远程访问(含 `/app <中继>`、`RUSTCODE_APP_RELAY`、`AppRelayClient*`、`AppRemoteLoginRequired`、移动端配对 QR)已随移动端 App 一并移除;`docs/features.md` 现以 frp 风格反向隧道(`RUSTCODE_ENABLE_TUNNEL` + `RUSTCODE_TUNNEL_RELAY` + `/tunnel` 命令)取代之。原 8 个 `App*` Msg 变体(`AppServerBindFailed`/`AppRemoteUsage`/`AppRemoteLoginRequired`/`AppServerStartFailed`/`AppRelayClientStartFailed`/`AppRelayClientSpawnFailed`/`AppPairQrBlock`/`AppPairLinkFallback`)仅作沿革,详见 `docs/archive/`。
  - **要点**:daemon 的 bind err 现在也 `t()` 本地化,tuix 再用 `AppServerStartFailed{error}` 包一层(进程内 webui 同 locale,双层 t() 一致;独立 `rustcode webui` 子命令用 daemon 进程 locale,默认 ZhCn 可覆盖)。en 臂用 ASCII 标点/括号;`[*]`/`[!]` ASCII tag 保留;技术词 webui/token/relay-client/cloudflared/Tailscale/TLS/RUSTCODE_APP_RELAY/`/webui stop`/`/app stop`/`/login`/`rustcode-link://` 两语皆保留。`bin` 实为 String(非 PathBuf),字段直接 `bin: &bin`。
  - **明确 LEAVE(本轮 triage,勿再上报)**:① vision 预处理的载荷标记 `[图片内容（由 {vl_model} 识别）]`/`[图片识别失败]`(cli `vision.rs` 与 daemon `live_api.rs` 各一份)是**折进 UserInput.text 的模型面会话载荷**(类比工具结果输出,默认 persona 中文、随快照持久化、像消息体一样原样渲染),STAY;真正面向用户的 toast 已本地化(zh 1590/1592 `VL 识别图片成功`/`VL 预处理失败`),daemon `lib.rs:832` 把这俩标记当识别配对做剥离。② daemon `live_api.rs:467/475` 的 webui 运行时错误自由文本(切换模式失败/发送用户消息失败)是**已知架构 backlog**:daemon 不掌握浏览器语言,按服务器 locale `t()` 只是把硬编码挪个位置,正解是机器错误码由 webui 按自身语言映射(daemon→webui),本轮不动。③ `api_codingplan.rs` 的 `reset_label` 等在 codingplan 托管特性门后(中立构建关闭),LEAVE——**2026-09-09 补注:该文件已随裁决 Q1=B 删除,本 LEAVE 项自然消解**。
  - **验证**:`cargo fmt --check` 干净;`cargo check -p config/daemon/tuix` 通过(仅 1 条既有 usage_render 括号 warning);config 测试绿、tuix lib 2063/0、daemon lib 307/0(zh 臂逐字复刻旧中文,默认 ZhCn 下既有断言不破);clippy daemon 9/tuix 55 均为 legacy 基线、新 t() 块零新 lint;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK(CLI bin 已重链)。
  - **下轮 backlog**:daemon→webui 错误码化本地化(架构级);onboarding 托管 QR 登录流程(中立构建不可达,LEAVE);webui 前端 zh/en 字典与 JetBrains welcomeContent(结构/门面,LEAVE)。
- **[DONE] 第二十二轮:daemon live-wire 运行时错误(切换模式/发送消息)收敛入 Msg Live* 家族(2 新变体)(2026-09-02)**:
  - **校准多 agent 方案**:审计 agent 建议 `live_api.rs` 的 webui 运行时错误"改用机器错误码而非 t()"。复核后**否决该架构建议的适用前提**——daemon `main.rs:131-132` 启动时已按 `config.language` 经 `resolve_initial_locale` 设定进程 locale,故 daemon 内 `t()` 跟随用户配置语言,与既有 `LiveCompactFailed` 等 Live* 家族完全一致;真·按浏览器语言本地化属更大的架构改造(机器码由前端映射),见 backlog,但不应阻止本轮把硬编码中文挪入编译期目录。
  - **修复**:`live_api.rs` 的 `send_chat_runtime_error(events, msg)` 两处——set_mode 失败、submit 失败——原是裸 `format!("切换模式失败：{error}")`/`format!("发送用户消息失败：{error}")`,改走 `t(Msg::LiveSetModeFailed{error})`/`LiveSubmitFailed{error}`(2 新变体,en/zh parity);经 SSE `ChatEvent::Warning{message}` 进 WebUI 聊天面。错误链 `{error}` 原样透传(raw 诊断,STAY)。
  - **验证**:`cargo fmt --check` 干净;`cargo check -p daemon/config` 通过;daemon lib 307/0、config 337/全绿;G4/G5 通过(CLI 已重链)。
  - **备注**:本轮落地后,第二十一轮 line 432 所挂 "live_api 467/475 本轮不动" 的 backlog 项**已消解**(进程 locale 前提下 t() 即正确);"机器错误码 → webui 按自身语言映射" 仍作为跨端 per-browser 本地化的架构 backlog 保留。
- **[DONE] 第二十三轮:provider 传输层/HTTP 错误硬编码中文全部收敛入 Msg(14 新变体 + 1 en 臂 {brand} parity 修),多 agent capabilities 审计落地(2026-09-02)**:
  - **来源**:多 agent 能力层审计指出 provider 错误文案构建 `ProviderError.message`,作为回合中红色 Error 行且被逐字折进常驻回合分隔条,英文/中文用户都看到硬编码中文——逐处复核属实后落地。
  - **新增 14 Msg 变体(en/zh 编译期 parity)**:`ProviderErrEntitlement403`(403 未开通套餐)、`ProviderErrUnauthorized{code:u16}`(401)、`ProviderErrInsufficientBalance{code:u16}`(402)、`ProviderErrConnResetRetried{attempts:u32}`(网络中断重连耗尽)、`ProviderErrConnResetPartial`(响应中断保留部分)、`ProviderErrDetailLabel`(详情/Details)、`ProviderErrCorpProxyHint`(公司网络/代理提示)、`ProviderErrProxyNamed{proxy}`/`ProviderErrProxyConfigured`/`ProviderErrProxyUnreachable{who}`(代理不可达)、`ProviderErrTtfbTimeout{secs:u64}`(首字节超时)、`ProviderErrEffortUnsupported`(reasoning_effort 被拒)、`ToolProgressParallelEdit{count:usize}`(并行编辑 fan-out)。`attempts` 用 u32 对齐 `StreamReadRecovery` 源类型,避免有损转换。
  - **转换点**:`provider/mod.rs friendly_http_error`(403 codingplan/401/402;`_ => HTTP {code}: {detail}` 与 `HTTP 429: ` 前缀**原样保留**——后者是 kernel `rate_limit_server_message` 的剥离契约);`provider/retry.rs` `stream_read_error_message` 两段 lead、`connection_reset_hint`(返回类型 `&'static str` → `Cow<'static,str>`,空命中回 `Cow::Borrowed("")`;仍按数字 `os error 10054` 匹配,locale 无关)、`proxy_unreachable_hint`(who/整句;门控串 `failed to create underlying connection` 英文不动)、`open_failed_message` 的详情标签;`anthropic.rs`/`openai_compat.rs` 两处 TTFB 超时(包在 `open failed: ` 英文前缀后);`openai_compat.rs effort_unsupported_error`(zh 引导句入目录,英文括注删除——目录 en 臂已承载同义英文);`tools/parallel_edit.rs` fan-out 头。
  - **特性门**:`tools` feature 不拉 `rustcode-config`,`parallel_edit.rs` 用 `#[cfg(feature="provider")] t(...)` + `#[cfg(not(feature="provider"))]` 英文 `format!` 回退,tools-only 构建可编译;默认工作区构建(provider 开)走本地化臂。
  - **en 臂 parity 修**:`AdminWarningBanner` en 臂缺 zh 臂有的 `{brand}`(运行时 i18n/mod.rs:82 替换),补为 "Consider running {brand} without elevation…"。
  - **测试钉住**:4 个断言中文的测试加 `let _g = test_lock(); set_locale(Locale::ZhCn)`——retry `chain_has_transient_io_detects_connection_timeout`、`stream_read_error_message_explains_a_connection_reset_in_plain_language`、`non_10054_transport_drop_omits_the_corporate_network_hint`、openai_compat `friendly_http_error_wraps_billing_and_auth_codes`(逐字断言 402/403 中文)。仅断言 `/proxy`/`no_proxy`/代理 URL/`open failed:`/`stream read error:` 等 locale 无关串的测试不钉。
  - **保留英文(raw/契约,勿再上报)**:`open failed: `、`stream read error:`、`HTTP {code}: {detail}`、`HTTP 429: ` 前缀;`os error 10054`/`failed to create underlying connection` 数字/英文匹配键;错误链 `err_chain`/`{error}`/`{detail}` 原样透传。
  - **验证**:`cargo fmt --check` 干净;`cargo check -p config/capabilities/daemon` 通过(仅既有 dead_code/legacy clippy 基线,新 t() 块零新 lint);config 337/0、capabilities lib 823/0、daemon lib 307/0;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK(CLI 已重链)。
- **[DONE] 第二十四轮:tuix 轮次上限面板 + git diff 诊断硬编码中文全部收敛入 Msg(26 新变体)(2026-09-02)**:
  - **来源**:多 agent tuix 层审计定位两块 TUI 专属硬编码 CJK——`render/mod.rs round_cap_view` 的轮次预算 checkpoint 面板(头/问题/两选项+描述)与 `git_diff.rs` 全部 git 子进程诊断(约 19 条)。均为用户可见:前者是回合中 UserInputPanel,后者是 diff 模态 Warning body(再由远端 `t(Msg::DiffFailed{error})` 包裹)。
  - **新增 26 Msg 变体(en/zh 编译期 parity)**:`RoundCap*` 7 个——`RoundCapHeader`、`RoundCapQuestion{cap:u32}`、`RoundCapQuestionStats{cap,stats:&'a str}`、`RoundCapContinue`、`RoundCapContinueDesc{base:u32}`(注:授予的是 re-arm 的 `base` 轮而非已增长的 `cap`,保留原注释不变量)、`RoundCapStop`、`RoundCapStopDesc`;`Git*` 19 个——`GitRepoRootEmpty`、`GitCmdFailed{cmd,detail}`(detail 为**原样保留**的 git stderr)、`GitOutputTooLarge{cmd,kib:usize}`、`GitSpawnFailed{error}`、`GitStdoutUnavailable`/`GitStderrUnavailable`、`GitWaitFailed{error}`、`GitTimeout{secs:u64}`、`GitStatusPollFailed{error}`、`GitStdoutThreadPanicked`/`GitStderrThreadPanicked`、`GitStdoutReadFailed{error}`/`GitStderrReadFailed{error}`、`GitNumstatMissingPath/MissingOldPath/MissingNewPath/MissingCount/CountNotUtf8`、`GitNumstatCountInvalid{text}`。
  - **转换点**:`render/mod.rs round_cap_view` 全部面板文案 → `crate::i18n::t(Msg::RoundCap*)`;`git_diff.rs` 每个 `return Err(...)`/`ok_or_else`/`map_err` 的中文字面量 → `t(Msg::Git*).into_owned()`(错误 interpolant 用 `&error.to_string()`,raw stderr/numstat text 逐字透传)。
  - **ASCII 终端门**:面板构建器用全局 `t()`(与 `output_truncation_view`/`round_cap_view` 既有先例一致);render 顶层已按 `caps.unicode_symbols` 决定 `lang`(非 unicode → `Locale::En`)并做字形降级,面板文案被消费进 panel 后由该路径统一处理。
  - **测试钉住**:`render/retained.rs round_cap_view_renders_header_and_two_options` 加 `crate::i18n::test_lock()` + `set_locale(Locale::ZhCn)`(断言中文面板)。
  - **保留**:git stderr/stdout、numstat 原始 text、`KiB`/命令名等 raw/机器值逐字 interpolant,不本地化。
- **[DONE] 第二十五轮:kernel provider-retry 原因中性化(L0 零依赖不变量)+ coding 统一 retry_reason_label + 6 driver 站点 + goal-cap 收敛(9 新变体)(2026-09-02)**:
  - **根因**:`rustcode-kernel` 是 L0(零内部依赖),不能调 `t()`;`agent.rs retry_reason()` 直接返回硬编码中文短语(`"请求过于频繁或额度已用尽"` 等)。各 driver 虽已用 Msg 包裹 retry 通知,但 reason 段嵌入了 kernel 的中文;更糟的是 CLI headless **jsonl 机器通道**把该中文写进 `reason` 字段泄漏给非交互消费者。
  - **kernel 侧(结构化,零文案)**:`event.rs` 新增中性 serde 枚举 `RetryReason{RateLimited,UpstreamUnavailable,Timeout,Network}`(derive Clone/Copy/Debug/PartialEq/Eq/Serialize/Deserialize)+ `as_token() -> &'static str`(稳定机器 token:`rate_limited`/`upstream_unavailable`/`timeout`/`network`);`AgentEvent::ProviderRetry.reason` 字段类型 `String` → `RetryReason`;`agent.rs retry_reason(e)` 改返回枚举(429→RateLimited、5xx→UpstreamUnavailable、message 含 timeout→Timeout、余→Network),emit 点去掉 `.to_string()`。kernel 仍无任何产品/i18n 字符串。
  - **coding 侧(L2,同时依赖 kernel + config,是 kernel-event→本地化标签的共享归属)**:新增 `pub fn retry_reason_label(RetryReason) -> Cow<'static,str>`,match 到 4 个新 Msg `RetryReasonRateLimited/Upstream/Timeout/Network`;从 `coding/lib.rs` 导出,供**全部 driver** 复用(禁止各 driver 自建映射)。
  - **6 driver 站点本地化**:tuix `event_loop` `Kernel::ProviderRetry` 臂(原硬编码 `"API error {reason}，{backoff_secs} 秒后重试…"`)→ `t(Msg::TuixProviderRetry{reason:&label,…})`;CLI headless prose `CliHeadlessProviderRetry{reason:&label}` + **jsonl `reason: Some(reason.as_token().to_string())`**(机器通道改发 token,不再泄漏中文);daemon `live_api.rs`+`lib.rs` 两处 `LiveApiProviderRetry{reason:&label}`;clix `code.rs`+`main.rs` 两处 `ClixRetry{reason:&label}`(各为同构块)。
  - **goal-cap 收敛**:`coding/controllers.rs goal_cap_stop_note` 4 条硬编码中文 → `GoalCapRound{max:u32}`/`GoalCapRoundNoMax`/`GoalCapTime`/`GoalCapStopped{other}`;测试 `cap_stop_note_handles_time_cap_and_unbounded_rounds` 钉 ZhCn。
  - **clap 帮助**:3 条 webui 相关 clap doc-comment 由中文改英文(`--help` 面向用户且同组兄弟项全英文)。
  - **新增 9 Msg 变体**:4 `GoalCap*` + 4 `RetryReason*` + `TuixProviderRetry{reason,backoff_secs:u64,attempt:u32,max_attempts:u32}`。driver 既有的 `CliHeadlessProviderRetry`/`LiveApiProviderRetry`/`ClixRetry` 包装变体复用,仅 reason interpolant 由 kernel 中文改为本地化 label。
  - **验证**:`cargo fmt --check` 干净;`cargo check` 全 lib crate + `-p rustcode`(CLI bin)通过(仅 3 条既有基线 warning:system_proxy parse_scutil_proxy dead_code、session/manager migrate_sessions_from dead_code、usage_render);全量 per-crate 测试全绿——kernel lib 128/0 + 全部集成目标(fallible_stream 13、rate_limit 7、failure_perception 16、liveness 9、spike_claims 17 等)、config lib 327/0、coding lib 429/0(8 ignored 联网门控)、capabilities lib 823/0、tuix lib 2063/0、daemon lib 307/0、clix bins 44/0、cli(rustcode)lib 116 + 集成多目标全 0 失败;`cargo build` 重链成功;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK。
- **[DONE] 第二十六轮:kernel 空响应/截断/越窗等用户可见文案中性化(AgentNotice 结构化枚举)+ coding 单点 localize_kernel_event 边缘本地化(8 新变体)(2026-09-02)**:
  - **根因**:第二十五轮解决了 `RetryReason`(provider 传输重试),但 `agent.rs` 仍有 4 类**面向用户的 prose 直接硬编码中文**写死在 L0 kernel 里:空响应重试提示、响应格式异常重试、回复截断、空响应耗尽的终态错误(按 malformed/越窗 brief/越窗 full/瞬时上游故障分 4 种文案)+ 越窗 advisory。kernel 零内部依赖不能调 `t()`,而这些字符串既经 `Warning/Error` 事件泄漏给全部 driver,又经 `run_to_completion` 写进 `Outcome.error`、经 `hooks.on_error` 发给模型/钩子。
  - **kernel 侧(结构化,零文案)**:`event.rs` 新增中性 serde 枚举 `AgentNotice`(8 变体:`EmptyCompletionRetrying{wait_secs,attempt,max_attempts}`、`MalformedCompletionRetrying{..}`、`ReplyTruncated`、`OverWindowAdvisory{est_k,window_k}`、`EmptyExhaustedMalformed{max_retries}`、`EmptyExhaustedOverWindowBrief{..}`、`EmptyExhaustedOverWindowFull{max_retries,est_k,window_k}`、`EmptyExhaustedTransient{max_retries}`)+ 三方法:`is_error() -> bool`(4 个 `EmptyExhausted*` 为 true,决定路由 Error vs Warning)、`machine_token() -> &'static str`(稳定码)、`english_diagnostic() -> String`(中性英文,供钩子/子代理工具结果/Outcome)。新增 `AgentEvent::AgentNotice(AgentNotice)`。`agent.rs`:`empty_exhaustion_message() -> String` 改 `empty_exhaustion_notice() -> AgentNotice`;`over_window_advisory() -> Option<String>` 改 `Option<AgentNotice>`;4 个 emit 点(越窗 advisory、空/畸形重试、耗尽终态经 `hooks.on_error(&notice.english_diagnostic())`+emit、截断仅在回合因未恢复截断终止时 emit ReplyTruncated)全部改发枚举;耗尽终态**不再另发 `AgentEvent::Error`**,改发 `is_error()==true` 的 AgentNotice。`run_to_completion` 新增臂:error-class notice 写入 `outcome.error=Some(english_diagnostic())` 与 `outcome.error_code=Some(machine_token())`。kernel 仍无产品/i18n 字符串;余额不足/资源包/请充值等上游错误子串匹配器保留(上游错误探测,非自有文案)。
  - **coding 侧(单点边缘本地化)**:`controllers.rs` 新增 `pub fn localize_agent_notice(&AgentNotice) -> Cow<'static,str>`(match 8 变体到 8 个新 Msg `KernelNotice*`,`max_attempts`→Msg 字段 `max`)与 `pub fn localize_kernel_event(AgentEvent) -> AgentEvent`——唯一 chokepoint:`AgentNotice` 按 `is_error()` 转成已本地化的 `AgentEvent::Error{ code: Some(machine_token), .. }` 或 `AgentEvent::Warning(本地化文案)`,其余事件原样透传;从 `lib.rs` 导出。`runtime.rs` 两处边缘 chokepoint:(1) owner 循环 `handle_compaction_event(...)` 结果链上 `.map(localize_kernel_event)`(native_protocol=true 发货路径,inner match 的 catch-all 把本地化后的事件包成 `CodingRuntimeEvent::Agent`);(2) 合并任务 `kernel_events.recv()`(native_protocol=false,仅测试用 owner)包 `CodingRuntimeEvent::Agent(event)` 前同样过一次 `localize_kernel_event`——幂等(Warning/Error 原样透传,仅 AgentNotice 被转换),保证两条通道产出的 `CodingRuntimeEvent::Agent` 都已本地化。覆盖全部走 CodingRuntimeEvent 的 driver(tuix / CLI headless / daemon / clix code.rs)。
  - **直连 kernel 的消费者(不经 coding owner)**:capabilities `tools/task.rs` 子代理事件循环新增 `AgentNotice` 臂——`is_error()` 才写 `outcome.error/error_code`(english_diagnostic + machine_token,工具结果面向模型),advisory 类像 Warning 一样忽略;clix `main.rs` `ReviewRun::apply`(直接 spawn kernel)新增臂:经 `rustcode_coding::localize_agent_notice` 本地化后,error 走 `eprintln!("    [error] …")` 并置 `self.error`,warning 走 `[warn]`。review crate 经 `run_to_completion` 自动获得 Outcome.error/error_code。
  - **新增 8 Msg 变体**:`KernelNoticeEmptyRetryMalformed`/`KernelNoticeEmptyRetryEmpty`(各 `{wait_secs:u64,attempt:u32,max:u32}`)、`KernelNoticeReplyTruncated`、`KernelNoticeOverWindow{est_k,window_k:u32}`、`KernelNoticeEmptyExhMalformed{max_retries:u32}`、`KernelNoticeEmptyExhOverWindowBrief{max_retries:u32}`、`KernelNoticeEmptyExhOverWindowFull{max_retries,est_k,window_k:u32}`、`KernelNoticeEmptyExhTransient{max_retries:u32}`;en/zh 臂齐备(编译期 parity),zh 臂复现原中文措辞。
  - **测试**:kernel 单测 `empty_exhaustion_notice_tests`(5)/`over_window_advisory_tests`(6)改断言中性枚举(`matches!`+`is_error()`+`machine_token()`+`english_diagnostic()` 子串);集成 `tests/fallible_stream.rs` 4 测试(`repeated_truncation_is_bounded`、`empty_response_is_retried_then_succeeds`、`empty_response_exhaustion_fails_visibly`、`malformed_response_retried_with_distinct_notice`)由匹配中文 Warning/Error 改为匹配 `AgentNotice::ReplyTruncated`/`EmptyCompletionRetrying`/`MalformedCompletionRetrying` 及 error-class `machine_token().starts_with("empty_exhausted")`(kernel 测试只断言中性枚举,不引入 i18n)。
  - **不变量保留**:失败感知不变(error-class→Error/Outcome.error,turn 仍 StopReason::ProviderError)、稳定机器码、解析契约、kernel 全英文 diagnostic 惯例、L0 零依赖;机器通道(code/token)与模型面(hooks/工具结果)保持中性英文/码,人类面(driver 警告/错误横幅)走本地化。
  - **验证**:`cargo fmt --check` 干净;`cargo build`(默认成员)成功;全量 per-crate 测试全绿——kernel lib 128/0 + fallible_stream 等全部集成目标 0 失败、config 327/0、coding 429/0(8 ignored)、capabilities 823/0、tuix 2063/0、daemon 307/0、clix bins 44/0、cli(rustcode)集成目标全 0 失败;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK。
- **[DONE] 第二十七轮:默认可达 tuix 文案 i18n(/loop 解析错误 + 内联 429 限流行)+ 三方审计校准收尾(9 新变体)(2026-09-02)**:
  - **目标与校准**:第二十五/二十六轮把 provider 重试原因与 kernel AgentNotice 收敛为"中性枚举 + 边缘本地化";本轮在 3 路多 agent 审计(平台中立 / 遥测 / 供应商耦合)结论上校准——审计报的 LLM-adapter "egress 绕行" 是**文档化结构性豁免**(openai_compat/anthropic/ollama builder 不强行改),PGY/relay "Sev-1" 在后端实为本地探测(BYO)+ relay 默认门控关闭(`HOSTED_RELAY_ENABLED=false`/`RUSTCODE_ENABLE_RELAY`),唯一真实供应商背书是 webui 一个 `pgy.oray.com` 下载链接(需 npm 重建,入 backlog)。故本轮选取**默认发货路径可达**的 tuix 硬编码字符串做可验证增量,而非门控后表面(onboarding QR / relay 错误)。
  - **新增 9 Msg 变体**(en/zh 臂齐备,编译期 parity):`TuixLoopUsage`、`TuixLoopSelfRef`、`TuixLoopIntervalRange`;`TuixRateLimitAutoResume{secs:u64}`、`TuixRateLimit429{reason,tail:&str}`、`TuixRateLimitRetryAfter{dur:&str}`、`TuixRateLimitWindowNoTime{tail}`、`TuixRateLimitWindowWithTime{reset_at,tail}`、`TuixRateLimitWindowRemaining{dur}`。zh 臂复现原中文措辞,en 臂给中性英文;限流行语义保持不变——`auto_resuming` → WaitAndRetry 倒计时(⏳);否则 `is_coding_plan = !reset_at_display.is_empty() || !reset_label.is_empty()` → 托管 5 小时窗口文案(⏸),否则通用外部/BYO 429;`server_message`(原始 provider body,如余额文案)仅在通用分支透传拼接(`": {}"` 拉丁冒号,locale 中立),`⏳`/`⏸` 属白名单单色字形保留。
  - **接线**:`event_loop/loop_parse.rs` 4 个 `LoopArg::Error(...)` 站点由硬编码中文字面量改 `crate::i18n::t(Msg::TuixLoop*) .into_owned()`(parser 返回 `LoopArg::Error(String)`,测试只匹配 `Error(_)` 形状,不受 locale 影响);`event_loop/commands.rs` `format_rate_limited_line` 三个分支(auto / 通用 429 / coding-plan 窗口)全部改走 `t(Msg::TuixRateLimit*)`,`fmt_dur` 时长与原始 server 消息作为 `&str` 字段注入(机器/原始面保持 raw)。
  - **locale 竞态修复(测试隔离不变量)**:凡断言/对比 `t()` 渲染结果的测试必须持锁——`dir_picker.rs` 测试会把全局 locale 设成 `En`,与并行的中文断言测试竞态(曾导致 `todo_command_tests::required_empty_arg_dispatch_pipeline_rejects_without_submit` 在 commands.rs:9216 panic)。给 9 个 `rate_limited_tests`(7 个单行 + 2 个两行调用形式)与该 todo 测试顶部统一加 `let _locale = crate::i18n::test_lock(); crate::i18n::set_locale(crate::i18n::Locale::ZhCn);`(guard 在 Drop 时恢复获取时刻 locale)。
  - **coding 边缘本地化测试**:`controllers.rs` `mod tests` 新增 `kernel_notices_localize_and_route_by_error_class`——ZhCn 下 `ReplyTruncated`→`Warning(w)`(含"长度上限""继续")、`EmptyExhaustedTransient{max_retries:5}`→`Error{message,code:Some("empty_exhausted_transient"),..}`(message 含"空响应"与 '5');En 下 ReplyTruncated→Warning 含 "length limit"/"continue";幂等:已本地化的 `Warning("已本地化")` 与 `TurnStarted` 原样透传。
  - **零星中立化收尾**:`capabilities/src/bin/mcp-test-server.rs` 启动横幅 `"✅ MCP server initialized..."`(彩色 emoji)→ `"[OK] MCP server initialized and ready (stdio)."`;`review/src/persona.rs` doc 注释 `The Go engineering layer (gitcode-assist-service) appends…` → 中性 `An external host layer may append … via --append-system-prompt-file`;`tuix/src/render/retained.rs` 测试夹具路径 `~/workspace/gitcode_project/...` → `~/workspace/example-project/...`(断言只取 "workspace");顺手清掉 `tuix/src/modals/usage_render.rs:107` 一处 `unused_parens` 警告。
  - **平台中立 backlog(记录,不在本轮实现)**:(a) webui `RemoteAccessDialog`(`webui/src/components/SettingsDialogs.tsx` ~983/1032)硬编码 `href="https://pgy.oray.com"` 下载链接——应门控在 relay-enabled 后或中性化,需 `cd webui && npm ci && npm run build` 再 `cargo clean -p rustcode-daemon`(cargo 不追踪 `webui/dist/`);(b) GitHub Copilot MCP 便捷子命令 `mcp add-github-oauth`(cli `main.rs` ~3592、`mcp/oauth.rs:19-21` 硬编码 `api.githubcopilot.com`)——考虑泛化为 `add-oauth`;(c) 门控后 CJK 字符串(onboarding_wizard.rs QR ~12 条、commands.rs relay client 错误 ~20 条、usage_monitor.rs:150/153、monitor.rs:44/45、codingplan types.rs:325/client.rs:377)——原判"全部在 codingplan/relay gate 之后,默认不可达";**2026-09-09 补注:除 relay 一项外,该清单所列文件均已随裁决 Q1=B 删除,codingplan 侧的这条 backlog 自然消解**;(d) `state.rs` thinking/done 标签用并行 const 数组而非 Msg;(e) `SubAgentConfig` 残余字段(config/mod.rs:151-172)、rustcode-auth `oauth.rs` ~6 个 dead_code fn、deprecated `diagnostics` 工具别名。
  - **不变量保留**:解析契约/NLP intent 匹配器、机器 `code`/token、原始 server message、HTTP 方法/路径、`.context()` 低层诊断、模型面文本一律保持 raw/英文;`atomgit` feature 与 `capabilities/src/atomgit/`、`[telemetry]` 兼容段仍**刻意保留**(gate,不删除);**同句原并列的 codingplan gate 与 Cp 前缀签名 i18n 族已于 2026-09-09 被裁决 Q1=B / Q3 推翻并移除**(i18n 侧的 Cp 前缀族删除亦已落地);**managed-QR 仍保留**(托管登录面,受托管登录谓词门控,只清除了其中的 codingplan 品牌文案);rustcode 身份不改名;L0 kernel 仍零文案。
  - **验证**:`cargo fmt --check` 干净;`cargo build`(默认成员)成功(初次因磁盘 100% 链接失败,清理 `target/debug/{incremental,examples,build}` 与 deps 内陈旧链接产物(保留全部 `.rlib/.rmeta/.d/.o`)释放至 22G 空闲后重链成功);config 327/0、tuix 2063/0(含与 En 设置 dir_picker 测试并行下竞态已修)、`cargo check -p rustcode-review -p rustcode-capabilities --all-targets` Finished;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK。
- **[DONE] 第二十八轮:多 agent 审计校准 + 厂商耦合 CLI 解耦(neutral `mcp add-oauth`)+ 并行工具批头 i18n「Running N tools」(8 新变体)(2026-09-02)**:
  - **三路只读审计结论与校准**:(1) **遥测** —— 0 真实违规;manifest/Cargo.lock/webui package.json 无任何 sentry/posthog/segment/mixpanel/analytics SDK;其余命中全是子串噪声(`segment` 路径段)、"已移除遥测"注释、卸载清理旧 telemetry 目录、向后兼容 `[telemetry]` 静默忽略段。G6 保持。(2) **陈旧命名** —— 3 项:① `LEGACY_CODINGPLAN_PREFIX="AtomGit"` 识别器 + `is_codingplan_provider_name` 当时判为**刻意保留**的迁移识别(只匹配旧配置键、不出站、不写出),**不删**——**该结论已于 2026-09-09 被用户裁决 Q2' 推翻:两个符号连同前缀匹配规则、账号折叠与只读保护一并删除;磁盘上已有的 AtomGit 系列配置键仍能正常加载,只是降为普通自定义 provider(不再折叠、不再只读、不再被登录流接管),config.toml 不被改写**;② `endpoints.rs` 中立性测试夹具里的真实上游主机 `https://api-ai.gitcode.com/v1` → 改为保留域名 `https://api-ai.upstream.example/v1`(保留"网关形状 URL 默认仍判外部"的回归语义)。(3) **厂商耦合 / i18n** —— 校准见下。
  - **厂商耦合处置(calibration)**:18 个品牌 provider preset(DeepSeek/OpenAI/Zhipu 等)是**第三方 BYO 配置目录**(各自需用户自带 key、无任何一方指向 rustcode 托管网关,且 generic OpenAI/Anthropic-compatible 居首),正是 `/goal`"只保留第三方配置"所指 → **保留**。真正的默认可达厂商背书是 GitHub MCP OAuth 的 CLI 引导,本轮在 **CLI 引导层**解耦,**不删**能力层机制:`login_github_oauth()` 是 GitHub classic-OAuth(无 PKCE/DCR、需用户自注册 OAuth App + secret)的互通机制,仅在用户显式配置 `auth.provider=="github"` 时触发——属 BYO 互操作(与 provider adapter 同性质),且无法离线验证,故保留。
  - **CLI 解耦(默认面去广告、功能全保留)**:新增中性子命令 `mcp add-oauth <url> [--name] [--global] [-C]`——按 URL 添加任意第三方 OAuth MCP 服务器,登录走通用 RFC-8414 元数据发现;`--name` 缺省时取 URL host。`mcp add-github-oauth` 改为 `.hide(true)`(从 `--help` 与 shell 补全中隐藏,但**仍可显式调用**,向后兼容)。`mcp login --provider` 去掉 `default_value="github"`(改 `Option<String>`):github classic 流改由**服务器自身配置**(`auth.provider=="github"`)或显式 `--provider github` 触发(`github_mode = is_github_server || provider.as_deref()==Some("github")`),bare `mcp login <server>` 对通用服务器不再默认走某厂商。
  - **能力层中性化**:`mcp/config.rs` `merge_http_oauth_mcp_server_into_json_file` 空 `provider` 不再 bail,改为**省略 `provider` 字段**(写出 `auth:{type:"oauth"}`),登录即进通用发现路径;非空 provider 原样写出(github 互通路径)。新增测试 `merge_http_oauth_neutral_omits_provider`(`example.test` 夹具,断言无 provider 字段);旧 `merge_http_oauth_creates_mcp_servers`(github 路径)保持绿。
  - **并行工具批头 i18n(高频中文缺口)**:TUI 每次并行/成组工具调用渲染的 `● Running N tools/calls` 行此前**硬编码英文**(中文默认用户看到英文)。抽公共 `pub(crate) fn tool_batch_label(count, tool: Option<&str>, concurrent) -> String`(live 渲染路径与 session replay `build_replay_tool_batch` 共用,消除两处漂移);4 个新 Msg `TuixToolBatchSameParallel{count,tool}`/`TuixToolBatchSame{..}`/`TuixToolBatchParallel{count}`/`TuixToolBatch{count}`,en/zh 臂齐备(zh:「并行运行 N 个 {tool} 调用」「运行 N 个工具」等);工具名(如 `bash`/`read_file`)作为原始 `&str` 注入,不译。replay 恒为 serial(无"in parallel")。
  - **测试 locale 钉定(隔离不变量)**:3 个批分支逻辑测试(`tool_batch_label_*`,此前内联复制一份英文 format 匹配)改为调用共享 `tool_batch_label` 并 `test_lock()+set_locale(En)`(它们以 "in parallel"/"Running N tools" 措辞断言 并发 vs 串行 分支);`session_picker::replay_rebuilds_parallel_batch_group` 同样钉 En(retained.rs 的 `header:"● Running…"` 是喂给渲染器的**夹具输入**做布局测试,非 t() 输出,不受影响)。
  - **新增 4 Msg**(另加 CLI 侧 `CliAboutMcpAddOauth`/`CliHelpMcpUrl`/`CliHelpMcpProvider`/`CliHelpMcpClientId`/`CliMcpAddedOauth{name,path,url}` 共 5,皆 en/zh 臂齐备)。
  - **backlog(记录,不在本轮)**:① **单工具 inflight 旋转行** `retained.rs:2084 format!("Running{meta}")`(bash liveness「Running · 12s」)仍是英文硬编码——嵌在动画 spinner 帧重写/commit 原子擦除/`spinner_meta_suffix` 解析契约里,且 ~6 个 retained 测试驱动真实 bash 行,需专项 + 可视化验证,本轮不冒险;② `/goal` 统计分隔行("N tools · tokens"、"↻ goal round N")与 user-paused 横幅 `mod.rs:27492` 英文(小众 `/goal` 用户);③ provider reload 错误文案(`mod.rs:17976/18126`)英文;④ `state.rs` 40 个 thinking/done 标签与 `effort_word()` **已按 current_locale() 选中英文池**(中文默认用户已见中文),转 Msg 目录纯属重构且牵动 `is_thinking_label` 停滞检测匹配器,低收益高风险,仅记;⑤ webui `pgy.oray.com` 下载链接(需 npm 重建);⑥ SubAgentConfig 残余字段、rustcode-auth dead_code fn、deprecated `diagnostics` 别名(沿用第二十七轮)。
  - **不变量保留**:`atomgit` feature/模块、`[telemetry]` 兼容段、`login_github_oauth` 互通机制仍**保留**(gate 不删);**同句原并列的 codingplan cfg 与 Cp 前缀族已于 2026-09-09 被裁决 Q1=B / Q3 / Q5 推翻并移除**(i18n 侧的 Cp 前缀族删除亦已落地);**managed-QR 仍保留**(托管登录面,门控不删,仅清除 codingplan 品牌文案);rustcode 不改名;品牌 preset 保留(BYO);机器码/工具名/HTTP/原始错误不译;L0 kernel 仍零文案。
  - **验证**:`cargo fmt --check` 干净;`cargo build`(默认成员)成功;config 327/0、capabilities `--features mcp` 下 merge 测试 2/0、tuix **2063/0**(3 个批测试 + replay 测试在并行 En-setting 下持锁稳定)、cli(rustcode)116+88+ 全 0 失败;新增 clippy 警告为 0(命中项均为既有基线,唯一文件级命中在更早轮次的 rustcode-auth/oauth.rs);端到端手验:`mcp add-oauth https://mcp.example.test/sse` 写出 `auth:{type:oauth}` 无 provider 且键取 host,隐藏的 `add-github-oauth` 仍写 provider:github;`mcp --help` 列出 add-oauth 而无 add-github-oauth;G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK。
- **[DONE] 第二十九轮:三路审计校准 + 中性构建隐藏端点死路(/desktop /upgrade)+ login/usage 描述去厂商 + team/scroll 文案 i18n + 死代码清理(14 新变体)(2026-09-02)**:
  - **三路只读审计结论**:(1) 遥测 SDK **仍为 0**(sentry/posthog/segment/mixpanel/amplitude/analytics 全无;`unicode-segmentation` 是子串噪声)。(2) G7/G8 **通过**(crates/scripts/.github 与 docs/architecture.md 零 atomcode);无双向转换器/旧 core 写入器/facade(`legacy_convert.rs` 严格单向导入)。(3) 品牌 preset(DeepSeek/OpenAI/Zhipu/SiliconFlow/OpenRouter…)为合法第三方 BYO 目录且 generic OpenAI/Anthropic-compatible 居首 → **保留**;`docs.rustcode.dev`、`noreply@rustcode.dev` 是本项目**自身**身份(非第三方背书)→ 保留;HarmonyBrew(distro-pm feature)、`rustcode-link://`(relay gate)均特性/运行时门控,默认不可达 → 保留。
  - **端点死路门控(本轮核心去厂商)**:`/desktop` 与 `/upgrade` 此前**总是**出现在 `/` 菜单/Tab 补全/`/help`(neutral 构建里:desktop 下载 URL 为空 → 打印悬空"下载安装:"空行;upgrade 无 manifest → `GET ""` 报 "relative URL without a base")。`command_visible()` 增按端点隐藏:`desktop` 当 `endpoints::desktop_download_url().is_empty()`、`upgrade` 当 `!rustcode_updater::update_endpoint_configured()`(对齐 version_check 的中性早退)。两命令**仍可显式键入**(dispatchable),arm 内部分别优雅早退:`DesktopNotInstalledNoUrl`(替代空 URL 行)、`UpgradeNoEndpoint`(替代空 URL GET)。
  - **login/usage 描述去厂商(CLI 对齐)**:TUI 此前只有 managed 版 `CmdDescLogin`/`CmdDescUsage`(文案含 "claim CodingPlan models"/"CodingPlan usage"),CLI 早有 `CliAboutLogin(Neutral)` 双版而 TUI 缺。新增 `CmdDescLoginNeutral`/`CmdDescUsageNeutral`,`cmd_desc_i18n()` 按 `managed_login_available()` 选版(neutral:指向 config.toml BYO / 改述为"令牌用量")。command_visible 本就在 neutral 构建隐藏二者,此为**纵深防御 + 与 CLI 一致**(gate 不删 managed 文案)。**[2026-09-09 补注]** "gate 不删 managed 文案"现只指两个 managed 变体本身仍在;文案里的 CodingPlan 品牌字样已随 i18n 收尾任务清除(config i18n 实测 codingplan 0 命中)。
  - **team/multiagent 内联通知 i18n**(契合多 agent 协作主题):`team_success_notice`/`team_batch_result_suffix`(event_loop/mod.rs ~22000)原本硬编码英文 "Team dispatched/stopped/results"、"dispatched/stopped/updated"、回退词 "agent/unknown/no report"。新增 9 变体(TeamNotice{Dispatched,Stopped,ResultsHeader}、TeamMemberFallbackId、TeamStatusUnknown、TeamResultNone、TeamSuffix{Dispatched,Stopped,Updated}),`·`/`○`/`└` 字形与 run_id/工具动作名(delegate/stop/result…)保持原样;`team_action`/`projected_team_action` 返回的是原始动作名,不译。
  - **审批面板滚动指示 i18n**:`retained.rs` fit_user_input 溢出指示 `"<arrow> N hidden lines · PgUp/PgDn"` 原本硬编码;新增 `ScrollHiddenLines{count}`(zh「N 行被隐藏 · PgUp/PgDn」),方向箭头与 `PgUp/PgDn` 键名保持原样。
  - **不译(校准剔除)**:`Tab:` ghost 前缀(retained.rs:73)是**键名**,中文软件 universally 渲染为 "Tab",译出反而怪异 → 保持;`shell` 模式徽标(retained.rs:3235)在中文开发者语境是 autoglottonym/技术术语(如同 bash),单字徽标强译"外壳/命令行"更差 → 保持;state.rs `Running/Preparing {tool}` spinner + retained.rs 单工具 inflight 行仍留给专项轮次(动画帧重写 + `display_spinner_label` 前缀匹配耦合,见 backlog)。
  - **死代码清理(Agent C 验证零调用点)**:删 `capabilities/src/plugin/paths.rs::project_marketplaces_root`(marketplace 已迁至 env 配置,零引用)、删 `tuix/src/render/retained.rs::build_wrapped_text_rows`(约 20 行死渲染方法,零引用);修 `rustcode-auth/Cargo.toml` 描述 "an rustcode-core" → "a rustcode-core" 冠词。**保留** `rustcode-auth/oauth.rs` 的 `await_callback`/`read_callback_from_stdin_until_stopped`/`accept_callback_until_stopped`/`parse_pasted_callback` 退休 TCP 回调簇(~200 行,后者尚有 live 测试)——属"OAuth transports/托管登录"刻意保留范畴且为内聚单元,留作专项;独立的 `pasted_state`/`generate_state` 虽零引用亦同属该 OAuth 簇,一并保留不拆。SubAgentConfig 残余字段(serde 反序列化旧配置)、`InstalledTxn.project_root`/`SetupLock.lock_path`/`LiveGroup.header_idx`(皆有 "reserved for future" 注释)、平台 cfg 的 OpenStrategy/DesktopApp/Screen 死码(假阳性)全部保留。
  - **新增 14 Msg 变体**(en/zh 臂齐备):CmdDesc{Login,Usage}Neutral ×2、DesktopNotInstalledNoUrl、UpgradeNoEndpoint、team 9、ScrollHiddenLines。
  - **测试隔离**:断言英文字面的 team 投影测试(`team_tool_success_is_compact_for_interactive_projection`)与溢出指示测试(`long_user_input_wraps_and_short_terminals_follow_cursor`)均加 `test_lock()+set_locale(En)`(并行 En-setting 下持锁稳定);`neutral_build_hides_managed_account_commands` 扩展断言 desktop/upgrade 在 neutral 构建不出现在 help 与 slash 菜单。
  - **观察到的既有 flake(非本轮引入)**:全量 tuix 跑时 `session_picker::replay_keeps_current_model_window_…`(2166,断言无 "987" 陈旧统计泄漏进 TurnSeparator)曾失败一次,但**隔离 + 全量重跑 2 次 + session_picker 连跑 3 次均通过**;该断言取决于 replay 回合位置选择(非 locale),疑为哈希迭代序敏感的**既有 flake**,本轮未触碰 replay/TurnStat/turn_divider_label 逻辑,仅记录不修。已知红 `mcp::registry::trust_key_golden…` 仍不动。
  - **验证**:`cargo fmt --check` 干净(自动 fmt 后);`cargo build` 成功;config **327+7+3/0**、tuix **2063/0**(重跑绿)、cli(rustcode)lib **116/0** + 默认成员全量 `cargo test` 所有二进制均 0 失败、capabilities `--features mcp` **928/1**(1 为已知红 trust_key);新增 clippy 警告为 0(en.rs/zh_cn.rs 文件尾 "items after a test module" 与两条 into_owned 命中均为既有基线,非本轮新增行);G4 headless 2 过 5 跳 0 失败;G5 acp_smoke SMOKE OK。
- **[DONE] 第三十轮:webui 远程访问去厂商(删 pgy.oray.com 下载链接)+ 单工具 inflight spinner i18n「运行中」+ 修复 zh effort 后缀泄漏潜在 bug(1 新变体)(2026-09-02)**:
  - **spinner 子系统结论(先厘清再改)**:`state.spinner_label` 里的 `format!("Running {name}")`/`"Preparing {name}"`(state.rs:2110/2128/2253)是**内部阶段哨兵**,不是展示文案——`display_spinner_label()`(state.rs:1909)在显示前把它们拦截、换回**已按 locale 切换的思考词池**(THINKING_LABELS/_ZH),故 footer spinner **早已全 i18n**(Compacting/WaitingApproval/SubAgents/effort/queue/elapsed 各段都走 `t()`)。审批暂存的 `prior_spinner_label = "Running {}"`(2253)回退后也过同一拦截器。**唯一漏网的英文散文**是 bash 工具条的存活行。
  - **bash inflight 存活词 i18n**:`render_inflight_tool` 在静态命令块下方追加的存活行 `format!("Running{meta}")`(retained.rs:2084)此前硬编码英文,中文环境每条运行中的 bash 命令下都显示 "Running"。新增 `Msg::SpinnerRunningLabel`(en "Running" / zh「运行中」),改为 `format!("{}{}", t(SpinnerRunningLabel), meta)`;`meta`(` · 12s` / ` (3s · ↑ …)`)由 `spinner_meta_suffix` 从 label 剥离,仅 ASCII 分隔符,与词无关;动画帧/CUP+EL 原位重写按**行数**判定,单词宽 7→6 cell 不影响行计数(单行不折行)。state.rs 哨兵**刻意保留为英文**(改中文会破坏 `display_spinner_label` 前缀匹配、`on_tool_call_streaming` 的 `starts_with("Preparing")` 相位锚、且用户本就看不到),不做 phase enum 重构(无用户可见收益、风险大)。
  - **修复 zh effort 后缀泄漏潜在 bug(本轮附带真实修复)**:`spinner_meta_suffix`(retained.rs)此前硬编码 `EFFORT_MARK = " · thinking with "`(英文)来把 effort 段从工具条上剔除;但 zh 的 effort 后缀是 `" · {level}强度思考"`(固定**尾**缀,词在前),中文环境该 mark **永不匹配** → effort 提示在 effort-capable 供应商下会泄漏到 zh 工具条行。改为按 `current_locale()` 选标记:英文用固定前缀 `" · thinking with "`、zh 用固定尾缀 `"强度思考"`,均从该标记内侧扫描下一 ` · `/` (` 边界。新增 zh 专项测试 `spinner_meta_suffix_splices_localized_zh_effort_hint`(覆盖 effort+queue+钟 / effort+括号钟 / 仅 effort / 无 effort 四形)。
  - **webui 远程访问去厂商**:`RemoteAccessDialog` 删除硬编码的 `<a href="https://pgy.oray.com">下载蒲公英</a>` 按钮(第三方厂商下载背书),分支 1 改为纯中性局域网/隧道指引(自身 `docs.rustcode.dev` 使用引导链接保留);i18n.ts 的 zh+en `remote.*`(intro/ready/notReachable/notConnected/notInstalled)全部改为中性"绑定局域网地址 / 任意虚拟局域网·内网穿透工具"措辞,**删除** 已无引用的 `remote.installLink` 键(en/zh 两份);api.ts/tsx/i18n.ts 注释里的"蒲公英/Oray PGY"改为"LAN / virtual-LAN tunnel"。`status.pgy`/`PgyInfo` 等 **JSON 线协议字段名保留**(daemon 契约);daemon 侧 VPN 检测(`pgy_probe`/Oray plist)作为"示例已装 VPN"的本地能力保留(不背书、无链接)。`npm run build` 后 `grep 蒲公英/oray/pgy.oray webui/dist` 为空;已 `cargo clean -p rustcode-daemon` 强制重嵌新 bundle。
  - **新增 1 Msg 变体**(en/zh 臂齐备):SpinnerRunningLabel。
  - **测试隔离**:`retained_inflight_tool_renders_elapsed_meta_suffix`、`retained_bash_inflight_hint_is_part_of_strip…`、`retained_bash_inflight_without_hint…` 三个断言/定位 "Running" 词的渲染测试加 `test_lock()+set_locale(En)`;两个 `spinner_meta_suffix_*` 英文夹具测试加 En pin(标记随 locale 选择),并新增上面的 zh 测试。state.rs 中 `assert_eq!(spinner_label, "Running Bash")` 等内部哨兵断言**不动**(哨兵仍为英文)。
  - **验证**:`cargo fmt --check` 干净;config **327/0**;tuix lib **2064/0**(较上轮 +1 新 zh 测试;spinner 41、inflight 21、state 78 子组全绿);webui bundle 构建成功且无厂商串。
- **[DONE] 第三十一轮:多 agent 审计校准闭环 + TUI 边缘散文 i18n(4 新变体)+ "官方登录流程" 措辞去厂商四面对齐(2026-09-02)**:
  - **校准闭环(Stop-hook 要求)**:本轮把上一轮 429 中断的 vendor 审计与 webui/TUI 两份审计结论**逐条处置并落地**。三路审计裁决:(1) **遥测仍为 0**——无 Sentry/PostHog/Segment/GA SDK 或调用;所有托管端点(platform server / LLM gateway / update manifest / relay / trusted domains / marketplaces)默认空或 false;onboarding BYO-first;唯一外部链接 `docs.rustcode.dev` 与 commit trailer `noreply@rustcode.dev` 均为本项目**自身身份**,保留。(2) webui 报的 "k tokens" 页脚(`Chat.tsx:3267`)与 3 处上下文窗口 "tokens" 后缀(`SettingsDialogs.tsx:360/637/929`)——**裁决不改**:"tokens" 在 TUI(`/cost` 规则"tokens stays untranslated")与 webui 既有 zh 目录(`cmd.context.body`/`cmd.cost.body`)都是**约定不译的单位词**;base-url 占位符 `https://api.example.com/v1`、`sk-...`、`~/...` 是通用格式示例,保持原样。(3) TUI `/save` markdown 的 User/Assistant 标题是**文件格式约定**,保持;effort 的 **SET** 行 `reasoning_effort -> {v}` 是配置键 + 值回显(与 `[high]` 徽标同类),保持英文,仅 **CLEARED** 散文 i18n。
  - **TUI 边缘散文 i18n(4 新 Msg,en/zh 臂齐备)**:① `/skills` 空列表安装指引——两处硬编码英文长文(idle 菜单分支 `i` 标记 + 输入路径 `ⓘ` 标记)抽 `Msg::CmdSkillsEmptyHint`(zh:「尚未安装可供调用的技能…将 SKILL.md 放入 ~/.rustcode/skills/<name>/…」),路径与 `/plugin install <git-url>` 命令保持原始;② Ctrl+T 循环 effort 回到"无覆盖"的确认行 `Msg::EffortCleared`(zh「reasoning_effort 已清除(API 默认值)」),配置键 `reasoning_effort` 保持原始;③ `ReadyRuntimeControl::report_delivery_failure` 构造的 `AgentEvent::Error { message }` 此前硬编码 `"coding runtime {operation} delivery failed"`——改 `Msg::TuixRuntimeDeliveryFailed { operation }`(zh「运行时 {operation} 事件投递失败」)。**注意 L0 边界**:kernel/coding 仍只发中性结构化 `AgentEvent`,文案在 **tuix 边缘**构造(符合"kernel 零文案、边缘本地化"不变量),`operation` 内部事件名保持原始;④ 本地 shell 输出回填运行时上下文失败的括号注记 `Msg::TuixShellContextQueueFailed`(zh「[将 shell 输出加入运行时上下文失败]」)。
  - **"官方登录流程" 措辞去厂商(四面对齐)**:policy-recovery 安全指引此前用"服务**官方**登录流程 / the service's **official** login flow"——"官方"暗含存在一个 canonical/权威厂商。改为中性表述且四处一致:TUI zh「使用服务**自身的**登录流程」、TUI en「the service's **documented** login flow」、webui zh「服务**自身的**登录流程」、webui en「the service's **documented** login flow」。
  - **测试隔离**:`ready_runtime_reports_later_submit_delivery_failure_after_undo_channel_closes`(async,断言 `message.contains("delivery failed")`)在默认 zh 下会拿到中文,加 `test_lock()+set_locale(En)` 钉定。
  - **新增 4 Msg 变体**:CmdSkillsEmptyHint、EffortCleared、TuixRuntimeDeliveryFailed{operation}、TuixShellContextQueueFailed。
  - **不变量保留**:`atomgit` feature/模块、`[telemetry]` 兼容段、`login_github_oauth` 互通机制仍保留(gate 不删);**同句原并列的 codingplan cfg 与 Cp 前缀族已于 2026-09-09 被裁决 Q1=B / Q3 / Q5 推翻并移除**(i18n 侧的 Cp 前缀族删除亦已落地);**managed-QR 仍保留**(托管登录面,门控不删,仅清除 codingplan 品牌文案);rustcode 不改名;机器码/工具名/HTTP/原始错误/配置键/路径/operation 名不译;L0 kernel 仍零文案;`ProviderConfig.model_mapping` 非 Option 不变。
  - **验证**:`cargo fmt --check` 干净;`cargo build`(默认成员,含 daemon 重嵌 bundle)成功;config **327+7+3 / 0**;tuix 编译绿(exhaustive match 编译期保证 en/zh 臂齐备);webui **227/0**、`npm run build` 成功且 `grep "official login" dist` 为 0;已 `cargo clean -p rustcode-daemon` 重嵌新 bundle。
- `ProviderConfig` / `ModelProfileConfig` 新增了**非 Option** 的 `model_mapping: ModelMapping`(空表即恒等映射),是**必填字段**。新增结构体字面量时必须显式给 `ModelMapping::default()`。
- `docs/architecture.md` 正文已改为 `rustcode-*` 命名;残留的 `rustcode` 字样仅在描述已退役 `rustcode-core` 的历史小节中(合法的历史名引用)。
- **[CHECK] 产品身份已锁定为 `rustcode`**(见 `docs/REFACTOR_DESIGN_PHASE1.md` §2.0 决策 D1),并已在 commit `6dbf57bb` 落地。不要再提议或先行改名。

- **[DONE] 第二十九轮:第三方模型厂商身份外发归零 + 遥测词义残留清零(2026-09-02)**:
  - **OpenRouter 归因改为 opt-in(落实 `docs/REFACTOR_DESIGN_PHASE1.md` §4.3 G6)**:`capabilities/src/provider/openai_compat.rs` 的归因头此前**无条件**随每个 `openrouter.ai` 请求外发 `X-OpenRouter-Title: RustCode` / `X-OpenRouter-Categories: cli-agent`(仅 Referer 上一轮已 opt-in)。现整体默认关闭:新增 `RUSTCODE_OPENROUTER_ATTRIBUTION=1|true|on|yes` 门控,解析抽为纯函数 `attribution_enabled_from`(避免测试改动进程级 env);`apply_openrouter_attribution` 拆出 env-free 的 `apply_openrouter_attribution_with(url, req, enabled, referer)` 供确定性单测。**默认出站只携带第三方配置本身(`base_url` / `api_key` / `model` / `extra_headers`),不向任何模型厂商外发本产品身份。** host 门禁 `is_openrouter_url` 与 userinfo 冒用防护(`openrouter.ai:x@evil.com`)原样保留。归因测试由 2 个扩到 6 个,覆盖默认关 / opt-in 开 / 无 Referer / 非 OR 端点 / 伪造 host 五路。
  - **遥测词义残留清零**:kernel(`hook.rs` ×4、`agent.rs` ×2、`event.rs`、`message.rs`、`tests/turn_complete.rs`、`tests/hook_a2_surface.rs`)、capabilities(`mcp/mod.rs`)、clix(`main.rs`)中把"可观测性挂载点"误写为 `telemetry` 的 hook seam 注释统一改为 `observability`。剩余 `telemetry` 字样收敛为 OBJECTIVE-2 列出的三类守卫,已标注禁止误删。
  - **文档旧名收尾**:`docs/multi-agent-collaboration-solution.md` 中 `atomcode-{kernel,capabilities,coding}` 与 `crates/atomcode-coding/src/session.rs` 更正为 `rustcode-*`;`docs/REFACTOR_DESIGN_PHASE1.md` §4.3 G6 行标注 [DONE]。刻意**未改** README 与 `docs/{UPSTREAM_RUSTCODE_LICENSE,UPSTREAM_CREDITS,THIRD_PARTY_NOTICES,platform-neutralization,features}.md` 中的 `atomgit_atomcode/atomcode`——那是 MIT 归属声明,删改有合规风险。**[SUPERSEDED 2026-09-02,见第三十二轮]** 该判断已修正:用户裁决要求清干净 README,`docs/{features,platform-neutralization}.md` 的正文 slug 亦一并清除;**MIT 归属原文仅在 `LICENSE` 与 `docs/{UPSTREAM_*,THIRD_PARTY_NOTICES,ORIGINAL_LICENSE}.md` 保留**,README 改述为「上游项目」并保留归属链接,故合规归属未丢失。
  - **验证(零回归,经 stash 基线逐项比对)**:`cargo check --workspace --all-targets` 0 错;capabilities lib **827/0**(新增 4 项归因测试全绿)、kernel 全部测试目标全绿;改动文件 `cargo fmt` 后 0 格式差异。全工作区 `cargo test -j 1 --workspace --no-fail-fast` 的失败集与**无改动基线完全一致**(tuix 5:`event_loop::task_render_tests::result_non_task_output_falls_back` + `tool_format_tests::summarise_*` ×4;cli 1:`acp::translate::tests::policy_intervention_exposes_safe_recovery_without_secret_material`;capabilities 1:文档化已知红 `mcp::registry::tests::trust_key_golden_matches_core_algorithm`,铁律禁改),**未引入任何新失败**。G7/G8 `atomcode` 均 0 命中。
  - **[CORRECTION] 本条前述"review 1 为 locale 竞态,单跑 100/0"结论错误,已由第三十轮推翻**:review 那 1 个失败是**确定性**的,非竞态。正解见第三十轮。
  - **[WARN] 环境限制**:cgroup 内存上限 8GB,`cargo test --workspace` 默认并发下 rustc 会 SIGBUS(曾崩于 `rustcode-coding` 与 `rustcode` 的 `acp_end_to_end` 测试目标),**须用 `-j 1`**;崩溃产生的 `core.*` 已清理。
  - **[WARN] 存量 G1 违规(非本轮引入,本轮未触碰这些文件)**:`cargo fmt --check` 有 19 处差异,全在 `crates/rustcode-cli/src/{main.rs,schedule_cmd.rs}`、`crates/rustcode-coding/src/runtime.rs`、`crates/rustcode-tuix/src/event_loop/*`。

- **[DONE] 第三十轮:G1 格式门禁归零(19 处存量违规)(2026-09-02)**:
  - **范围**:`cargo fmt --check` 由 exit=1(19 处)归零。违规集中在 4 个包的 10 个文件——`cli/{main.rs,schedule_cmd.rs}`、`coding/runtime.rs`、`tuix/{event_loop/commands.rs,event_loop/mod.rs,modals/dir_picker.rs,modals/onboarding_wizard.rs,render/cell.rs,test_term.rs}`、`updater/lib.rs`。全部为纯格式问题(换行/缩进/行尾空格),非本轮引入。
  - **执行**:逐包 `cargo fmt -p rustcode|coding|tuix|updater`(裸 `cargo fmt` 会波及全工作区,刻意不用)。注意 **cli 的包名是 `rustcode`**。
  - **纯格式证明方法学(留档复用)**:`git diff -w` **不能**用于此证明——它只忽略行内空白,无法忽略 rustfmt 的换行合并(实测 258 行"假阳性")。正确做法是剥离**全部**空白字符后比对字符序列(`''.join(text.split())`)。结果:6 个文件完全一致;4 个文件的差异经 Python 定位为 **尾随逗号增删** 与 rustfmt `merge_derives` 合并相邻 `#[derive(...)]`,均零语义影响。
  - **越界证明**:21 个改动文件 283 增/104 删,减上一轮 11 文件的 230/44,余 53 增/60 删=113 行,恰等于本轮 10 个文件的行数之和(3+7+3+16+43+19+4+3+7+8)。上一轮改动未被触碰。
  - **验证**:G1 `cargo fmt --check` **exit=0 / 0 处差异**;G2 `cargo check -j 1 --workspace --all-targets` **exit=0 / 0 error**;单跑 `rustcode-coding --lib` **430/0**、`rustcode-updater --lib` **41/0** 全绿;全工作区 8 个失败**逐名比对零新增**(tuix 5 / cli 1 / capabilities 1 与 stash 基线一致,review 1 见下)。
  - **[CORRECTION] review 失败定性修正(推翻第二十九轮结论)**:`review_tool::tests::review_activity_line_composes_label_findings_and_tail` **不是** locale 竞态,而是**确定性失败**。实测断言 `left: "评审 · thinking"` vs `right: "review · thinking"`——该测试断言英文输出却**未持 locale 锁**,在默认中文(O5)下必然红。本轮 `--test-threads=1` 与单独过滤运行均 **4/4 失败**;第二十九轮单跑之所以 100/0,是**测试顺序运气**(别的 `pin_en()` 用例抢先设了 En),据此得出的"竞态"结论不成立。修法即 `:349` 已确立的 `let _g = pin_en();`,不改断言、不削弱测试。
  - **[DONE] 该缺锁已修(用户裁决「加 pin_en()」)**:`review_tool.rs` **+1 行**,用例首行加 `let _g = pin_en();`,**未改任何断言**。范围经核实精确到 1 处:`paths_match_*` 断言路径匹配、`sort_findings_*` 断言输入数据,均不含本地化文本;`render_findings_*` 本已持锁。验证:`cargo test -p rustcode-review --lib` **100/0**,且串行(`--test-threads=1`)+ 默认并发共 **4/4 全绿**,证明确定性转绿;G1 复检仍 **exit=0 / 0 差异**。
  - **[BLOCKER] 并发会话冲突(需用户裁决)**:本轮作业期间实测发现**另一编排会话在同一 worktree 并发写入**——`ps` 抓到非本会话的 `cargo test -p rustcode-codingplan --lib sync_marker`,对应看板 `.codebuddy/artifacts/2026-09-02-cleanup-codingplan-legacy/` 处于 **G3 实现中(T1 in_progress)**。本轮开始时改动面 11 文件,收尾时 **28 文件**,新增 6 个(`codingplan/src/{client,lib,setup,sync_marker,types}.rs`、`config/src/i18n/messages.rs`)来自对方。**直接冲突点**:对方 T3 要删 `crates/rustcode-cli/src/main.rs` 的 `Commands::Codingplan`(`:1696`/`:3573`,仍在、未执行),而本轮格式化了同文件 `:3363`;其决策日志把该文件的回滚策略记为「非 dirty,可安全 `git checkout`」,**执行回滚会抹掉本轮格式改动**。缓解事实:双方已写文件当前无交集,且对方写入后 G1 复检仍 exit=0。**本轮已停止一切 worktree 写入**;全量 `cargo test --workspace` 未复跑(与对方争用 target 锁与 daemon 固定端口会产生假红,参见前述 daemon 教训)。
  - **[WARN] 操作教训(防复发)**:工具会话超时约 60–90s,长任务须 `setsid nohup ... &` 脱离会话后轮询。第二十九轮的超时残留进程与本轮 `setsid` 进程**并发跑了两个全量测试**,既污染了同一日志路径(出现重复失败目标),又使两个 daemon 测试二进制争用固定端口 13456-13458,导致 `daemon_token_auth` 单次假红(事后单跑 **3/3 全绿**)。**同一日志路径绝不可被两个进程共用**。
  - **[WARN] 子代理通道不稳定**:本轮 `code-implementer` / `code-reviewer` 派发连续失败(一次 "No result found"、一次 idle timeout)。因 `cargo fmt` 是确定性工具调用而非业务代码编写,改由编排者直接执行并以只读命令完成等效验证。

- **[DONE] 第三十一轮:locale 锁缺陷批量修复——存量红 8 → 1(2026-09-02)**:
  - **根因同类**:第三十轮修的 review 缺锁并非孤例。tuix 的 5 个 `summarise_*` /
    `result_non_task_output_falls_back` 与 cli 的 `acp::translate` 共 **6 个用例**同为
    「断言英文串却未钉 locale」,在默认中文(O5)下必然红。实测断言
    `left: "Result（3 行）"` vs `right: "Result (3 lines)"`、
    `text.contains("separate terminal")` 不成立。依据 `:231` 约定逐个补
    `test_lock()` + `set_locale(Locale::En)`,**未改任何断言**。
  - **[CHECK] 关键教训:locale 锁分两种,用错会制造新红**。`summarise_multi_line_adds_line_count`
    是**刻意与 locale 无关**的测试——用 `i18n::t(Msg::TuixFoldLinesSuffix{count})` 现算期望后缀再比对,
    要求 `summarise()` 与 `t()` 两次调用间 **locale 保持稳定**。把它连同兄弟用例一起 set 成 En,
    反而**新增 2 个红**:(1) 该用例因我增多的 En 设置翻转了全局 locale,使两次调用拿到不同 locale 而失配;
    (2) 见下条。**正解:此类用例只持 `test_lock()` 取稳定性,绝不 `set_locale`**。
    **凡给断言英文的用例补锁时,必须先判明同模块是否存在 locale 无关型兄弟用例。**
  - **[WARN] 新发现的独立缺陷(未修,待裁决)**:`modals::session_picker::tests::replay_keeps_current_model_window_and_ignores_accounting_only_turn_positions`
    断言 `!label.contains("987")`(987654 为其「仅记账」哨兵值),但标签渲染了会话 ID
    `session-1788360798786`,该**毫秒时间戳数字串恰好含子串 "987" 时**断言失败。
    **与时间相关的固有偶发缺陷**,与 locale 无关、与本轮改动无关(末次运行该用例通过)。
    修法需改哨兵判定(改判 `total_tokens` 字段而非字符串包含)或改用固定会话 ID,涉及测试语义。
  - **验证(净减红,零新增)**:`rustcode-tuix --lib` **2059/5 → 2064/0**;`rustcode --lib`
    **115/1 → 116/0**;`rustcode-review --lib` **100/0**(第三十轮);`coding` 430/0;`updater` 41/0;
    `rustcode-capabilities --lib` 仍 1 个——文档化已知红 `trust_key_golden_matches_core_algorithm`(铁律禁改)。
    **存量红由 8 个降至 1 个。** G1 复检 **exit=0 / 0 差异**;本轮触碰文件严格限于自有 10 个,
    `cargo fmt -p` 未波及额外文件。
  - **[CHECK] G3 全量验证已锁定(用户裁决)**:`cargo test -j 1 --workspace --no-fail-fast`
    → **5481 passed / 1 failed**,90 个测试目标中 **89 个全绿**。分项:`cli --lib` 116/0、
    `tuix --lib` **2064/0**、`review --lib` 100/0、`coding --lib` 430/0、`config --lib` 327/0、
    `daemon --lib` 307/0、`updater --lib` 41/0、`kernel` 全绿;`capabilities --lib` 1475/1。
    **唯一失败即 `trust_key_golden_matches_core_algorithm`**(`AGENTS.md:226` 文档化已知红,
    DefaultHasher 跨工具链不稳定,铁律禁改)。存量红演进:**8 → 7(T3)→ 1(T4),净减 7,零新增**。
    执行要点:后台 `setsid` + 唯一日志路径,启动前确认 `pgrep -c cargo = 0`,
    规避双进程污染日志与争用 daemon 端口(参见第三十轮教训)。
  - **[WARN] 子代理通道不可用**:本轮派发 2 个 `code-implementer`(tuix / cli,`files_owned` 不相交),
    **均因 idle timeout 取消**,未落盘交接件、未产生代码改动(已核验)。cargo 编译期无增量输出触发空闲超时。
    **累计 3 次派发失败**(1 次 "No result found" + 2 次 idle timeout)。第三十轮与本轮均改由编排者
    直接执行 + 只读命令验证,**未绕过任何门禁**。后续长编译任务宜直接执行或先拆小。
  - **并发会话**:`cleanup-codingplan-legacy` 在本轮作业期间持续推进(已落地 T1 注释清零、
    T4 `docs/config.example.toml` 去重、T5 十份文档 `git mv` 到 `docs/archive/`)。
    **新增冲突点:其 T6 目标是 `docs/REFACTOR_DESIGN_PHASE1.md`,与本会话改动同一文件。**
    其 T3(`cli/src/main.rs` 删 `Commands::Codingplan`)截至本轮结束**仍未执行**。
    交接件见 `HANDOFF-codingplan-legacy.md`。

- **[DONE] 第三十二轮:用户可见文档 `atomcode` 残留清理 + 统计方法学纠错(2026-09-02)**:
  - **[ERROR] 方法学纠错:此前"全仓 9 文件 / 约 26 处"的统计是错的**。真实为 **92 处 / 29 文件**
    (`grep -rIoi "atomcode" --exclude-dir={target,.git,node_modules} . | wc -l`)。
    教训:`search_content` 工具的 `count` 模式**会低估**,统计残留面**必须用 shell 精确计数**,
    不要复用工具聚合结果。编排者据此错误统计得出过"O1 无剩余面"的结论,现予推翻。
  - **残留分布**:`AGENTS.md` 18、`.codebuddy/` ~40(交接件与 agent 定义)、`.goals/` 11、
    `.superpowers/pr/` 4、合规归属文档 9(`UPSTREAM_*`/`THIRD_PARTY_NOTICES`)、
    门禁定义 5、`docs/{features,platform-neutralization,REFACTOR_DESIGN_PHASE1}.md` 11、两个 README 4。
  - **三分法(后续清理照此判定)**:① **合规归属必留** —— `LICENSE`、
    `docs/{UPSTREAM_RUSTCODE_LICENSE,UPSTREAM_CREDITS,THIRD_PARTY_NOTICES,ORIGINAL_LICENSE}.md`;
    ② **门禁定义必留** —— G7/G8 那几行**本身就是 grep 模式**,删掉 `atomcode` 字样会让门禁失效
    (`docs/features.md:113-114`、`docs/platform-neutralization.md:204-206`);
    ③ **可清** —— 用户可见正文里把旧名当当前事物描述处。
  - **本轮清理**(doc-writer 执行,4 文件 7 增 7 删):两个 README 与
    `docs/{features,platform-neutralization}.md` 正文中的上游 slug `atomgit_atomcode/atomcode`
    改为「上游项目」,**并保留指向 `ORIGINAL_LICENSE.md` / `UPSTREAM_CREDITS.md` 的归属链接**;
    `docs/features.md:12` 的「产品重命名」项由 `atomcode-* → rustcode-*` 改为现状表述。
    **两个 README 现为 0 命中**;剩余 4 处全为规则②门禁定义,原样保留。
  - **[CHECK] MIT 合规性判定**:MIT 要求保留的是**版权声明与许可文本**,落点是 `LICENSE` 与上述
    归属文档,**并不要求 README 内联点名上游仓库 slug**。故本次删除 README 中的 slug 不削弱合规,
    归属信息仍完整可达。第二十八轮(`:282`)与第二十九轮(`:539`)「刻意保留 README 中该 slug」
    的相反决策已标 `[SUPERSEDED]`。
  - **G7/G8 结构性不受影响**:两者分别扫描 `crates/ scripts/ .github/` 与 `docs/architecture.md`,
    本轮改动的 4 个文件均不在其 grep 范围内,故清理**不可能**改变门禁结果。
  - **[CHECK] 子代理通道 :`doc-writer` 首次派发成功**(42 次工具调用)。关键差异:该角色**不执行
    构建/测试命令**,无 cargo 编译静默期,故不触发此前 3 次 `code-implementer` 的 idle timeout。
    **结论:涉及编译的任务慎用子代理,纯文档任务可正常派发。**
  - **[WARN] 子代理验证能力缺口**:`doc-writer` **无 shell 工具**,无法执行 `git diff --stat` 验证,
    已如实标注为验证缺口(未粉饰)。**该验证由编排者补齐**:确认改动严格限于 4 文件、
    7 增 7 删、`crates/` 无越界。

- **[DONE] 第三十三轮:`.goals`/`.superpowers` 清理 + 交付产物生成 + 流水线核查(2026-09-02)**:
  - **`.goals/` 清理**:2 文件 3 增 3 删。残留 **6 处全为 G7/G8 门禁定义与验收证据(必留)**;
    `inspector-feedback-1.md` 零改动(全文仅含验收证据)。
  - **`.superpowers/` 清理:残留归零**。修正 4 处**已失效的可执行命令**
    (`cargo test -p atomcode-{tuix,capabilities,daemon}` → `rustcode-*`,及任务书未点名的
    `cargo check -p atomcode` → `-p rustcode`)。映射依据 `crates/rustcode-cli/Cargo.toml:2`
    的 `name = "rustcode"`,**非臆测**。注意 cli 包名是 `rustcode` 而非 `rustcode-cli`。
  - **[CORRECTION] 子代理的 gitignore 判断有误,已由编排者实测纠正**:它据 `.gitignore` 条文推断
    `.superpowers/` 被忽略、改动不会入库。**实测 `git ls-files` 显示该文件已被跟踪、
    `git status` 显示 ` M`——会进入提交。** 教训:**已跟踪文件不受 gitignore 约束**,
    判断入库状态必须用 `git ls-files` / `git status` 实测,不能只读 `.gitignore`。
  - **产物已生成**:`05-test-report.md`(验证基线/逐门禁/逐套件/存量红演进/失败归因/零回归论证/未验证范围)、
    `06-release.md`(四段式交付清单 + 回滚方案 + 唯一下一步)、`03-impl/T6/T7/T8.md`、
    `HANDOFF-codingplan-legacy.md`。均位于 `.codebuddy/artifacts/2026-09-02-g1-fmt-gate/`。
  - **流水线核查(`.github/`)**:本会话与对方会话均未触碰流水线。**[2026-09-20 更新]** ci.yml 现有
    job 除 G1–G3 外,已补齐 G4(`headless-smoke`)、G5(`acp-smoke`)、G6/G7(`no-telemetry`)、
    G8(`no-stale-naming`)四个 CI job;G2 已收紧为 `-D warnings`(clippy warnings 收敛为 0)。
    **影响推论**(历史口径):① 本 feature 修好 19 处格式违规,使 CI 的 `fmt` job 由红转绿;
    ② CI `test` job 跑裸 `cargo test --workspace`,而 `trust_key` 确定性失败,该 job 仍将为红
    (既有状态,非本轮引入);③ `clippy` job 现加 `-D warnings`,warnings 已清零。
  - **对方 T3 已落地,恢复验证通过**:`crates/` 下 `Commands::Codingplan` **0 命中**(由 `doc-writer`
    实测发现并上报「编排者数据已过期」,核验属实)。恢复验证:**我的 fmt hunk
    (`cli/src/main.rs:3363`)存活**,与对方删除在同一文件共存;G1 **exit=0 / 0 差异**;
    G2 **exit=0 / 0 error**;G3 **5481 passed / 1 failed**、89 目标全绿,唯一失败仍为 `trust_key`。
    **G3 与 T3 落地前完全一致**,双方改动共存无损。
  - **[WARN] G2 口径澄清**:`AGENTS.md` 的 G2 真义是 `cargo clippy --workspace --all-targets`,
    本轮全程只跑了 `cargo check`。`clippy` 全量**尚未验证**,不得记为 G2 通过。
- **[WARN] `scripts/check-zh-docs.py` 中文文档门禁 AC-4 恒红(非本轮引入,已裁决「维持现状」)**:门禁基带 `ZH_BASE=3ee655e3` 自 zh-docs 中文 feature(`3c8df5cc feat(docs): zh-CN docs` 删 `README.zh-CN.md`、汉化 README 等)落地后从未推进,其后 20+ 个 commit(tunnel/wiki/auth 移除/账号命令等)持续改写 README/AGENTS/docs,造成大量未登记 code span,故 `check --files README.md AGENTS.md docs/platform-neutralization.md` 恒 FAIL(AC-4 code span 多重集不等)。该门禁未被任何 CI 引用,属本地人工门禁;AC-4 判据冻结、扩登 `AC4_ALLOWED_ADDED_BY_FILE` 需裁决,不阻塞发行链路交付。

## 高信号文档索引

- **`docs/phase1-refactor-design.md`** — PHASE-1 方案与 PHASE-2 缺口(设计决策、已知失败、缺陷清单)
- **`docs/CONTEXT.md`** — 运行时领域术语定义(注意:旧 `RustCode` 命名,但术语有效)
- **`docs/architecture.md`** — 架构描述(已更新为 `rustcode-*` 命名)
- **`docs/REFACTOR_DESIGN_PHASE1.md`** — 重命名前的基线设计(历史决策记录)
- **`docs/model-fallback-requirements.md`** — 模型回退能力需求与实施记录(触发判据 / 回退链配置面 / 验收标准 / 落点与不变量 / §10 实测契约与诚实边界)
- **`crates/rustcode-capabilities/src/fallback.rs`** — 可回退失败的**共享判定**单点(`fallback_eligible` / `fallback_eligible_for_stop`);主 agent(`coding/src/runtime.rs` 的 `try_model_fallback`)与四个子代理调用方(`tools/task.rs` 的 `retryable_content_free_failure`、`coding/src/team/runner.rs` 的成员游走、`tools/parallel_edit.rs` 的每文件子代理、`rustcode-review/src/review_tool.rs` 的 `run_review_pass`)**共用**它,禁止调用点各写一份 `if`。L2 侧的链游走器在 `crates/rustcode-coding/src/fallback.rs`(`FallbackWalk`,单调前进 + 显式耗尽)。子代理的显式链由持有 `Config` 的 `coding/src/parts.rs` 解析后经 `with_chain_providers(...)` 注入(`task` / `team` / `code_review` 均已接;`parallel_edit_files` 在本仓无生产构造点,仅能力面),`capabilities` 因此不新增 `rustcode-config` 依赖。
- **`rustcode-config/src/distribution.rs`** — 重命名事实源(HOME_ENV / 端口 / 进程名)
- **`rustcode-config/src/endpoints.rs`** — 环境变量名与托管端点
