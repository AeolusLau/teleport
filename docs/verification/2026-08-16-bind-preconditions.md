# bind 前置条件的可用唤醒信号 —— 验证结论

- 任务:A 组客户端计划 Task 7 Step 1(承重验证步)。
- 上游基线:`CHROMIUM_VERSION = 151.0.7922.76`,检出 `/Users/liulichao/workspace/chromium/151.0.7922/src`(下称 `$CR`)。
- 本仓 overlay:`/Users/liulichao/workspace/teleport/.worktrees/tunnel-webapp-compat/src`(下称 `$TP`;与 `main` 上同名文件逐字节一致,已 diff 核对)。
- 本文所有 `file:line` 均为**上述两棵树的当前内容**;文档注释一律逐字全抄,不做省略。

---

## 0. 先说推翻了什么(读结论前必须看)

### 0.1 【推翻代码注释】`teleport_oidc_inplace_registrar.cc` 声称的「已有设备证书」是**假的**

`$TP/browser/enterprise/teleport_oidc_inplace_registrar.cc:343-347`:

```cpp
    // Trigger orchestration (Task T5): the profile is now a signed-in managed
    // profile with a provisioned device certificate and a fetched managed
    // policy -- exactly the precondition TeleportTunnelService::Start()
    // documents. Establish the access tunnel before reporting success.
    MaybeStartTunnelService();
```

这条注释断言「此刻设备证书已供给完毕(provisioned)」。**源码不支持这个断言**:

1. 该行运行在**策略 FETCH 成功**的回调里,而证书供给要等策略先落到 pref。供给的唯一启动点是 `CertificateProvisioningServiceImpl::OnPolicyUpdated()`,它由 `policy_pref()` 的 pref 变更触发(`$CR/components/enterprise/client_certificates/core/certificate_provisioning_service.cc:165-172`、`:236-248`)。
2. 供给启动后还有**至少一次自有的网络往返**:`upload_client_->CreateCertificate(...)`(同文件 `:305-311`、`:396-402`),再 `CommitIdentity` 落库(`:456-461`),才在 `OnCertificateCommitted` 里 `cached_identity_.emplace(...)`(`:482-483`)。
3. 因此 `MaybeStartTunnelService()` 所在时刻**严格早于**证书可用。同名注释在 `$TP/browser/enterprise/teleport_tunnel_service.h:67-70`(`Start()` 的「called once ... the device certificate is present」)同样不成立。

**影响**:这正是 spec §3.2 所说的「第二个异步前置条件」。它不是理论风险,而是当前代码里被一条错误注释掩盖的既有竞态。修 Task 7 时应顺手改掉这两处注释(注释即契约,留着会让下一个人重犯)。

### 0.2 【推翻 plan 的命令】Step 1 里的工厂路径不存在

计划 `docs/superpowers/plans/2026-08-16-tunnel-webapp-compat-group-a-client.md:829` 写的是:

```
sed -n '50,80p' "$CR/components/enterprise/client_certificates/core/certificate_provisioning_service_factory.cc"
```

该文件**不存在**(已 `ls` 确认)。真实路径是 `$CR/chrome/browser/enterprise/client_certificates/certificate_provisioning_service_factory.cc`(另有 iOS 版 `$CR/ios/chrome/browser/enterprise/client_certificates/certificate_provisioning_service_factory_ios.mm`)。因为 Step 1 的命令块没有 `set -e`,照抄执行只会打一行 `sed: No such file`,然后**静默跳过**这条最关键的证据 —— 与「上一轮把注释截断」是同一类失败模式。本文按真实路径重新取证。

### 0.3 【确认 spec 判断正确,并给出完整证据】

spec `docs/superpowers/specs/2026-08-15-tunnel-webapp-compat-group-a-design.md:104-106` 的两条自我否定(「`PrefChangeRegistrar` 不对初始值触发」「`GetManagedIdentity` 是 request/response 不是 observer,策略未启用时同步跑 `std::nullopt` 且此后不再触发」)**逐字属实**,证据见 §1、§2。本文不推翻 spec,而是把它补成可执行的判据,并追加三项 spec 未覆盖的发现:**回调重入不安全(§3)**、**单测里服务恒为 nullptr(§4)**、**`net::CertDatabase` 通道在本产品彻底无效(§6.5)**。

---

## 1. `PrefChangeRegistrar::Add` 是否对**注册时已存在的值**触发?

**结论:不触发。注册只挂观察者,不回放当前值。所以读值门(read-gate)不可省。**

三个 `Add` 重载全部汇流到同一个实现,`$CR/components/prefs/pref_change_registrar.cc:48-67`:

```cpp
void PrefChangeRegistrar::Add(std::string_view path,
                              base::RepeatingClosure obs) {
  Add(path, base::IgnoreArgs<std::string_view>(std::move(obs)));      // :50
}

void PrefChangeRegistrar::Add(std::string_view path, NamedChangeCallback obs) {
  Add(path, base::BindRepeating(&CopyStringView).Then(std::move(obs)));  // :54
}

void PrefChangeRegistrar::Add(std::string_view path,
                              NamedChangeAsViewCallback obs) {
  if (!service_) {
    NOTREACHED();
  }
  DCHECK(!IsObserved(path))
      << "Already had pref, \"" << path << "\", registered.";

  service_->AddPrefObserver(path, this);          // :65
  observers_.insert_or_assign(path, std::move(obs));  // :66
}
```

`:65` + `:66` 是这个函数的全部副作用:登记 + 存回调。**没有任何一处 `Run(...)`**。

继续往下追,确认登记路径也不回放:

- `$CR/components/prefs/pref_service.cc:317-319` — `PrefService::AddPrefObserver` 直接转发 `pref_notifier_->AddPrefObserver(path, obs)`。
- `$CR/components/prefs/pref_notifier_impl.cc:31-39` — `PrefNotifierImpl::AddPrefObserver` 的函数体只有 `pref_observers_[std::string(path)].AddObserver(obs);`(`:38`)。

回调**唯一**的触发入口是变更通知:

- `$CR/components/prefs/pref_notifier_impl.cc:73-78` — `OnPreferenceChanged(path)` → `FireObservers(path)`;
- `$CR/components/prefs/pref_notifier_impl.cc:93-111` — `FireObservers` 遍历 `pref_observers_[path]` 调 `observer.OnPreferenceChanged(pref_service_, path)`;
- `$CR/components/prefs/pref_change_registrar.cc:104-109` — registrar 侧收到后才 `iter->second.Run(pref)`。

