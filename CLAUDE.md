# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 说明:按用户全局偏好,本仓库的 Markdown 文档使用简体中文;代码、注释、提交信息、脚本、配置等其余产物一律使用英文。

## 仓库现状(务必先读)

**这是一个全新的空仓库**:刚 `git init`,**无任何提交、无文件、无远程**。本文件目前是仓库里唯一的内容,用于给后续的 Claude Code 会话提供"这个项目是什么、要怎么做"的奠基性上下文。

因此:本文件中**"已确认"的部分是产品事实与团队决策**,**"参考工具链/待定"的部分尚未落地为本仓库的代码或脚本**。在补充本文件时,请只写已被核实的内容,不要凭空编造构建命令、目录结构或架构细节。

## 产品(已确认)

- **代号**:`teleport`;**中文名(暂定)**:闪现;**英文名(暂定)**:Teleport。
- **形态**:基于 **Chromium 源码**自研的**企业安全浏览器**。
- **核心能力**:接收并执行由服务端下发的**安全策略**(浏览器作为受管端,策略在服务端集中管理与下发)。

## 与 `fairyland` 的关系(已确认)

浏览器的**服务端不在本仓库**,而在**同级目录的 `fairyland` 仓库**(`../fairyland`)。

- `fairyland` 是公司**全部服务端产品的 monorepo**,不只是浏览器后端;它本身是一个 B2B DSPM(数据安全态势管理)平台,采用微服务架构。
- 浏览器的**策略下发后端**将作为 `fairyland` 中的一个(或多个)服务存在。**该服务的代号尚未确定**(见"待定事项")。
- 浏览器端(本仓库)与服务端的**策略下发协议格式尚未定义**(见"待定事项")。改动任一端的协议时,务必同步另一端。

`fairyland` 的工程约定可作为本项目的参考基线(命名、工作流、文档结构等,见下文)。其完整约定见 `../fairyland/CLAUDE.md` 与 `../fairyland/README.md`。

## 命名约定(沿用 fairyland 体系)

`fairyland` 使用**奇幻/魔幻代号**作为服务的规范标识符,贯穿目录、包名、K8s、NATS、配置键等所有位置(如 `sigil`、`realm`、`warden`、`prism`、`telepathy`、`seer`、`phantom`、`portal`)。

`teleport`(闪现,游戏术语"瞬移")延续同一命名体系。本项目内新增的模块/服务代号应保持这一风格,并在选定后作为各处的规范标识符统一使用。

## Chromium 集成策略(已确认:补丁/叠加层)

采用 **patch/overlay(补丁叠加层)** 模式,而非把 Chromium 整体 fork 入库(类似 Brave / Vivaldi 的做法):

- 通过 **depot_tools / gclient** 将**上游 Chromium 拉取到外部的 `src/`** 检出,**不**把 `chromium/src` 提交进本仓库。
- 本仓库只存放**定制代码**:针对上游的 **patches**,以及一个独立的 **`//teleport` 模块**(企业安全特性、策略执行等)。
- 收益:仓库体积小、跟随上游升级成本低。

**当前上游基线版本**:**Chromium M148**。M150 非稳定版,**初期基于 M148 开发,后续再升级**。来源 `https://chromium.googlesource.com/chromium/src.git`。

> 仓库布局(patches 目录结构、`//teleport` 模块位置、gclient 钩子如何把本仓库注入 `src/` 等)**尚未敲定**,见"待定事项"。

## 目标平台(已确认)

- **Windows、macOS、Linux**(三端均为目标),企业场景通常**以 Windows 为主**。
- **未来需适配国产操作系统**(如鸿蒙 HarmonyOS 等信创环境);**MVP 阶段可暂不覆盖**。

## 构建工具链(标准 Chromium,本仓库尚未封装)

采用上游标准 depot_tools / GN 流程;**本仓库自己的构建/同步脚本尚不存在**。

- **构建工具:Siso**(Chromium 自 2025 年中起在非 Google 环境默认启用,是 Ninja 的直接替代)。`autoninja` 会自动调用 Siso(执行一次 `gn clean` 后生效);如需退回 Ninja,在 `args.gn` 设 `use_siso=false`。**Ninja + Reclient 正在被弃用**。
- **ccache 基本不再需要**:Siso 原生支持远程执行(RBE),并尽量减少磁盘/网络 I/O 与内存占用,自带缓存能力。
- 标准流程:

  ```bash
  gclient sync                      # 同步上游源码与依赖
  gn gen out/Default                # 生成构建目录(读取 args.gn)
  autoninja -C out/Default chrome   # 经 autoninja 调用 Siso 编译
  ```

> `out/` 的 `args.gn` 具体配置、以及本仓库的构建/同步脚本封装,均**尚未确定**(见"待定事项")。

## 开发工作流(公司级约定)

- **分支模型**:GitLab Flow —— `main` 为唯一事实来源,从 `main` 切分支、合回 `main`;合并采用 **rebase onto main + squash + fast-forward**(不产生 merge commit)。
- **TDD**:严格 Red → Green → Refactor。
- **设计文档/计划**:沿用 `fairyland` 结构,放在 `docs/superpowers/specs/`(设计与规格)与 `docs/superpowers/plans/`(实现计划)。
- **brainstorming 命令**:在新分支的独立 git worktree 中进行,并把 spec、plan、实现一并提交到该分支。

> CI 平台:`fairyland` 使用 **Gitea Actions**(`.gitea/workflows/`)。本仓库的 CI **尚未建立**。

## 待定事项(请勿臆测,需明确决策后再写入)

- 仓库目录布局:`patches/` 结构、`//teleport` 模块位置、gclient 钩子/`DEPS` 注入方式。
- 本仓库自身的构建/同步脚本与命令封装。
- 浏览器后端在 `fairyland` 中的**服务代号**及其归属。
- 浏览器端 ↔ 服务端的**策略下发协议**(传输方式、消息格式、鉴权)。
- 代码签名、打包与分发(各平台企业部署方式)。
- 国产 OS(鸿蒙等)适配的时间点与范围。
- CI(构建/编译时长较长,需规划缓存与产物策略)。

## 参考材料(同级目录)

- `../fairyland/CLAUDE.md`、`../fairyland/README.md` —— 服务端 monorepo 的完整工程约定(命名、proto-first、gRPC + NATS、测试与日志规范等),作为本项目工程约定的基线参考。
