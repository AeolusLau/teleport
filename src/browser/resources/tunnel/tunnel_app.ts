// Copyright 2026 The Teleport Authors
// Tunnel diagnostics page (teleport://tunnel). Pulls one snapshot of the
// profile's tunnel state over Mojo and renders it, and offers a manual rebind.
//
// Everything shown here is DERIVED state that had no surface at all before:
// which origins the gate actually routed, what was rejected on the way in, what
// the edge answered, and when the credential lapses. The snapshot deliberately
// excludes the cnf token — this page is a rendering surface with a DevTools
// console attached.
//
// TWO WORDING RULES ARE LOAD-BEARING (see tunnel_app.html.ts):
//   * `blocked` means "the server marked this address as having no route row",
//     NEVER "this will fail". The edge's verdict is computed over a collapsed
//     claimant set, so a per-row flag can legitimately disagree with it.
//   * an empty routing table is reported as "the server sent an empty table",
//     never as "your organization has no apps" — the page does not know why.

import 'chrome://resources/cr_elements/cr_button/cr_button.js';

import {ColorChangeUpdater} from 'chrome://resources/cr_components/color_change_listener/colors_css_updater.js';
import {CrLitElement} from 'chrome://resources/lit/v3_0/lit.rollup.js';

import {getCss} from './tunnel_app.css.js';
import {getHtml} from './tunnel_app.html.js';
import type {TunnelState} from './tunnel.mojom-webui.js';
import {PageHandlerFactory, PageHandlerRemote} from './tunnel.mojom-webui.js';

export class TunnelAppElement extends CrLitElement {
  static get is() {
    return 'tunnel-app';
  }

  static override get styles() {
    return getCss();
  }

  override render() {
    return getHtml.bind(this)();
  }

  static override get properties() {
    return {
      loaded_: {type: Boolean},
      state_: {type: Object},
      rebindMessage_: {type: String},
      busy_: {type: Boolean},
    };
  }

  // False until the first GetState() reply lands. If the Mojo interface binder
  // patch is missing, the call never resolves and the page sits here forever —
  // which is exactly the symptom that distinguishes that failure from a
  // missing WebUIConfig (a 404, no page at all).
  protected accessor loaded_: boolean = false;
  protected accessor state_: TunnelState|null = null;
  protected accessor rebindMessage_: string = '';
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
    this.refresh_();
  }

  // 0 is the wire's "never" / "not armed"; rendering it would read as 1970.
  protected formatTime_(ms: number): string {
    if (!ms) {
      return '—';
    }
    return new Date(ms).toLocaleString();
  }

  // Relative form for the two future instants, so an operator can see "in 6
  // minutes" without doing clock arithmetic. Negative means it is overdue,
  // which is itself worth seeing rather than hiding.
  protected formatRelative_(ms: number): string {
    if (!ms) {
      return '';
    }
    const seconds = Math.round((ms - Date.now()) / 1000);
    if (seconds < 0) {
      return `(已过期 ${-seconds} 秒)`;
    }
    if (seconds < 120) {
      return `(${seconds} 秒后)`;
    }
    return `(${Math.round(seconds / 60)} 分钟后)`;
  }

  protected onRefreshClick_() {
    this.rebindMessage_ = '';
    this.refresh_();
  }

  protected async onRebindClick_() {
    if (this.busy_) {
      return;
    }
    this.busy_ = true;
    const {accepted} = await this.handler_.rebind();
    this.busy_ = false;
    // The refusal reasons are enumerated by the service, not guessed here; the
    // page reports the two the snapshot can distinguish and otherwise says the
    // request was declined without inventing a cause.
    if (accepted) {
      this.rebindMessage_ = '已请求重新绑定,稍后刷新查看结果。';
    } else if (this.state_ && !this.state_.enrolled) {
      this.rebindMessage_ = '已拒绝:此配置文件尚未纳管。';
    } else if (this.state_ && !this.state_.autoSelectPolicyPresent) {
      this.rebindMessage_ = '已拒绝:设备证书选择策略尚未下发,绑定无法完成握手。';
    } else if (this.state_ && this.state_.bindInFlight) {
      this.rebindMessage_ = '已拒绝:已有一次绑定正在进行中。';
    } else {
      this.rebindMessage_ = '已拒绝:距离上次手动重新绑定的间隔过短。';
    }
    this.refresh_();
  }

  private async refresh_() {
    const {state} = await this.handler_.getState();
    this.state_ = state;
    this.loaded_ = true;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'tunnel-app': TunnelAppElement;
  }
}

customElements.define(TunnelAppElement.is, TunnelAppElement);