**对本任务的判据**:

- `TeleportTunnelService` 是**懒创建**的(见 §8),其构造函数在 `ProfileNetworkContextService::ConfigureNetworkContextParamsInternal` 里被拉起 —— 这个时刻**可能晚于**策略 pref 已经落好。此时 `Add` 不回放 ⇒ 只挂通知会永远等不到。今天的代码正是靠 `MaybeAutoStartFromPrefs()` 里的**读值**补上这一刀(`$TP/browser/enterprise/teleport_tunnel_service.cc:147`、`:159`)。
- 因此 **Task 7 新增任何唤醒源,都必须成对提供「读值门 + 变更通知」**,不得只加通知。这一条对 §6 列出的每一个候选信号一律适用。

**补充(顺手取到、后面会用到的一条强性质)**:同一次策略刷新里改变的**多个** pref,是在**整张 `PrefValueMap` 换好之后**才逐个发通知的 —— `$CR/components/policy/core/browser/configuration_policy_pref_store.cc:119-130`:

```cpp
void ConfigurationPolicyPrefStore::Refresh() {
  std::unique_ptr<PrefValueMap> new_prefs = CreatePreferencesFromPolicies();
  std::vector<std::string> changed_prefs;
  new_prefs->GetDifferingKeys(prefs_.get(), &changed_prefs);
  prefs_.swap(new_prefs);                       // :123  <-- 先整体换入

  // Send out change notifications.
  for (const auto& pref : changed_prefs) {      // :126  <-- 再逐个通知
    for (auto& observer : observers_)
      observer.OnPrefValueChanged(pref);
  }
}
```

⇒ 在**任一**策略 pref 的观察者回调里,`PrefService::Get*()` 读**同批次其他**策略 pref 已经是新值。这让「在 A 的回调里读 B 做门控」是安全的,不需要担心半更新状态。

---

## 2. `CertificateProvisioningService::GetManagedIdentity` 的完整文档注释与实现语义

### 2.1 完整文档注释(逐字全抄,共 4 行 / 3 句,一字不删)

`$CR/components/enterprise/client_certificates/core/certificate_provisioning_service.h:62-66`:

```cpp
  // Will invoke `callback` with the managed identity once it has been
  // successfully loaded and the policies for its usage are enabled as well.
  // Otherwise, run it with std::nullopt. If the identity failed to load for
  // some reason, subsequent calls will retry loading it.
  virtual void GetManagedIdentity(GetManagedIdentityCallback callback) = 0;
```

三句话拆开看,**语义反转正好发生在第一句和第二句之间**:

| # | 原句 | 语义 |
|---|---|---|
| 1 | "Will invoke `callback` with the managed identity once it has been successfully loaded and the policies for its usage are enabled as well." | 读起来像「会等到就绪再回调」—— **上一轮的截断点就在这句末尾** |
| 2 | "Otherwise, run it with `std::nullopt`." | **反转**:不就绪就**立刻**用 `std::nullopt` 跑掉,不等 |
| 3 | "If the identity failed to load for some reason, subsequent calls will retry loading it." | 重试靠**后续调用**(caller 主动再问),**不是**服务事后回头补一次 |

即:这是 **request/response**,不是 observer;`once` 是「一旦(在本次调用里)已经就绪」,不是「等到将来某刻就绪」。

顺带抄全同一个头文件里另外三个方法的注释,避免下一轮又在别处截断:

`:71-74`(`DeleteManagedIdentities`):
```cpp
  // Deletes the managed identities (permanent and temporary). `callback` will
  // be invoked with true if the identities were deleted successfully, and false
  // otherwise. In case of an unexpected failure, the identities might still
  // exist in the store but not be usable anymore currently we just log an
  // error.
```
`:76-77`(`GetCurrentStatus`):
```cpp
  // Returns metadata about the current status of the service, mainly for
  // debugging purposes.
```
`:80-81`(`GetLoggingContext`):
```cpp
  // Returns the logging context for the current service (e.g., "Browser" or
  // "Profile").
```

注意 `GetCurrentStatus` 的注释明写 **"mainly for debugging purposes"** —— 把它当生产判据是逆着上游意图用,见 §6.4。

### 2.2 实现:策略未启用时发生什么?

`$CR/components/enterprise/client_certificates/core/certificate_provisioning_service.cc:177-196`(函数全文):

```cpp
void CertificateProvisioningServiceImpl::GetManagedIdentity(
    GetManagedIdentityCallback callback) {
  if (!IsPolicyEnabled()) {
    std::move(callback).Run(std::nullopt);     // :180   <-- 同步、就地、立刻
    return;                                    // :181
  }

  if (!IsProvisioning() && cached_identity_ && cached_identity_->is_valid() &&
      !IsCertExpiringSoon(*cached_identity_->certificate)) {
    // A valid identity is already cached, just return it.
    std::move(callback).Run(cached_identity_);  // :187  <-- 同步、就地、立刻
    return;
  }

  pending_callbacks_.push_back(std::move(callback));   // :191

  if (!IsProvisioning()) {
    OnPolicyUpdated();                                  // :194
  }
}
```

`IsPolicyEnabled()` 的定义,`:227-230`:

```cpp
bool CertificateProvisioningServiceImpl::IsPolicyEnabled() const {
  return pref_service_->IsManagedPreference(policy_pref()) &&
         pref_service_->GetInteger(policy_pref()) == 1;
}
```

**逐条回答任务提出的三个子问:**

1. **策略未启用时行为如何?** `:179-182` 命中,`callback` 被**同步**地用 `std::nullopt` 跑掉,函数返回。**回调不入队**(`pending_callbacks_` 完全没被碰),**不启动供给**(`OnPolicyUpdated()` 在 `:194`,处于已被 `return` 跳过的分支之后)。
2. **回调是否同步跑?** **是,而且有两条同步路径**:`:180`(策略未启用 → `nullopt`)与 `:187`(已缓存有效且不临期 → 直接给值)。二者都在 `GetManagedIdentity` 的调用栈内完成。
   - 第三条路径(`:191` 入队)通常异步,但**也不保证异步**:`:194` 的 `OnPolicyUpdated()` → `certificate_store_->GetIdentity(...)`(`:242-246`),而 store 的实现是允许同步回调的 —— `$CR/components/enterprise/client_certificates/core/prefs_certificate_store.cc:157-162` 在「库里没有该 identity」时就是同步 `std::move(callback).Run(std::nullopt);`。所以调用方**必须同时容忍同步与异步**两种回调时序(不能在 `GetManagedIdentity` 之后才初始化回调依赖的状态)。
