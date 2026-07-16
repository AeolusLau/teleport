# 部署域名配置 Phase 2a(teleport 客户端侧)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 客户端侧提供 server-identity 验证基元:把 `ServerIdentityData` 编进客户端(overlay 首个 proto_library),实现纯验证库 `VerifyServerIdentity`(验根签名 + 校 message_type/domain/过期),并用跨仓往返测试(fairyland 铸造 → 客户端验签,dev 公钥)证明 wire+签名兼容。

**Architecture:** 验证库放进**独立的较重 //teleport target**(deps `//crypto` + 新 proto_library),**不进 `teleport_deployment_config` leaf**(crypto+proto 会经 `//components/policy/proto` 重新成环)。**根密钥 DER 作参数注入**(Phase 2b 调用方传烘焙 `GetPolicyVerificationKey()`),验证库本身纯、可测。**无 Local State、无 fetch、无 resolver 接线、无 UI**——全部留 Phase 2b。

**Tech Stack:** C++(Chromium M148 overlay)、GN proto_library(proto3)、`crypto::SignatureVerifier`(RSA_PKCS1_SHA256)、gtest。

## Global Constraints

- **配对仓库**:fairyland(同名分支/worktree)。协议准源:本仓 `docs/superpowers/specs/2026-07-15-deployment-domain-config-design.md` §4.1。fairyland 侧计划:`../fairyland/docs/superpowers/plans/2026-07-15-deployment-domain-config-phase2a-fairyland.md`。
- **跨仓 wire 契约(硬约束,与 fairyland 逐字一致)** —— `ServerIdentityData`(proto3,wire 兼容只依赖字段号+类型):
  ```proto
  string message_type   = 1;   // 哨兵 "TeleportServerIdentity"
  uint32 version         = 2;   // 当前 1
  string domain          = 3;   // canonical D
  int64  not_after_unix  = 4;   // 过期,Unix 秒
  ```
