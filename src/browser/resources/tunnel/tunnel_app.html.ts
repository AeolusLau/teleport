// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// COPY RULES, not style preferences (see tunnel_app.ts):
//   * `blocked` is worded as "服务端标记:无路由行" plus the explanation that
//     the edge decides over a collapsed claimant set. It must NEVER say the
//     access will fail — the flag and the edge's verdict can legitimately
//     disagree.
//   * an empty routing table says the SERVER SENT an empty table, and states
//     nothing about why. "Your organization has no apps" is an inference this
//     page cannot make.

import {html} from '//resources/lit/v3_0/lit.rollup.js';

import type {TunnelAppElement} from './tunnel_app.js';

export function getHtml(this: TunnelAppElement) {
  // clang-format off
  return html`<!--_html_template_start_-->
<div class="page">
  <h1>隧道诊断</h1>
  <div class="subtitle">此页面显示当前配置文件的接入隧道派生状态。所有内容均为
    诊断信息;访问是否被允许由边缘节点判定,不由本页面决定。</div>

  ${!this.loaded_ || !this.state_ ? html`
    <div class="card">
      <div class="empty">正在读取隧道状态…</div>
    </div>` : html`

    ${this.state_.routesHardStale ? html`
      <div class="card warning">
        <h2>路由表未获重新确认</h2>
        <div class="empty">最近一次绑定成功,但响应中没有可用的路由表,因此下方
          仍是更早一次响应下发的那张表。原因:${this.state_.routesHardStaleReason}</div>
      </div>` : ''}

    <div class="card">
      <h2>概览</h2>
      <dl>
        <dt>纳管状态</dt>
        <dd>${this.state_.enrolled ? '已纳管' : '未纳管'}</dd>
        <dt>证书选择策略</dt>
        <dd>${this.state_.autoSelectPolicyPresent ? '已下发' : '未下发'}</dd>
        <dt>隧道编排</dt>
        <dd>${this.state_.started ? '已启动' : '未启动'}</dd>
        <dt>绑定请求</dt>
        <dd>${this.state_.bindInFlight ? '进行中' : '空闲'}</dd>
        <dt>访问凭据</dt>
        <dd>${this.state_.hasToken ? '已持有' : '未持有'}</dd>
        <dt>代理配置</dt>
        <dd>${this.state_.configPushed ? '已下发到网络栈' : '尚未下发'}</dd>
        <dt>绑定入口(gate)</dt>
        <dd class="mono">${this.state_.gateHost}</dd>
        <dt>边缘节点(edge)</dt>
        <dd class="mono">${this.state_.edgeHost}:${this.state_.edgePort}</dd>
      </dl>
    </div>

    <div class="card">
      <h2>时间线</h2>
      <dl>
        <dt>最近一次绑定尝试</dt>
        <dd>${this.formatTime_(this.state_.lastBindAttemptMs)}</dd>
        <dt>最近一次绑定成功</dt>
        <dd>${this.formatTime_(this.state_.lastBindSuccessMs)}</dd>
        <dt>凭据到期</dt>
        <dd>${this.formatTime_(this.state_.tokenExpiresMs)}
          ${this.formatRelative_(this.state_.tokenExpiresMs)}</dd>
        <dt>下次自动刷新</dt>
        <dd>${this.formatTime_(this.state_.nextRefreshMs)}
          ${this.formatRelative_(this.state_.nextRefreshMs)}</dd>
        <dt>下次失败重试</dt>
        <dd>${this.formatTime_(this.state_.nextRetryMs)}
          ${this.formatRelative_(this.state_.nextRetryMs)}</dd>
        <dt>最近一次失败原因</dt>
        <dd>${this.state_.lastBindError || '—'}</dd>
      </dl>
    </div>

    <div class="card">
      <h2>生效的路由地址(${this.state_.routableOrigins.length})</h2>
      ${this.state_.routesUnavailable ? html`
        <div class="empty">尚未收到任何良构的路由表。</div>` : ''}
      ${!this.state_.routesUnavailable && this.state_.routableOrigins.length === 0 ? html`
        <!-- The server sent an empty table. Why it did is not knowable here,
             and this page does not guess. -->
        <div class="empty">服务端下发了一张空的路由表(0 条)。本页面不推断其
          原因。</div>` : ''}
      ${this.state_.routableOrigins.length > 0 ? html`
        <table>
          <thead>
            <tr><th>地址</th><th>范围</th><th>服务端标记</th></tr>
          </thead>
          <tbody>
            ${this.state_.routableOrigins.map(origin => html`
              <tr>
                <td class="mono">${origin.host}:${origin.port}</td>
                <td>${origin.includeSubdomains ? '含子域' : '仅此主机'}</td>
                <td>${origin.blocked ? html`
                  <span class="tag">无路由行</span>` : '—'}</td>
              </tr>`)}
          </tbody>
        </table>
        ${this.state_.routableOrigins.some(o => o.blocked) ? html`
          <div class="note">「无路由行」表示服务端标记该地址在路由表中没有属于
            它自己的路由行。边缘节点的放行判定是在坍缩后的申领集合上计算的,可能
            与该标记不一致——因此它不代表访问一定失败,仅供排查时参考。</div>` : ''}` : ''}
      ${this.state_.routesStale || this.state_.routesTruncated || this.state_.routesDropped > 0 ||
        this.state_.routesDigest ? html`
        <dl class="meta">
          <dt>服务端自述陈旧</dt>
          <dd>${this.state_.routesStale ? '是' : '否'}</dd>
          <dt>服务端自述截断</dt>
          <dd>${this.state_.routesTruncated ? '是' : '否'}</dd>
          <dt>服务端丢弃条目数</dt>
          <dd>${this.state_.routesDropped}</dd>
          <dt>路由表摘要</dt>
          <dd class="mono">${this.state_.routesDigest || '—'}</dd>
        </dl>
        <div class="note">以上四项均为诊断信息,按跨仓契约不参与任何路由决策。</div>`
        : ''}
    </div>

    <div class="card">
      <h2>被跳过的条目(${this.state_.skippedEntries.length})</h2>
      ${this.state_.skippedEntries.length === 0 ? html`
        <div class="empty">没有条目被跳过。</div>` : html`
        <table>
          <thead><tr><th>原始条目</th><th>跳过原因</th></tr></thead>
          <tbody>
            ${this.state_.skippedEntries.map(entry => html`
              <tr>
                <td class="mono">${entry.raw}</td>
                <td>${entry.reason}</td>
              </tr>`)}
          </tbody>
        </table>`}
    </div>

    <div class="card">
      <h2>最近的 CONNECT 结果(${this.state_.recentConnects.length})</h2>
      ${this.state_.recentConnects.length === 0 ? html`
        <div class="empty">尚未观察到经由本隧道的 CONNECT。</div>` : html`
        <table>
          <thead><tr><th>时间</th><th>目标</th><th>状态码</th></tr></thead>
          <tbody>
            ${this.state_.recentConnects.map(result => html`
              <tr>
                <td>${this.formatTime_(result.timeMs)}</td>
                <td class="mono">${result.authority}</td>
                <td>${result.responseCode || '—'}</td>
              </tr>`)}
          </tbody>
        </table>`}
    </div>

    <div class="action-row">
      <cr-button id="refresh" @click="${this.onRefreshClick_}">刷新</cr-button>
      <cr-button id="rebind" class="action-button" ?disabled="${this.busy_}"
          @click="${this.onRebindClick_}">
        立即重新绑定
      </cr-button>
    </div>
    ${this.rebindMessage_ ? html`
      <div class="note">${this.rebindMessage_}</div>` : ''}`}
</div>
<!--_html_template_end_-->`;
  // clang-format on
}