3. **此后还会再触发吗?** **不会。** `GetManagedIdentityCallback` 是 `base::OnceCallback`(`:28-29`),`:180` / `:187` 用掉后即销毁;`:191` 入队的那份也只会在 `OnFinishedProvisioning` 里被消费一次(`:537-540`)。服务**没有**任何「稍后回头补一次」的机制。上游自己的用法就是**每次需要时重新问一遍**:`$CR/components/enterprise/client_certificates/core/client_certificates_service.cc:104-125` 里 `GetClientCerts` 每一次被网络栈调用都重新 `GetManagedIdentity(...)` 一次。

**结论:`GetManagedIdentity` 不能当唤醒信号。** 它恰好在它本该解决的那个窗口(策略刚下发、供给尚未完成、`IsPolicyEnabled()` 还是 false)里同步返回 `nullopt` 且此后永不再响 —— 这与 spec §3.2 第 106 行的判断完全一致。

---

## 3. 回调能否**重入**(在回调里再调 `GetManagedIdentity` 安全吗)?

**结论:不安全。排空 `pending_callbacks_` 的写法存在两个独立缺陷,重入会踩其中之一。**

`$CR/components/enterprise/client_certificates/core/certificate_provisioning_service.cc:523-541`(函数全文):

```cpp
void CertificateProvisioningServiceImpl::OnFinishedProvisioning(bool success) {
  LogProvisioningContext(GetLoggingContext(), provisioning_context_.value(),
                         success);
  provisioning_context_.reset();          // :526  <-- 此后 IsProvisioning()==false

  std::optional<ClientIdentity> identity =
      cached_identity_ && cached_identity_->is_valid() ? cached_identity_
                                                       : std::nullopt;

  LOG_POLICY(INFO, DEVICE_TRUST)
      << "Managed identity provisioning finished."
      << (identity.has_value() ? " A cached identity is available."
                               : " No cached identity is available.");

  for (auto& pending_callback : pending_callbacks_) {   // :537 range-for 直接遍历成员
    std::move(pending_callback).Run(identity);          // :538 在遍历中运行用户代码
  }
  pending_callbacks_.clear();                            // :540 遍历后无条件清空
}
```

容器声明:`:129-130`

```cpp
  // Callbacks waiting for an identity to be available.
  std::vector<GetManagedIdentityCallback> pending_callbacks_;
```

**重入分析** —— 站在 `:538` 里的用户回调中再调 `GetManagedIdentity(cb2)`,会落到 §2.2 的三条分支之一:

| 分支 | 条件 | 后果 |
|---|---|---|
| A `:180` | `IsPolicyEnabled()` 为 false | 同步 `nullopt`,不碰容器。**安全** |
| B `:187` | 有有效且不临期的缓存(注意 `:526` 已把 `IsProvisioning()` 置 false,该条件可满足) | 同步给值,不碰容器。**安全** |
| C `:191` | 策略开着但**没有可用身份**(供给刚失败 / 证书临期)—— **恰恰就是调用方想重试的那种情形** | `pending_callbacks_.push_back(...)`,**在 range-for 遍历自身期间修改被遍历的 vector** |

分支 C 的两个独立缺陷:

1. **迭代器失效 / UAF**:`std::vector::push_back` 若触发扩容,`:537` 的 range-for 在循环开始时取的 `begin()/end()` 全部失效,后续迭代是未定义行为(实测形态通常是堆内存 use-after-free)。是否扩容取决于当时的 `capacity()`,即**这是一个概率性崩溃,不是确定性崩溃** —— 最坏的一类 bug。
2. **静默丢回调**:即便侥幸没扩容,`:540` 的 `pending_callbacks_.clear()` 在循环结束后**无条件**执行,会把刚刚重入排入的 `cb2` 一并丢掉。`cb2` **永远不会被调用**,调用方就此挂死等待一个永不到来的回调,且没有任何日志或 CHECK。

补充:分支 C 里 `:193-195` 还会再调一次 `OnPolicyUpdated()`,而 store 允许同步回调(§2.2 第 2 点),理论上可以让 `OnFinishedProvisioning` **嵌套重入自身**,叠加一次嵌套排空 + 二次 `clear()`。

**判据**:Task 7 若最终要碰 `GetManagedIdentity`(本文不建议,见 §7),**绝不可在其回调内同步再调它**;必须 `PostTask` 跳出调用栈。上游自身的用法(`client_certificates_service.cc:104-125`)也从不在回调内重入,因此这个坑目前在上游没有暴露 —— 不能指望它被上游修掉。

---

## 4. 单测里能拿到这个服务吗?

**结论:拿不到。默认恒为 `nullptr`;只有显式 `SetTestingFactory` 注入 mock 才能拿到实例。**

工厂,`$CR/chrome/browser/enterprise/client_certificates/certificate_provisioning_service_factory.cc:59-76`:

```cpp
CertificateProvisioningServiceFactory::CertificateProvisioningServiceFactory()
    : ProfileKeyedServiceFactory("CertificateProvisioningService",
                                 ProfileSelections::BuildForRegularProfile()) {  // :61
  DependsOn(CertificateStoreFactory::GetInstance());                             // :62
  DependsOn(enterprise::ProfileIdServiceFactory::GetInstance());                 // :63
}

bool CertificateProvisioningServiceFactory::ServiceIsCreatedWithBrowserContext()
    const {
  return true;                        // :71
}

bool CertificateProvisioningServiceFactory::ServiceIsNULLWhileTesting() const {
  return true;                        // :75   <-- 关键
}
```

`ServiceIsNULLWhileTesting` 的语义,`$CR/components/keyed_service/core/keyed_service_base_factory.h:94`(注释在 `:92-93`):

