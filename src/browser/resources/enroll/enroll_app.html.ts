// Copyright 2026 The Teleport Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {html} from '//resources/lit/v3_0/lit.rollup.js';

import type {EnrollAppElement} from './enroll_app.js';

export function getHtml(this: EnrollAppElement) {
  // clang-format off
  return html`<!--_html_template_start_-->
<div class="card">
  ${this.view_ === 'locked' ? html`
    <h1>部署域名</h1>
    <div class="subtitle">此浏览器已连接到组织服务器
      <span class="domain">${this.currentDomain_}</span>。</div>
    <div class="managed-note">此设置由你的组织管理,无法在此更改。</div>` : ''}
  ${this.view_ === 'form' ? html`
    ${this.canUnbind_ ? html`
      <h1>部署域名</h1>
      <div class="subtitle">当前已连接到组织服务器
        <span class="domain">${this.currentDomain_}</span>。</div>
      <div class="section-label">更改为其他组织服务器</div>
    ` : html`
      <h1>连接到组织服务器</h1>
      <div class="subtitle">输入你的组织提供的服务器域名以连接。</div>
    `}
    <cr-input id="domain" label="服务器域名" placeholder="例如 acme.internal"
        .value="${this.domain_}"
        @value-changed="${this.onDomainValueChanged_}"
        @keydown="${this.onKeydown_}"
        ?invalid="${!!this.errorMessage_}"
        error-message="${this.errorMessage_}"
        autofocus spellcheck="false" autocomplete="off">
    </cr-input>
    <div class="action-row">
      ${this.canUnbind_ ? html`
        <cr-button id="unbind" @click="${this.onUnbindClick_}">
          解除绑定
        </cr-button>` : ''}
      <cr-button id="verify" class="action-button" ?disabled="${this.busy_}"
          @click="${this.onVerifyClick_}">
        ${this.busy_ ? '正在验证…' : '验证'}
      </cr-button>
    </div>` : ''}
  ${this.view_ === 'confirm' ? html`
    <h1>确认连接</h1>
    <div class="subtitle">连接到组织服务器
      <span class="domain">${this.confirmDomain_}</span>?</div>
    <div class="action-row">
      <cr-button id="cancel" @click="${this.onCancelClick_}">取消</cr-button>
      <cr-button id="connect" class="action-button"
          @click="${this.onConnectClick_}">
        连接
      </cr-button>
    </div>` : ''}
  ${this.view_ === 'done' ? html`
    <h1>已连接</h1>
    <div class="subtitle">已连接到
      <span class="domain">${this.doneDomain_}</span>,重启后生效。</div>
    <div class="action-row">
      <cr-button id="relaunch" class="action-button"
          @click="${this.onRelaunchClick_}">
        重启 Teleport
      </cr-button>
    </div>` : ''}
  ${this.view_ === 'unbound' ? html`
    <h1>已解除绑定</h1>
    <div class="subtitle">已断开与组织服务器的连接,重启后恢复默认设置。</div>
    <div class="action-row">
      <cr-button id="relaunch" class="action-button"
          @click="${this.onRelaunchClick_}">
        重启 Teleport
      </cr-button>
    </div>` : ''}
</div>
<!--_html_template_end_-->`;
  // clang-format on
}
