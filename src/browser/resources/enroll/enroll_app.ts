// Copyright 2026 The Teleport Authors
// Enroll page (teleport://enroll): a private-deployment BYOD user sets their
// organization's deployment domain here before enrolling. Talks to the browser
// PageHandler over Mojo. Built on the standard cr-elements design system
// (cr-input / cr-button + Chromium color pipeline) so it matches native WebUI
// look and light/dark theming. Domains are shown exactly as the browser returns
// them (canonical punycode) via Lit text bindings (auto-escaped) to defeat
// ?domain= injection and IDN homograph spoofing at the confirmation point.
//
// On load the page asks GetState() for the current binding + lock flags and
// picks a view (spec §4.2 / §4.6): read-only (corp-managed lock), an editable
// form (BYOD), and — when already bound via a user-accepted entry — an unbind
// (disconnect) action.

import 'chrome://resources/cr_elements/cr_button/cr_button.js';
import 'chrome://resources/cr_elements/cr_input/cr_input.js';

import {ColorChangeUpdater} from 'chrome://resources/cr_components/color_change_listener/colors_css_updater.js';
import {CrLitElement} from 'chrome://resources/lit/v3_0/lit.rollup.js';

import {getCss} from './enroll_app.css.js';
import {getHtml} from './enroll_app.html.js';
import {PageHandlerFactory, PageHandlerRemote} from './enroll.mojom-webui.js';

type EnrollView = 'loading'|'locked'|'form'|'confirm'|'done'|'unbound';

// Distinct message per status (spec §4.2 error classification).
const MESSAGES: {[key: string]: string} = {
  kInvalidDomainFormat: '域名格式无效,请输入形如 acme.internal 的主机名。',
  kCannotConnect: '无法连接到该服务器,请检查域名与网络。',
  kTlsError: '该服务器的 TLS 证书无效。',
  kHttpError: '服务器返回了非预期的响应。',
  kMalformedResponse: '服务器返回的身份数据格式不正确。',
  kBadSignature: '身份签名无效,该服务器不是受信任的部署。',
  kWrongMessageType: '身份数据类型不匹配。',
  kUnsupportedVersion: '身份数据版本不受支持。',
  kDomainMismatch: '身份中的域名与输入不一致。',
  kExpired: '该服务器的身份凭据已过期。',
  kAlreadyEnrolled: '此浏览器的部署域名由你的组织管理,无法在此更改。',
};

export class EnrollAppElement extends CrLitElement {
  static get is() {
    return 'enroll-app';
  }

  static override get styles() {
    return getCss();
  }

  override render() {
    return getHtml.bind(this)();
  }

  static override get properties() {
    return {
      view_: {type: String},
      currentDomain_: {type: String},
      canUnbind_: {type: Boolean},
      domain_: {type: String},
      confirmDomain_: {type: String},
      doneDomain_: {type: String},
      errorMessage_: {type: String},
      busy_: {type: Boolean},
    };
  }

  protected accessor view_: EnrollView = 'loading';
  // The effective domain D at load, and whether it came from a user-accepted
  // (level-4) entry that can be unbound.
  protected accessor currentDomain_: string = '';
  protected accessor canUnbind_: boolean = false;
  // The change-flow working state.
  protected accessor domain_: string = '';
  protected accessor confirmDomain_: string = '';
  protected accessor doneDomain_: string = '';
  protected accessor errorMessage_: string = '';
  protected accessor busy_: boolean = false;

  private handler_: PageHandlerRemote = new PageHandlerRemote();

  constructor() {
    super();
    // Repaint on live theme changes (dep: color_change_listener).
    ColorChangeUpdater.forDocument().start();
    PageHandlerFactory.getRemote().createPageHandler(
        this.handler_.$.bindNewPipeAndPassReceiver());
  }

  override firstUpdated() {
    this.loadState_();
  }

  private async loadState_() {
    const {state} = await this.handler_.getState();
    this.currentDomain_ = state.domain;
    this.canUnbind_ = state.canUnbind;
    if (state.locked) {
      this.view_ = 'locked';
      return;
    }
    this.view_ = 'form';
    // Deep link: teleport://enroll?domain=acme.internal prefills + verifies.
    const prefill = new URLSearchParams(location.search).get('domain');
    if (prefill && prefill.trim()) {
      this.domain_ = prefill.trim();
      this.verify_();
    }
  }

  protected onDomainValueChanged_(e: CustomEvent<{value: string}>) {
    this.domain_ = e.detail.value;
    this.errorMessage_ = '';
  }

  protected onKeydown_(e: KeyboardEvent) {
    if (e.key === 'Enter') {
      this.verify_();
    }
  }

  protected onVerifyClick_() {
    this.verify_();
  }

  private async verify_() {
    const domain = this.domain_.trim();
    if (!domain || this.busy_) {
      return;
    }
    this.busy_ = true;
    this.errorMessage_ = '';
    const {result} = await this.handler_.verify(domain);
    this.busy_ = false;
    if (result.status === 'kSuccess') {
      this.confirmDomain_ = result.domain;
      this.view_ = 'confirm';
      return;
    }
    this.errorMessage_ = MESSAGES[result.status] || ('验证失败:' + result.status);
  }

  protected async onConnectClick_() {
    const {ok} = await this.handler_.confirm();
    if (ok) {
      this.doneDomain_ = this.confirmDomain_;
      this.view_ = 'done';
      return;
    }
    this.view_ = 'form';
    this.errorMessage_ = '保存失败,请重试。';
  }

  protected onCancelClick_() {
    this.view_ = 'form';
  }

  protected async onUnbindClick_() {
    const {ok} = await this.handler_.unbind();
    if (ok) {
      this.view_ = 'unbound';
    }
  }

  protected onRelaunchClick_() {
    this.handler_.relaunch();
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'enroll-app': EnrollAppElement;
  }
}

customElements.define(EnrollAppElement.is, EnrollAppElement);