```cpp
  // By default, testing contexts will be treated like normal contexts. If this
  // method is overridden to return true, then the service associated with the
  // testing context will be null.
  virtual bool ServiceIsNULLWhileTesting() const;
```

生效点,`$CR/components/keyed_service/core/keyed_service_templated_factory.cc:141-148`:

```cpp
    info.stage = MappingStage::kServiceAssociated;
    if (info.testing_factory) {
      info.service = std::move(info.testing_factory).Run(context);   // :143 优先级最高
    } else if (info.is_testing_context && ServiceIsNULLWhileTesting()) {
      // Do not create the service if the context is a testing context and
      // the factory is configured to not create the service in that case.
    } else {
      info.service = BuildServiceInstanceFor(context);
    }
```

`is_testing_context` 的来源(`TestingProfile` 恒为 true):

- `$CR/chrome/test/base/testing_profile.cc:496` — `browser_context_dependency_manager_->CreateBrowserContextServicesForTest(...)`;
- `$CR/components/keyed_service/content/browser_context_dependency_manager.cc:24-27` — `CreateBrowserContextServicesForTest` → `DoCreateBrowserContextServices(context, true)`;
- `$CR/components/keyed_service/core/keyed_service_templated_factory.cc:195-199` — 该 `true` 存进 `iterator->second.is_testing_context`。

现有隧道单测用的正是 `TestingProfile`(`$TP/browser/enterprise/teleport_tunnel_service_unittest.cc:61`)。

**判据(直接决定 Task 7 Step 2 的三个新用例能不能跑绿):**

- 实现里任何 `CertificateProvisioningServiceFactory::GetForProfile(profile)` 在单测中**返回 `nullptr`**,必须显式判空;否则新用例一律解引用空指针崩溃。
- 若确需在测试里给出实例:上游备好了 `MockCertificateProvisioningService`(`$CR/components/enterprise/client_certificates/core/mock_certificate_provisioning_service.h:18-34`,四个方法全 `MOCK_METHOD`),位于 `testonly` 目标 `//components/enterprise/client_certificates/core:test_support`(`$CR/components/enterprise/client_certificates/core/BUILD.gn:182-188`),经 `SetTestingFactory` 注入即可(`keyed_service_templated_factory.cc:143` 的 `testing_factory` 优先级高于 `ServiceIsNULLWhileTesting`)。代价是 `unit_tests` 需新增该 testonly 依赖。
- **推荐**:§7 的方案不依赖这个服务,从而**不需要**新增依赖、不需要判空样板、也不需要 mock。

另注:`ServiceIsCreatedWithBrowserContext()==true`(`:71`)意味着**生产环境**下该服务随 Profile 创建即建、pref 观察者早早挂上 —— 这一点在 §6.2 里有用。

---

## 5. 消费方是否需要 `DependsOn` 以避免关停顺序问题?

**结论:需要。上游同类消费方已经这么做,是既定范式。**

上游先例,`$CR/chrome/browser/net/profile_network_context_service_factory.cc:82-84`:

```cpp
#if BUILDFLAG(IS_WIN) || BUILDFLAG(IS_MAC) || BUILDFLAG(IS_LINUX)
  DependsOn(client_certificates::CertificateProvisioningServiceFactory::
                GetInstance());
#endif
```

`ProfileNetworkContextService` 在 `$CR/chrome/browser/net/profile_network_context_service.cc:330-332` 处持有该服务指针(`GetWrappedCertStore`),所以工厂声明了依赖。

`CertificateProvisioningService` 是 `KeyedService`(`$CR/components/enterprise/client_certificates/core/certificate_provisioning_service.h:26` — `class CertificateProvisioningService : public KeyedService`)。KeyedService 的关停按依赖图逆序执行,**没有 `DependsOn` 就没有顺序保证**:被依赖者可能先 `Shutdown()`/析构,消费方随后持有悬垂指针。

**本仓现状(缺口)**:`$TP/browser/enterprise/teleport_tunnel_service_factory.cc:13-18` 的构造函数**一条 `DependsOn` 都没有**:

```cpp
TeleportTunnelServiceFactory::TeleportTunnelServiceFactory()
    : ProfileKeyedServiceFactory(
          "TeleportTunnelService",
          ProfileSelections::Builder()
              .WithRegular(ProfileSelection::kOriginalOnly)
              .Build()) {}
```

**Profile 选择兼容性**:两个工厂对常规 profile 的选择一致 —— `ProfileSelections::BuildForRegularProfile()` 未覆写 `WithRegular`,而 Builder 的默认值就是 `kOriginalOnly`(`$CR/chrome/browser/profiles/profile_selections.h:145`:`ProfileSelection regular_profile_selection_ = ProfileSelection::kOriginalOnly;`;`$CR/chrome/browser/profiles/profile_selections.cc:80-86` 只关掉 guest/system/ash-internals)。所以真要加 `DependsOn`,不存在「依赖方存在而被依赖方在该 profile 上不存在」的错配。

**判据**:采纳 §7 方案则**不需要**加这条 `DependsOn`(不持有该服务);若后续改为持有,则**必须**同时加 `DependsOn` 与判空。

---

## 6. 还有哪些**可观测信号**能表示「设备证书现在可用了」?

先给整体结论:**不存在一个真正表示「证书已就绪」的观测信号**。下面逐个列出候选与其真实触发语义。

### 6.1 供给策略 pref —— 到底是哪一个?

- 常量定义:`$CR/components/enterprise/client_certificates/core/prefs.cc:13-16`

  ```cpp
  const char kProvisionManagedClientCertificateForUserPrefs[] =
      "client_certificates.provision_for_user.value";
  const char kProvisionManagedClientCertificateForBrowserPrefs[] =
      "client_certificates.provision_for_browser.value";
  ```

- profile 作用域选哪一个:`$CR/chrome/browser/enterprise/client_certificates/profile_context_delegate.cc:43-45`

  ```cpp
  std::string ProfileContextDelegate::GetPolicyPref() {
    return prefs::kProvisionManagedClientCertificateForUserPrefs;
  }
  ```

  服务通过 `policy_pref()`(`certificate_provisioning_service.cc:117-119`)取到它,并在构造时观察之(`:165-168`)。

