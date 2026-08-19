# 验证结论:edge / gate 排除的覆盖语义(Task 4 Step 1)

- **验证对象**:`$TELEPORT_CHROMIUM_ROOT/151.0.7922/src`(M151,`CHROMIUM_VERSION=151.0.7922.76`)
- **验证方式**:纯源码阅读 + 由 Task 4 的两个单测活体钉住结论
- **产出用途**:直接决定 Task 4 Step 2 的断言与 Step 4 的判据

---

## Q1. `base::MatchPattern` 的 `*` 是否跨点?`?` 与 `\` 的语义?

**`*` 跨点。它就是「任意字符任意个数」,对 `.` 没有任何特殊处理。**

文档语义(`base/strings/pattern.h:14-18`):

```
// Returns true if the |string| passed in matches the |pattern|. The pattern
// string can contain wildcards like * and ?.
//
// The backslash character (\) is an escape character for * and ?.
// ? matches 0 or 1 character, while * matches 0 or more characters.
```

实现证据:

- `EatWildcards`(`base/strings/pattern.cc:97-112`)吞掉连续的 `*` / `?`,**只要含一个 `*` 就返回 `-1`**(`:111` `return has_asterisk ? -1 : num_question_marks;`),即「无限距离」;
- 该返回值作为 `maximum_distance` 传进 `SearchForChars`(`:115-128` 的 `MatchPatternT`),后者在失配时执行 `maximum_distance--` 后**从字符串的下一个字符重新开始匹配整个 pattern 片段**(`:76-89`,其中 `:79` `if (maximum_distance == 0) return false;`)。`-1` 递减永远碰不到 `0`,所以扫描一路走到串尾;
- 整个循环里**没有任何针对 `.` 的判断**——这是朴素子串搜索(`:76` 的 TODO 自述 naive),故 `*` 跨点。

`?` 是 **0 或 1** 个字符(不是「恰好 1 个」):`num_question_marks` 计数后作为最大距离,允许 0..n 次重启。
`\` 是 `*` / `?` 的转义符(`pattern.cc:49-53` 的 `escape` 分支)。

## Q2. gate 为 `gate.tp.D`、条目 host 为 `D` 且带通配时,`*.D` 是否匹配 `gate.tp.D`?

**是。** 通配条目产出的规则是 `*.` + `D`(`teleport_tunnel_logic.cc` 的 Task 2 实现),即 `*.d.example`。
按 Q1:`EatWildcards` 吃掉 `*` 返回 `-1`,`SearchForChars` 在 `gate.tp.d.example` 中搜索字面量 `.d.example`,在偏移 6 处命中,且此时 pattern 与 string **同时耗尽**(`pattern.cc:35-40`),返回 `true`。

**推论(承重)**:**把 gate 往更深的子域搬不能规避**。任何位于 `D` 或 `D` 之上的通配条目都会捕获 `gate.tp.D`——因为 `*` 跨点,层级深浅不构成防护。故排除判据**不能**是「直接子域」「标签数比较」这类形状判断。

该结论由 `TeleportRoutableOriginExclusionTest.ExcludesWildcardCoveringGate` 活体钉住:判据若退化成 host 相等,该测试立刻变红。

## Q3. 排除判据的正确形式

```
条目 origin(host = H, include_subdomains = W)覆盖保留主机 R,当且仅当:
    H == R                                  // 精确条目与通配条目都产出裸 H 规则
或  W 且 base::MatchPattern(R, "*." + H)     // 通配条目额外产出 *.H 规则
```

即:**用条目实际产出的那两条规则去反查保留主机**,而不是用标签计数或子域关系去猜。两侧比较前统一归一为 host-only(去端口)、ASCII 小写、去尾点——条目侧已由 Task 3 的 `RejectHost` 保证(小写、无尾点、规范),故实际只需归一保留主机那一侧。

**已知代价(必须写进注释,不能假装没有)**:命中覆盖分支时整条通配条目被丢弃,该域下**全部**应用一起失去路由。Chromium 的规则语法**没有否定形式**(`SchemeHostPortMatcherRule` 只有 include / exclude 两类规则,而 `<-loopback>` 那种 exclude 规则不接受任意主机名),所以「路由 `*.D` 但排除 gate/edge」在这套语法里**不可表达**。主防线因此是服务端写入面拒绝此类登记,客户端这条是 fail-safe 的另一半。

## Q4. 为什么 gate 要排在 edge 前面判

`*.d.example` 同时覆盖 `gate.tp.d.example` 与 `edge.tp.d.example`,两条都命中时只能给出一个原因。**先判 gate**:自锁链路是 bind 自己的 `POST https://gate.<D>/tunnel/bind` 被路由进 edge——而它需要的 cnf 令牌正是这次 bind 要去取的,于是隧道永久停摆。edge 被路由进 edge 是同类问题的第二顺位。