- **容器格式(与 fairyland mint 逐字一致)**:blob = `u32be(len(signed_bytes)) || signed_bytes || signature`;`signed_bytes` = 序列化 `ServerIdentityData`;`signature` = 根密钥对 `signed_bytes` 的 RSA-PKCS1v1.5-SHA256 签名。
- **依赖环红线**:验证库与 proto **绝不进 `teleport_deployment_config` leaf**(它 //base+//url、被 //components/policy 消费)。验证库是独立 source_set,根密钥 DER **注入**(不在库内调 `GetPolicyVerificationKey()`,那会引 //components/policy)。
- **验签算法固定** RSA_PKCS1_SHA256,与 `CloudPolicyValidatorBase::VerifySignature`(`components/policy/core/common/cloud/cloud_policy_validator.cc:263`)同款原语。
- **一文件一 patch**;**TDD**(gtest,产品代码);构建/测试命令见下(worktree 需 `export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium`)。
- **overlay 首个 proto**:src/ 此前无 `.proto`/`proto_library`;本计划引入 `//third_party/protobuf` proto_library——属新构建面,注意其只落在验证库 target,不污染 leaf。
- **不做(留 Phase 2b/2c)**:Local State 自认证条目、resolver 第 4 级接线、`teleport://connect` 页、深链接、gate 精确白名单、fetch(SimpleURLLoader)、§4.5 迁移接线。

---

### Task 1: 客户端 `server_identity.proto` + overlay 首个 proto_library

**Files:**
- Create: `src/common/server_identity.proto`
- Modify: `src/BUILD.gn`(顶部 `import` protobuf 规则;新增 `proto_library("server_identity_proto")`)
- Create: `src/common/server_identity_proto_smoke_unittest.cc`(最小构造/序列化测试,证明 proto 编进客户端)

**Interfaces:**
- Produces: C++ 类型 `teleport::v1::ServerIdentityData`(proto3;生成头 `teleport/common/server_identity.pb.h`),GN target `//teleport:server_identity_proto`。

- [ ] **Step 1: 写 proto(镜像 fairyland wire)**

创建 `src/common/server_identity.proto`:

```proto
syntax = "proto3";

package teleport.v1;

// Client mirror of fairyland's teleport.v1.ServerIdentityData. Wire-compatible by
// field number + type (package/message name need not match the server; only the
// wire shape does). The browser verifies the enclosing root signature, then reads
// message_type / domain / not_after_unix from this parsed message.
message ServerIdentityData {
  string message_type = 1;
  uint32 version = 2;
  string domain = 3;
  int64 not_after_unix = 4;
}
```

- [ ] **Step 2: 加 proto_library 到 src/BUILD.gn**

在 `src/BUILD.gn` 顶部 import 区加:
```gn
import("//third_party/protobuf/proto_library.gni")
```
在 `buildflag_header(...)` 之后、`source_set("teleport_deployment_config")` 之前新增:
```gn
# Client-side ServerIdentityData proto (proto3), wire-compatible with fairyland's
# teleport.v1.ServerIdentityData. Kept as its own target so ONLY the heavier
# server-identity verification lib depends on protobuf — never the //base+//url
# teleport_deployment_config leaf (which //components/policy consumes; adding a
# proto/policy dep there would reintroduce the dependency cycle).
proto_library("server_identity_proto") {
  sources = [ "common/server_identity.proto" ]
  proto_in_dir = "//teleport/src"
  cc_generator_options = "lite=true:"
}
```

> 注:`proto_in_dir` + 生成头路径以检出实际为准。overlay 挂载为 `//teleport`(→ `chromium/src/teleport`),源在 `//teleport/src/common/server_identity.proto`;若 GN 报 `proto_in_dir`/import 路径问题,按 chromium proto_library 约定调整(生成头形如 `teleport/src/common/server_identity.pb.h` 或 `teleport/common/...`,实现期以 `gn gen` 报错为准确定,并在 smoke 测试 include 处对齐)。`lite=true` 用 protobuf-lite(客户端够用、更轻)。

- [ ] **Step 3: 写 smoke 测试(证明 proto 编进客户端)**

创建 `src/common/server_identity_proto_smoke_unittest.cc`(include 路径以 Step 2 实际生成路径为准):

```cpp
#include "teleport/common/server_identity.pb.h"

#include <string>

#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Proves the ServerIdentityData proto compiles into the client and round-trips
// through serialize/parse — the wire contract shared with fairyland.
TEST(ServerIdentityProtoTest, RoundTrips) {
  teleport::v1::ServerIdentityData msg;
  msg.set_message_type("TeleportServerIdentity");
  msg.set_version(1);
  msg.set_domain("acme.internal");
  msg.set_not_after_unix(4102444800);
  std::string bytes = msg.SerializeAsString();

  teleport::v1::ServerIdentityData parsed;
  ASSERT_TRUE(parsed.ParseFromString(bytes));
  EXPECT_EQ(parsed.message_type(), "TeleportServerIdentity");
  EXPECT_EQ(parsed.version(), 1u);
  EXPECT_EQ(parsed.domain(), "acme.internal");
  EXPECT_EQ(parsed.not_after_unix(), 4102444800);
}

}  // namespace
}  // namespace teleport
```

把该文件加入 `test("teleport_unittests")` 的 sources(字母序),并给 `teleport_unittests` 的 deps 加 `":server_identity_proto"`。

- [ ] **Step 4: 生成 + 构建 + 跑测试**

```bash
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter='ServerIdentityProtoTest.*'
```
Expected:`gn gen` 解析 proto_library 成功;`RoundTrips` PASS。若生成头 include 路径不对,按 `gn gen`/编译报错修正 include 与 `proto_in_dir` 后重试(记录最终路径供 Task 2 验证库 include 对齐)。

- [ ] **Step 5: Commit**

```bash
git add src/common/server_identity.proto src/common/server_identity_proto_smoke_unittest.cc src/BUILD.gn
git commit -m "feat(server-identity): add client ServerIdentityData proto (overlay's first proto_library)"
```

---

### Task 2: 纯验证库 `VerifyServerIdentity` + 容器解析

独立较重 target 里的两个纯函数:解析 `u32be||signed||sig` 容器;验根签名 + 解析 proto + 校 message_type/domain/过期。根密钥 DER 与 now 均注入 → 完全可测,不依赖烘焙密钥/系统时钟。

**Files:**
- Create: `src/common/teleport_server_identity.h`
- Create: `src/common/teleport_server_identity.cc`
- Create: `src/common/teleport_server_identity_unittest.cc`
- Modify: `src/BUILD.gn`(新增 `source_set("teleport_server_identity")` deps `//crypto` + `:server_identity_proto` + `//base`;unittest 源与 dep 加入 `teleport_unittests`)

**Interfaces:**
- Consumes: `teleport::v1::ServerIdentityData`(Task 1)、`crypto::SignatureVerifier`。
- Produces:
  ```cpp
  namespace teleport {
  struct ServerIdentityParts { std::vector<uint8_t> signed_bytes; std::vector<uint8_t> signature; };

  // Split the wire container u32be(len)||signed_bytes||signature. nullopt if the
  // buffer is too short or the length prefix is inconsistent.
  std::optional<ServerIdentityParts> ParseServerIdentityContainer(
      base::span<const uint8_t> blob);

  // Verify signed_bytes' root signature (RSA_PKCS1_SHA256) against root_key_der
  // (DER SubjectPublicKeyInfo), then parse ServerIdentityData and require:
  // message_type == "TeleportServerIdentity", version supported, domain ==
  // candidate_domain, and now < not_after_unix. Returns true only if ALL hold.
  bool VerifyServerIdentity(base::span<const uint8_t> signed_bytes,
                            base::span<const uint8_t> signature,
                            base::span<const uint8_t> root_key_der,
                            std::string_view candidate_domain,
                            base::Time now);
  }  // namespace teleport
  ```

- [ ] **Step 1: 写失败测试(注入临时 RSA 密钥 + 篡改各字段)**

创建 `src/common/teleport_server_identity_unittest.cc`。用 `crypto` 生成临时 RSA 密钥签名、导出 SPKI DER 验签(model:`components/policy/core/common/cloud/test/policy_builder.cc:250/393`)。核心用例:

```cpp
#include "teleport/common/teleport_server_identity.h"

#include <cstdint>
#include <string>
#include <vector>

#include "base/time/time.h"
#include "crypto/keypair.h"          // crypto::keypair::PrivateKey (RSA)
#include "crypto/sign.h"             // crypto::sign::Sign (RSA_PKCS1_SHA256)
#include "teleport/common/server_identity.pb.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Helpers: build+sign a ServerIdentityData with an ephemeral key; return
// (signed_bytes, signature, spki_der). (Exact crypto:: API per checkout —
// mirror policy_builder.cc's RSA_PKCS1_SHA256 signing.)
struct Signed { std::vector<uint8_t> signed_bytes, signature, spki_der; };
Signed MakeSigned(const std::string& message_type, const std::string& domain,
                  int64_t not_after_unix);  // impl in Step 3 test-support inline

constexpr char kSentinel[] = "TeleportServerIdentity";
const base::Time kNow = base::Time::FromTimeT(1750000000);  // ~2025-06
constexpr int64_t kFuture = 4102444800;                     // 2100

TEST(TeleportServerIdentityTest, VerifiesValidBlob) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  EXPECT_TRUE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                   "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsWrongMessageType) {
  Signed s = MakeSigned("NotTheSentinel", "acme.internal", kFuture);
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsDomainMismatch) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "evil.example", kNow));
}

TEST(TeleportServerIdentityTest, RejectsExpired) {
  Signed s = MakeSigned(kSentinel, "acme.internal", 1000000000);  // 2001, past
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsTamperedSignature) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  s.signature[0] ^= 0xFF;
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, s.spki_der,
                                    "acme.internal", kNow));
}

TEST(TeleportServerIdentityTest, RejectsWrongKey) {
  Signed s = MakeSigned(kSentinel, "acme.internal", kFuture);
  Signed other = MakeSigned(kSentinel, "acme.internal", kFuture);  // different key
  EXPECT_FALSE(VerifyServerIdentity(s.signed_bytes, s.signature, other.spki_der,
                                    "acme.internal", kNow));
}

TEST(TeleportServerIdentityContainerTest, RoundTripsContainer) {
  // u32be(3) || {0xAA,0xBB,0xCC} || {0xDD,0xEE}
  std::vector<uint8_t> blob = {0,0,0,3, 0xAA,0xBB,0xCC, 0xDD,0xEE};
  auto parts = ParseServerIdentityContainer(blob);
  ASSERT_TRUE(parts);
  EXPECT_EQ(parts->signed_bytes, (std::vector<uint8_t>{0xAA,0xBB,0xCC}));
  EXPECT_EQ(parts->signature, (std::vector<uint8_t>{0xDD,0xEE}));
}

TEST(TeleportServerIdentityContainerTest, RejectsTruncated) {
  EXPECT_FALSE(ParseServerIdentityContainer(std::vector<uint8_t>{0,0,0,9, 0x01}));  // len>data
  EXPECT_FALSE(ParseServerIdentityContainer(std::vector<uint8_t>{0,0}));            // <4 bytes
}

}  // namespace
}  // namespace teleport
```

> `MakeSigned` 的实现放测试文件内(inline),用检出实际的 `crypto` 签名/密钥 API(以 `policy_builder.cc` 为准模型)。实现期若 `crypto::sign`/`crypto::keypair` 具体签名与此处不符,按检出 API 校正(保持「临时 RSA 密钥签 signed_bytes、导出 SPKI DER」的语义)。

- [ ] **Step 2: 跑测试确认 RED**

```bash
autoninja -C "$TELEPORT_CHROMIUM_DIR/src/out/mac/arm64/dev" teleport_unittests
```
Expected: 编译失败(`VerifyServerIdentity`/`ParseServerIdentityContainer` 未声明)。

- [ ] **Step 3: 实现验证库**

创建 `teleport_server_identity.h`(声明如 Interfaces)。创建 `teleport_server_identity.cc`:

```cpp
#include "teleport/common/teleport_server_identity.h"

#include <cstring>

#include "crypto/signature_verifier.h"
#include "teleport/common/server_identity.pb.h"

namespace teleport {

namespace {
constexpr char kExpectedMessageType[] = "TeleportServerIdentity";
constexpr uint32_t kSupportedVersion = 1;
}  // namespace

std::optional<ServerIdentityParts> ParseServerIdentityContainer(
    base::span<const uint8_t> blob) {
  if (blob.size() < 4) {
    return std::nullopt;
  }
  uint32_t len = (uint32_t{blob[0]} << 24) | (uint32_t{blob[1]} << 16) |
                 (uint32_t{blob[2]} << 8) | uint32_t{blob[3]};
  if (static_cast<size_t>(len) + 4 > blob.size()) {
    return std::nullopt;  // length prefix overruns buffer
  }
  ServerIdentityParts parts;
  parts.signed_bytes.assign(blob.begin() + 4, blob.begin() + 4 + len);
  parts.signature.assign(blob.begin() + 4 + len, blob.end());
  if (parts.signature.empty()) {
    return std::nullopt;  // no signature bytes
  }
  return parts;
}

bool VerifyServerIdentity(base::span<const uint8_t> signed_bytes,
                          base::span<const uint8_t> signature,
                          base::span<const uint8_t> root_key_der,
                          std::string_view candidate_domain,
                          base::Time now) {
  // 1) Root signature over signed_bytes (RSA_PKCS1_SHA256), same primitive as
  //    CloudPolicyValidatorBase::VerifySignature.
  crypto::SignatureVerifier verifier;
  if (!verifier.VerifyInit(crypto::SignatureVerifier::RSA_PKCS1_SHA256,
                           signature, root_key_der)) {
    return false;
  }
  verifier.VerifyUpdate(signed_bytes);
  if (!verifier.VerifyFinal()) {
    return false;
  }
  // 2) Parse + field checks.
  teleport::v1::ServerIdentityData data;
  if (!data.ParseFromArray(signed_bytes.data(),
                           static_cast<int>(signed_bytes.size()))) {
    return false;
  }
  if (data.message_type() != kExpectedMessageType) {
    return false;
  }
  if (data.version() != kSupportedVersion) {
    return false;
  }
  if (data.domain() != candidate_domain) {
    return false;
  }
  if (now >= base::Time::FromTimeT(data.not_after_unix())) {
    return false;  // expired
  }
  return true;
}

}  // namespace teleport
```

在 `src/BUILD.gn` 新增(在 `server_identity_proto` 之后):
```gn
# Server-identity verification lib. Heavier than the leaf (deps //crypto + the
# proto); the level-4 caller (Phase 2b, in //chrome/browser) injects the baked
# root key DER — this lib never touches //components/policy or Local State.
source_set("teleport_server_identity") {
  sources = [
    "common/teleport_server_identity.cc",
    "common/teleport_server_identity.h",
  ]
  deps = [
    ":server_identity_proto",
    "//base",
    "//crypto",
  ]
}
```
把 `teleport_server_identity_unittest.cc` 加入 `teleport_unittests` sources(字母序),deps 加 `":teleport_server_identity"` 与 `"//crypto"`。

- [ ] **Step 4: 跑测试确认 GREEN**

```bash
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportServerIdentity*'
```
Expected: 全部 PASS(有效 blob 通过;错 message_type / 域不匹配 / 过期 / 篡改签名 / 错密钥 均 false;容器解析 round-trip + 截断拒绝)。

- [ ] **Step 5: Commit**

```bash
git add src/common/teleport_server_identity.h src/common/teleport_server_identity.cc \
        src/common/teleport_server_identity_unittest.cc src/BUILD.gn
git commit -m "feat(server-identity): pure verify lib (root sig + message_type/domain/expiry, injectable key)"
```

---

### Task 3: 跨仓往返联合测试(fairyland 铸造 blob ↔ 客户端验签,dev 公钥)

用一份由 **fairyland `server-identity-mint` 工具真实铸造**的 blob(远期过期,作固定 fixture)+ **vendored dev 根公钥 DER**,断言客户端验证库通过。这证明两仓 wire 格式 + 签名算法逐字兼容——Phase 2a 的核心验收。

**Files:**
- Create: `src/common/test_data/server_identity_dev_fixture.bin`(由 fairyland mint 工具生成,提交)
- Create: `src/common/teleport_server_identity_joint_unittest.cc`
- Modify: `src/BUILD.gn`(fixture 作为 test data;joint unittest 入 `teleport_unittests`)

**Interfaces:**
- Consumes: Task 2 的 `ParseServerIdentityContainer` + `VerifyServerIdentity`;vendored `keys/dev-policy-root.pub.pem`。

- [ ] **Step 1: 用 fairyland 工具铸造固定 fixture**

在 fairyland worktree 跑 mint 工具产出一份**远期过期**(100 年 TTL,避免 fixture 随时间失效)、domain=`fairyland.io` 的 blob:
```bash
cd /Users/liulichao/workspace/fairyland/.claude/worktrees/deployment-domain-config
POLICY_ROOT_KEY_PATH=products/teleport/device-manager/keys/dev-policy-root.pem \
SERVER_IDENTITY_DOMAIN=fairyland.io SERVER_IDENTITY_TTL_DAYS=36500 \
OUTPUT_PATH=/tmp/sid_fixture.bin \
go run -mod=vendor ./products/teleport/device-manager/cmd/server-identity-mint/
cp /tmp/sid_fixture.bin \
  /Users/liulichao/workspace/teleport/.claude/worktrees/deployment-domain-config/src/common/test_data/server_identity_dev_fixture.bin
```
> fixture 由 dev 根**私钥**签(私钥在 fairyland 仓);客户端只 vendored **公钥**。dev 密钥轮换时需重生成该 fixture(在 joint 测试注释中记录)。

- [ ] **Step 2: 取 dev 根公钥 DER 供测试**

dev 根公钥 DER = `keys/dev-policy-root.pub.pem` 的 base64 解码(与烘焙 `kDevPolicyKey` 同字节)。用 `scripts/gen_policy_verification_key.py` 的 `load_pub_der()` 打印其 hex,内嵌进 joint 测试为常量数组(或测试运行时读 PEM 解码——但 gtest 读仓外文件不便,内嵌 DER 更稳):
```bash
cd /Users/liulichao/workspace/teleport/.claude/worktrees/deployment-domain-config
uv run python -c "import scripts.gen_policy_verification_key as g; print(g.load_pub_der('keys/dev-policy-root.pub.pem').hex())"
```
把输出 hex 转为 `constexpr uint8_t kDevRootKeyDer[] = {...}` 内嵌测试。

- [ ] **Step 3: 写 joint 测试**

创建 `src/common/teleport_server_identity_joint_unittest.cc`:

```cpp
#include "teleport/common/teleport_server_identity.h"

#include <cstdint>
#include <vector>

#include "base/base_paths.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/path_service.h"
#include "base/time/time.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace teleport {
namespace {

// Dev policy-root PUBLIC key DER (== baked kDevPolicyKey; from
// keys/dev-policy-root.pub.pem). Regenerate with the fixture if the dev key rotates.
constexpr uint8_t kDevRootKeyDer[] = { /* hex bytes from Step 2 */ };

// Cross-repo round-trip: a blob minted by fairyland's server-identity-mint (dev
// root PRIVATE key) must verify under the client lib with the dev PUBLIC key.
// Proves wire + signature compatibility across the two repos.
TEST(TeleportServerIdentityJointTest, VerifiesFairylandMintedDevBlob) {
  base::FilePath dir;
  ASSERT_TRUE(base::PathService::Get(base::DIR_SRC_TEST_DATA_ROOT, &dir));
  base::FilePath path = dir.AppendASCII(
      "teleport/src/common/test_data/server_identity_dev_fixture.bin");
  std::string blob;
  ASSERT_TRUE(base::ReadFileToString(path, &blob));

  std::vector<uint8_t> bytes(blob.begin(), blob.end());
  auto parts = ParseServerIdentityContainer(bytes);
  ASSERT_TRUE(parts);
  // Fixture minted for fairyland.io with a 100-year TTL; verify at a fixed 'now'.
  EXPECT_TRUE(VerifyServerIdentity(parts->signed_bytes, parts->signature,
                                   kDevRootKeyDer, "fairyland.io",
                                   base::Time::FromTimeT(1750000000)));
  // Negative: wrong candidate domain must fail even for a genuine blob.
  EXPECT_FALSE(VerifyServerIdentity(parts->signed_bytes, parts->signature,
                                    kDevRootKeyDer, "evil.example",
                                    base::Time::FromTimeT(1750000000)));
}

}  // namespace
}  // namespace teleport
```

> `DIR_SRC_TEST_DATA_ROOT` 的路径前缀以检出实际为准(overlay 在 `teleport/src/...`);若 PathService 前缀不符,用 `gn` 的 test data 声明或调整路径。fixture 也需在 `test("teleport_unittests")` 里作为 `data` 声明,确保测试运行时可达。

在 `src/BUILD.gn` 的 `test("teleport_unittests")` 加该 unittest 源,并加:
```gn
  data = [ "common/test_data/server_identity_dev_fixture.bin" ]
```

- [ ] **Step 4: 构建 + 跑联合测试**

```bash
export TELEPORT_CHROMIUM_DIR=/Users/liulichao/workspace/teleport/chromium
cd "$TELEPORT_CHROMIUM_DIR/src"
gn gen out/mac/arm64/dev --args='import("//teleport/gn/args/dev.mac.gn")'
autoninja -C out/mac/arm64/dev teleport_unittests
out/mac/arm64/dev/teleport_unittests --gtest_filter='TeleportServerIdentityJointTest.*'
```
Expected:`VerifiesFairylandMintedDevBlob` PASS(真实 fairyland blob 经客户端验签通过;错域仍拒)。这是跨仓兼容的实证。

- [ ] **Step 5: 全量回归 + Commit**

```bash
out/mac/arm64/dev/teleport_unittests   # full suite green
cd /Users/liulichao/workspace/teleport/.claude/worktrees/deployment-domain-config
git add src/common/test_data/server_identity_dev_fixture.bin \
        src/common/teleport_server_identity_joint_unittest.cc src/BUILD.gn
git commit -m "test(server-identity): joint cross-repo round-trip (fairyland-minted dev blob verifies)"
```

---

## Self-Review(计划对照 spec / 客户端 spec §4.1）

- 根签名 typed proto 验证(准源 §4.1 / D14)→ Task 2;域名绑定 + 过期(D15）→ Task 2 的 domain/not_after 校验;`message_type` 域分离 → Task 2 校 `kExpectedMessageType`;外层容器格式 → Task 2 `ParseServerIdentityContainer`(与 fairyland 逐字一致);根密钥注入(不引 //components/policy)→ Task 2 target 结构;跨仓 wire+签名兼容 → Task 3 联合测试。
- **依赖环红线**:验证库/proto 独立于 leaf(Task 1/2 的 BUILD.gn target 分离);根密钥注入而非库内取。
- **不在本计划(Phase 2b/2c)**:Local State 自认证条目 + resolver 第 4 级接线、connect 页 + 深链接 + 确认 UX、fetch(SimpleURLLoader)、gate 精确白名单 + 动态 OP-host 注入、§4.5 迁移接线、私有化交付规范。
- 占位符扫描:proto 生成头 include 路径、`crypto` 签名 API 细节、`DIR_SRC_TEST_DATA_ROOT` 前缀三处标「以检出实际为准」——因 M148 proto_library/crypto/PathService 的确切形态需 `gn gen`/编译期确认,均给出确认方式而非臆断;`kDevRootKeyDer` 由 Step 2 命令实测填入。

## 合并纪律

与 fairyland 仓 Phase 2a 联合 e2e(Task 3 的往返 + fairyland 起栈 serve blob)通过后,双仓 rebase+squash+ff 背靠背合并;单侧先行合并禁止。