- 注册形态:`$CR/components/enterprise/client_certificates/core/prefs.cc:19-22` —— `RegisterIntegerPref(..., /*default_value=*/0)`,**profile pref、整型**。
- 判定式:`IsManagedPreference(pref) && GetInteger(pref) == 1`(`certificate_provisioning_service.cc:227-230`)—— 注意**必须是 managed 层**,用户层写入不算数。
- 策略映射:`$CR/chrome/browser/policy/configuration_policy_handler_list_factory.cc:2505-2507`

  ```cpp
    { key::kProvisionManagedClientCertificateForUser,
      client_certificates::prefs::kProvisionManagedClientCertificateForUserPrefs,
      base::Value::Type::INTEGER },
  ```

  是 simple-map 直通项(无自定义 handler)。

**触发语义**:`PrefChangeRegistrar` 观察它 ⇒ **仅在值变化时**触发(§1),语义是「**供给策略刚打开 / 刚变化**」。此刻供给才**开始**(`OnPolicyUpdated` → `GetIdentity` → 可能 `CreatePrivateKey` → `CreateCertificate` 网络往返 → `CommitIdentity`),证书**尚不可用**。

**陷阱 A(致命,决定了它的实际价值)**:服务端把它与 `AutoSelectCertificateForUrls` 放在**同一批用户策略**里下发 —— `../fairyland/products/teleport/device-manager/internal/policy/settings_pipeline_test.go:58-62`、`.../internal/repo/webapp_repo_test.go:157-162` 断言二者同时出现在 user-scope 编译产物中。结合 §1 补充的 `configuration_policy_pref_store.cc:119-130`(整张 map 先换后逐个通知),两个 pref 的观察者**在同一个 task 内先后触发**。⇒ 在冷启动这一主场景里,它比现有的 AutoSelect 观察者**几乎不提供任何新的时间信息**。它的增量价值仅限于「管理员事后单独改供给策略而不动 AutoSelect」这类分批下发场景。

**陷阱 B**:它是「策略开了」不是「证书好了」。把它当作「可以 bind 了」会稳定地**过早**唤醒一次,该次 bind 大概率仍失败。这不致命(有退避兜底),但必须在设计里承认,不能记成「就绪信号」。

### 6.2 供给服务自身的 observer 接口

**不存在。** `$CR/components/enterprise/client_certificates/core/certificate_provisioning_service.h` 全文只有四个虚函数(`:66` `GetManagedIdentity`、`:73-74` `DeleteManagedIdentities`、`:78` `GetCurrentStatus`、`:82` `GetLoggingContext`)与一个 `Status` 结构(`:33-52`)。已 grep 确认 `certificate_provisioning_service.h` / `certificate_store.h` / `client_certificates_service.h` / `leveldb_certificate_store.h` / `prefs_certificate_store.h` **五个头文件里 `Observer` / `AddObserver` / `ObserverList` 零命中**。

唯一沾边的是 `ContextDelegate::OnClientCertificateDeleted`(`$CR/components/enterprise/client_certificates/core/context_delegate.h:23-25`),但:(a) 它是**删除**通知不是**新增**通知;(b) 它是服务**持有**的 delegate(构造时以 `std::unique_ptr` 注入,`certificate_provisioning_service.h:56-60`),不是可外挂的观察者列表 —— 只有工厂里那一个实现方 `ProfileContextDelegate`(`certificate_provisioning_service_factory.cc:104`),外部无法追加。

### 6.3 证书存储(certificate store)本身

**不可观测,且在本产品里也不在 prefs 里。**

profile 用哪个 store 由一个 feature 开关决定,`$CR/chrome/browser/enterprise/client_certificates/certificate_store_factory.cc:60-73`:

```cpp
  if (features::IsManagedUserClientCertificateInPrefsEnabled()) {
    return std::make_unique<PrefsCertificateStore>(profile->GetPrefs(),
                                                   CreatePrivateKeyFactory());
  }
  ...
  return LevelDbCertificateStore::Create(
      profile->GetPath(),
      profile->GetDefaultStoragePartition()->GetProtoDatabaseProvider(),
      CreatePrivateKeyFactory());
```

而该开关**默认关闭**:`$CR/components/enterprise/client_certificates/core/features.cc:26-27`

```cpp
BASE_FEATURE(kManagedUserClientCertificateInPrefs,
             base::FEATURE_DISABLED_BY_DEFAULT);
```

在本产品里这是**确定性**的,不是概率性的:`disable_fieldtrial_testing_config = true`(`$TP/gn/args/dev.mac.gn:52`、`$TP/gn/args/release.mac.gn:52`)把每个 `base::Feature` 钉死在编译期默认值。

⇒ 身份落在 **LevelDB**,不是 prefs。`RegisterProfilePrefs` 里那两个字典 pref(`$CR/components/enterprise/client_certificates/core/prefs.cc:23-24`,`kManagedProfileIdentityName` / `kTemporaryManagedProfileIdentityName`)在我们的构建里**没有写入方**,观察它们等于观察一个恒定不变的空字典。**这是一条看着最诱人、实则完全无效的路** —— 若不查 feature 默认值,极易误判为「证书落地就有 pref 变更可观察」。

### 6.4 `GetCurrentStatus()` 轮询

`$CR/components/enterprise/client_certificates/core/certificate_provisioning_service.h:33-52` 的 `Status` 暴露 `is_provisioning` / `is_policy_enabled` / `identity` / `last_upload_code`,实现见 `.cc:213-221`。

**触发语义**:**没有触发,这是纯拉取**。头文件注释自陈 "mainly for debugging purposes"(`:76-77`)。上游的现役用法也确实只有诊断页:`$CR/chrome/browser/ui/webui/connectors_internals/connectors_internals_page_handler.cc:149`。

**可用性**:可作为**读值门的精化**(例如诊断页展示 `is_provisioning`),但**不能**当唤醒源;且同样受 §4(单测恒 nullptr)与 §5(需 `DependsOn`)两条约束。

### 6.5 `net::CertDatabase::Observer::OnClientCertStoreChanged` —— 看似正解,实则无效

接口本身确实存在且看起来正合用,`$CR/net/cert/cert_database.h:44-47`:

```cpp
    // Called when a potential change to client certificates is detected. (Some
    // platforms don't provide precise notifications and this may be notified
    // on unrelated changes.)
    virtual void OnClientCertStoreChanged() {}
```

**但企业证书供给链路从不触发它。** 全树 grep `NotifyObserversClientCertStoreChanged` 的调用方只有:NSS(`$CR/net/cert/nss_cert_database.cc:70,196,245,255,347,454`)、macOS Keychain 事件(`$CR/net/cert/cert_database_mac.cc:73`)、Android(`$CR/net/cert/x509_util_android.cc:21`)、ChromeOS kcer(`$CR/chromeos/ash/components/kcer/kcer_token_impl.cc:2466`),其余全是测试。`components/enterprise/client_certificates/**` **零命中**。

macOS 上唯一的触发源是 Keychain 变更回调,且它还会**主动忽略本进程产生的事件**(`$CR/net/cert/cert_database_mac.cc:62-65`:`if (info->pid == base::GetCurrentProcId()) { ... return errSecSuccess; }`)。而我们的托管身份落在 LevelDB(§6.3),压根不进 Keychain。

**结论:在 macOS + 企业供给这条链路上,该 observer 永远不会因为「设备证书就绪」而触发。** 这条必须写死在文档里 —— 它是本轮最容易被误采纳的候选。

### 6.6 纳管标记 pref `kPolicyRecoveryToken` —— **今天只读不观察,是一个真实的漏信号**

- 定义:`$CR/chrome/browser/enterprise/signin/enterprise_signin_prefs.h:33`,注册于 `$CR/chrome/browser/enterprise/signin/enterprise_signin_prefs.cc:19`(`RegisterStringPref(prefs::kPolicyRecoveryToken, std::string())`)—— 普通 profile 字符串 pref,随 profile prefs 同步加载。
- 写入方(本仓):`$TP/browser/enterprise/teleport_oidc_inplace_registrar.cc:175-177`,在 `ApplyManagedAttributes()` 里落 DM token。
- 读取方(本仓):`$TP/browser/enterprise/teleport_tunnel_service.cc:159-162` —— **只读,没有任何观察者**。

**触发语义(若加上观察)**:值从空变非空 = 「本 profile 完成纳管」。

**今天的漏信号(实打实的缺口)**:`MaybeAutoStartFromPrefs()` 同时门控在 AutoSelect 与 `kPolicyRecoveryToken` 两个 pref 上,但**只观察前者**。若 AutoSelect 先落、DM token 后写,则:AutoSelect 的通知触发 → `MaybeAutoStartFromPrefs()` 在 `:159-162` 早退 → 此后 **DM token 写入不产生任何通知** → 除非 AutoSelect 再变一次,否则**本次会话永远不会 `Start()`**。补上这个观察者是**低成本、纯增量、无外部依赖**的修复。

### 6.7 bind 本身(唯一的真探针)—— 并且重试不会被缓存污染

由于没有真正的「证书就绪」信号,**唯一权威的判定就是发起一次 bind 看它成不成**。这使得「失败 → 退避 → 重试」是承重结构,唤醒信号只负责**短路退避**。

失败形态(证实 spec §3.2 的竞态描述):

- 恰好一张 matching 证书 → 自动选中,不弹框:`$CR/chrome/browser/chrome_content_browser_client.cc:4372-4390`;
- 零张 matching + **无 WebContents**(浏览器进程 `SimpleURLLoader` 正是此情形)→ 早退且**完全不碰 `delegate`**:`if (!web_contents) { ... }` 整块为 `:4400-4435`,末尾注释 + 早退在 `:4432-4434`

  ```cpp
    // Return without calling anything on `delegate`. This results in the
    // `delegate` being deleted, which implicitly calls to cancel the request.
  ```

**一条重要的正面结论(决定退避重试是否真的能自愈)**:上述取消路径**不会**在 `SSLClientAuthCache` 里留下「对该 host 不发证书」的偏好,因此**重试是干净的,不会被首次失败毒化**。链路:

- 取消走 `$CR/services/network/url_loader.cc:1993-1996` 的 `URLLoader::CancelRequest()` → `url_request_->CancelWithError(net::ERR_SSL_CLIENT_AUTH_CERT_NEEDED)` —— 未触碰任何缓存;
- 缓存写入的**唯一**入口是 `$CR/net/http/http_network_transaction.cc:501-505` 的 `RestartWithCertificate` 里 `ssl_client_context()->SetClientCertificate(...)`,而它只在 `ContinueWithCertificate` 被调用后才可达(`$CR/services/network/url_loader.cc:1976-1991`);
- 而 `$CR/chrome/browser/chrome_content_browser_client.cc:4437-4445` 那条会写入「无证书」偏好的分支(`delegate->ContinueWithCertificate(nullptr, nullptr);` 在 `:4443`)位于 `:4400` 的 `if (!web_contents)` 早退**之后**,对我们的 bind **不可达**。
- 缓存语义参见 `$CR/net/ssl/ssl_client_auth_cache.h:31-33`:"The desired certificate may be NULL, which indicates a preference to not send any certificate to |server|."

⇒ 若哪天 bind 改为带 WebContents 发起,这条豁免就没了,首次失败会把 host 钉成「永不发证书」直到缓存被清 —— 属于必须留档的边界条件。

---

## 7. `BeginBind()` 今天有 in-flight 守卫吗?在途的 `SimpleURLLoader` 被新赋值会怎样?

**结论:没有守卫。新赋值会静默取消在途请求,且该请求的回调永不执行 —— 状态机会整段丢失这次尝试。**

`$TP/browser/enterprise/teleport_tunnel_service.cc:261-309` 是 `BeginBind()` 全文;函数**第一行就是 annotation 定义**(`:273`),**不存在任何 `if (loader_) return;` 之类的前置检查**。关键两行:

```cpp
  loader_ = network::SimpleURLLoader::Create(std::move(request), annotation);  // :301
  loader_->SetTimeoutDuration(base::Seconds(30));                              // :302
  loader_->AttachStringForUpload("{}", "application/json");                    // :303
  loader_->DownloadToString(                                                   // :304
      GetUrlLoaderFactory().get(),
      base::BindOnce(&TeleportTunnelService::OnTunnelToken,
                     weak_factory_.GetWeakPtr()),
      kMaxBindBodyBytes);
```

`loader_` 是 `std::unique_ptr<network::SimpleURLLoader>`(`$TP/browser/enterprise/teleport_tunnel_service.h:167-168`,注释还写着 "One in-flight bind request at a time." —— **这条注释是愿望,不是被代码强制的不变量**)。`:301` 的移动赋值会销毁旧对象。

上游对「销毁 = 取消 + 不回调」的定义(两处逐字):

- `$CR/services/network/public/cpp/simple_url_loader.h:58-60`

  ```
  // Deleting a SimpleURLLoader before it completes cancels the requests and frees
  // any resources it is using (including any partially downloaded files). A
  // SimpleURLLoader may be safely deleted while it's invoking any callback method
  // that was passed it.
  ```

- `$CR/services/network/public/cpp/simple_url_loader.h:229-233`(`DownloadToString` 的注释,即我们用的那个)

  ```
  // Whether the request succeeds or fails, the URLLoaderFactory pipe is closed,
  // or the body exceeds `max_body_size`, `body_as_string_callback` will be
  // invoked on completion. Deleting the SimpleURLLoader before the callback is
  // invoked will result in cancelling the request, and the callback will not be
  // called.
  ```

**后果链(全部是静默的)**:被取消的那次尝试 ⇒ `OnTunnelToken` 不跑 ⇒ `OnBindFailed` 不跑(`:329-335`)⇒ `bind_backoff_.InformOfRequest(...)` 不跑(`:321` / `:331`)⇒ 退避计数不推进 ⇒ 也不 `ScheduleRefresh`(`:326`)。既无日志也无指标,从外部完全不可见。

**今天为什么还没炸**:三个调用点恰好互不重叠 —— `Start()`(`:212`,被 `started_` 单次门控 `:200-203`)、`retry_timer_` 回调(`:332-334`,`OnBindFailed` 已先 `loader_.reset()` 于 `:330`)、`refresh_timer_` 回调(`:349`,前置的 `OnTunnelToken` 已 `loader_.reset()` 于 `:319`)。这是**巧合的单飞**,不是设计出来的。

**Task 7 必须处理的三个新增风险**:

1. **唤醒 → `BeginBind()` 会直接取消在途 bind。** 这正是计划里 `WakeUpDoesNotCancelInFlightBind` 要钉的行为。
2. **抖动饿死**:唤醒源若短时间内重复触发(策略分批下发时完全可能),每次都会掐掉上一次在途请求,bind 可能永远完不成。⇒ 必须有**最小唤醒间隔**。
3. **定时器未被互斥**:`BeginBind()` 既不 `Stop()` `retry_timer_` 也不 `Stop()` `refresh_timer_`。唤醒触发 `BeginBind()` 后,原先已武装的 `retry_timer_` 到点仍会再发一次 `BeginBind()`,把刚发出的请求掐掉。⇒ 状态机进入 in-flight 时应显式停掉这两个定时器(或统一由状态机而非裸定时器驱动)。

---

## 8. 今天自动启动到底门控在什么上(`MaybeAutoStartFromPrefs`)?哪些是**读**、哪些是**观察**?

`$TP/browser/enterprise/teleport_tunnel_service.cc:138-168` 全文语义:

| 顺序 | 位置 | 条件 | 性质 |
|---|---|---|---|
| 1 | `:139-141` | `if (started_) return;` | **读**内存状态(幂等门) |
| 2 | `:147-149` | `prefs->GetList(prefs::kManagedAutoSelectCertificateForUrls).empty()` → return | **读** pref 值 |
| 3 | `:159-162` | `prefs->GetString(enterprise_signin::prefs::kPolicyRecoveryToken).empty()` → return | **读** pref 值 |
| 4 | `:167` | 三关全过 → `Start()` | 动作 |

**被观察的只有一个 pref**,`:116-120`:

```cpp
  pref_change_registrar_.Init(profile_->GetPrefs());
  pref_change_registrar_.Add(
      prefs::kManagedAutoSelectCertificateForUrls,
      base::BindRepeating(&TeleportTunnelService::OnManagedAutoSelectPrefChanged,
                          weak_factory_.GetWeakPtr()));
```

**初次检查被显式推迟到下一个 task**,`:130-133`:

```cpp
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&TeleportTunnelService::MaybeAutoStartFromPrefs,
                     weak_factory_.GetWeakPtr()));
```

理由见 `:121-129` 的注释:本服务是从 `ProfileNetworkContextService::ConfigureNetworkContextParamsInternal` 内部**懒创建**的,同步跑 `Start()` 会重入 NetworkContext 配置(`Start()` → `BeginBind()` → `GetDefaultStoragePartition()`)。**这条约束在 Task 7 里必须保留** —— 任何新的「构造期立刻检查」都要保持异步。

观察者回调 `OnManagedAutoSelectPrefChanged`(`:170-197`)是**双职责**的:

- `started_` 为 false(`:171-176`):转交 `MaybeAutoStartFromPrefs()` 重跑三关;
- `started_` 为 true(`:191-196`):重新推导 `routable_origins_`,变了就 `PushConfig()`。**注意它不会触发 `BeginBind()`** —— 所以计划里 `WakeUpShortCircuitsBackoff` 用例期望的 `bind_attempts()==2` 今天必然拿不到,需要新接线。

**今天没有被门控、也没有被观察的东西(缺口清单)**:

1. **设备证书是否可用 —— 完全没有判据。** bind 直接发,靠 mTLS 握手失败兜底(§6.7)。
2. **`kPolicyRecoveryToken` 只读不观察。** 见 §6.6,顺序反了就本会话不启动。
3. **供给策略 pref(`client_certificates.provision_for_user.value`)既不读也不观察。**
4. **没有 in-flight 状态。** 见 §7。

---

## 结论:可用的唤醒信号

### A. 判定表

| 信号 | 可用? | 精确触发语义 | 陷阱 |
|---|---|---|---|
| **读值门**:`prefs::kManagedAutoSelectCertificateForUrls` 非空 + `enterprise_signin::prefs::kPolicyRecoveryToken` 非空 | ✅ **必需,不可省** | 无触发,主动拉取当前真值 | `PrefChangeRegistrar` 不回放初始值(§1),而本服务是懒创建、可能晚于 pref 落地才诞生(§8 `:121-129`)⇒ 只挂通知严格更弱 |
| **观察者 A**:`prefs::kManagedAutoSelectCertificateForUrls`(**已有**) | ✅ **保留** | 值**变化**时触发;语义 = 「路由策略下发 / 变更」 | 已在 `started_` 前后双职责(§8);Task 7 加唤醒时不要破坏 `:191-196` 的重推导职责 |
| **观察者 B**:`enterprise_signin::prefs::kPolicyRecoveryToken`(**新增**) | ✅ **建议新增** | 值由空变非空时触发;语义 = 「本 profile 完成纳管」;写入点 `teleport_oidc_inplace_registrar.cc:175-177` | 今天**只读不观察**,是实打实的漏信号(§6.6);零外部依赖、零测试改造成本 |
| **观察者 C**:`client_certificates::prefs::kProvisionManagedClientCertificateForUserPrefs`(= `"client_certificates.provision_for_user.value"`,**新增**) | ⚠️ **可选,价值有限** | 值**变化**时触发;语义 = 「供给策略刚打开」= 供给**开始**,**不是**证书就绪 | ① 与观察者 A **同批下发、同 task 内先后触发**(§6.1 陷阱 A)⇒ 冷启动主场景几乎不提供新信息;② 语义是「开始」不是「就绪」,必然过早唤醒一次;③ 判定必须是 `IsManagedPreference && GetInteger==1`,用户层写入不算(§6.1) |
| **`CertificateProvisioningService::GetManagedIdentity`** | ❌ **不可用** | request/response;策略未启用时**同步** `nullopt` 并返回,此后**永不再触发**(§2) | 上一轮的截断点;另附三重代价:回调内重入会 UAF 或静默丢回调(§3)、单测恒 `nullptr`(§4)、需 `DependsOn`(§5) |
| **`net::CertDatabase::Observer::OnClientCertStoreChanged`** | ❌ **不可用** | 企业供给链路**从不**调用 `NotifyObserversClientCertStoreChanged()`;macOS 上仅由 Keychain 事件触发且忽略本进程事件 | 本轮最像正解的陷阱(§6.5);托管身份在 LevelDB,不进 Keychain |
| **证书身份 pref**(`kManagedProfileIdentityName` 等) | ❌ **不可用** | 本产品里**无写入方** | `kManagedUserClientCertificateInPrefs` 默认关(§6.3),且 `disable_fieldtrial_testing_config=true` 把它钉死 ⇒ 恒为空字典 |
| **供给服务 / store 的 observer 接口** | ❌ **不存在** | — | 五个相关头文件里 `Observer`/`AddObserver`/`ObserverList` 零命中(§6.2) |
| **`GetCurrentStatus()` 轮询** | ⚠️ **仅诊断** | 无触发,纯拉取 | 头文件自陈 "mainly for debugging purposes";受 §4/§5 同样约束。可用于 `teleport://tunnel` 展示,**不可**作唤醒源 |
| **bind 本身 + 退避重试** | ✅ **承重,唯一真探针** | 失败即证据 | 是承重结构而非兜底;好消息:无 WebContents 的取消路径**不写** `SSLClientAuthCache`,重试干净不被毒化(§6.7) |

### B. 推荐组合

**读值门(每个入口都跑,不依赖任何通知)**

```
gate := (状态机 == idle)
     && GetList(kManagedAutoSelectCertificateForUrls) 非空
     && GetString(kPolicyRecoveryToken) 非空
```

—— 与今天 `MaybeAutoStartFromPrefs()` 的三关一致(§8),**不新增证书相关判据**:证书就绪不可观测,任何代理指标都不充分(spec §3.2 决策),加了只会制造新的假门。

**观察者(仅用于短路退避,不承担正确性)**

1. `prefs::kManagedAutoSelectCertificateForUrls` —— 保留现有,保留其 `started_` 后的重推导职责;
2. `enterprise_signin::prefs::kPolicyRecoveryToken` —— **新增**,补 §6.6 的漏信号;
3. (可选)`client_certificates::prefs::kProvisionManagedClientCertificateForUserPrefs` —— 只在需要覆盖「策略分批下发」时加;若加,须在文档里写明它是「供给开始」而非「证书就绪」,避免下一轮又被当成就绪信号。

三个观察者的回调走**同一个** `OnPreconditionSignal()` 入口:重跑读值门 → 通过则请求唤醒。由 §1 补充的性质(整张 map 先换后逐个通知)保证:任一回调里读其余 pref 都已是新值,**不需要**担心半更新。

**状态机(三态)与唤醒规则**

- `idle` → 门通过 + 唤醒请求 ⇒ 进入 `in-flight`,发 bind,并**显式 `Stop()` `retry_timer_` 与 `refresh_timer_`**(§7 风险 3);
- `in-flight` → 收到唤醒请求 ⇒ **不取消在途请求**,只置 `pending` 位,转 `in-flight + pending`;
- `in-flight + pending` → 在途请求终结(成功或失败)后**立即**再发一次,**跳过 `bind_backoff_` 的等待**(这就是「短路退避」),并清 `pending`;
- **最小自动唤醒间隔**:记录 `last_wake_bind_at_`,间隔未到的唤醒只置 `pending` 不立即发,防止抖动饿死(§7 风险 2)。手动重绑(Task 11 的诊断页入口)应可绕过该间隔 —— 它是人触发的,不会抖。

**必须同时改掉的两处错误注释**(§0.1):`teleport_oidc_inplace_registrar.cc:343-346` 与 `teleport_tunnel_service.h:67-70` 中「设备证书已 provisioned」的断言。

**给 Task 7 Step 2 三个新用例的落地提示**

- 三个用例都用 `TestingProfile` ⇒ 若实现里碰了 `CertificateProvisioningServiceFactory::GetForProfile`,拿到的是 `nullptr`(§4)。**采纳上面的推荐组合则完全不碰它**,三个用例无需 mock、无需新 GN 依赖。
- 策略 pref 一律经 managed store 写入(`GetTestingPrefService()->SetManagedPref`)—— 计划已注明;`kProvisionManagedClientCertificateForUserPrefs` 若被采纳为观察者 C,其 `IsManagedPreference` 判定使这一点从「惯例」升级为「硬性要求」(§6.1)。
- `WakeUpShortCircuitsBackoff` 需要新接线才可能变绿:今天 `OnManagedAutoSelectPrefChanged` 在 `started_==true` 时只重推导 + `PushConfig()`,**不发 bind**(§8)。
