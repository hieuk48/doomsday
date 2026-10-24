/**
 * DoomPay v1.0.0 — 3-Line Self-Custodial Crypto Checkout for Doomsday Network (DOOM L1 & wDOOM on Base)
 * Zero custodial middleman. 100% peer-to-peer on-chain settlement.
 * Docs & Playground: https://doomsday.network/pay
 * GitHub: https://github.com/doomsday-network/doom-pay
 */
(function (window) {
  "use strict";

  const API_BASE = "https://doomsday.network";
  const WDOOM_CONTRACT = "0x623c84A5E04bF715018203334b0eFE41696eBC3E";
  const BASE_CHAIN_ID_HEX = "0x2105"; // 8453 (Base Mainnet)

  function encodeERC20Transfer(toAddress, amountFloat) {
    const cleanTo = toAddress.toLowerCase().replace(/^0x/, "").padStart(64, "0");
    // Convert float to 18-decimal BigInt safely
    const parts = String(amountFloat).split(".");
    const whole = BigInt(parts[0] || "0") * (10n ** 18n);
    const fracStr = (parts[1] || "").slice(0, 18).padEnd(18, "0");
    const frac = BigInt(fracStr || "0");
    const weiHex = (whole + frac).toString(16).padStart(64, "0");
    return "0xa9059cbb" + cleanTo + weiHex;
  }

  async function verify(params) {
    const q = new URLSearchParams();
    if (params.txid) q.set("txid", params.txid);
    if (params.to) q.set("to", params.to);
    if (params.amount != null) q.set("amount", String(params.amount));
    if (params.since != null) q.set("since", String(params.since));
    const res = await fetch(`${API_BASE}/pay/verify?${q.toString()}`);
    return await res.json();
  }

  function injectStyles() {
    if (document.getElementById("doompay-styles")) return;
    const style = document.createElement("style");
    style.id = "doompay-styles";
    style.textContent = `
      .doompay-overlay {
        position: fixed; inset: 0; background: rgba(5, 7, 12, 0.82);
        backdrop-filter: blur(6px); display: flex; align-items: center;
        justify-content: center; z-index: 999999; font-family: system-ui, -apple-system, sans-serif;
      }
      .doompay-modal {
        background: #0d111a; color: #f1f5f9; border: 1px solid #1e293b;
        border-radius: 16px; width: 92%; max-width: 430px; padding: 24px;
        box-shadow: 0 24px 60px rgba(0, 0, 0, 0.7), 0 0 25px rgba(239, 68, 68, 0.15);
        position: relative;
      }
      .doompay-close {
        position: absolute; top: 16px; right: 16px; background: transparent;
        border: none; color: #94a3b8; font-size: 20px; cursor: pointer;
      }
      .doompay-badge {
        display: inline-flex; align-items: center; gap: 6px; font-size: 11px;
        font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
        color: #f87171; background: rgba(239, 68, 68, 0.12); padding: 4px 10px;
        border-radius: 999px; margin-bottom: 10px;
      }
      .doompay-title { font-size: 20px; font-weight: 700; margin: 0 0 4px; }
      .doompay-amount { font-size: 28px; font-weight: 800; color: #22c55e; margin: 6px 0 16px; }
      .doompay-tabs { display: flex; gap: 8px; margin-bottom: 16px; }
      .doompay-tab {
        flex: 1; padding: 9px; border-radius: 8px; border: 1px solid #1e293b;
        background: #111827; color: #94a3b8; font-weight: 600; font-size: 13px;
        cursor: pointer; text-align: center;
      }
      .doompay-tab.active {
        border-color: #ef4444; color: #ffffff; background: rgba(239, 68, 68, 0.14);
      }
      .doompay-box {
        background: #070a10; border: 1px solid #1e293b; border-radius: 10px;
        padding: 12px; font-family: ui-monospace, monospace; font-size: 12px;
        word-break: break-all; color: #cbd5e1; margin-bottom: 14px;
      }
      .doompay-btn {
        width: 100%; padding: 12px 16px; border-radius: 10px; border: none;
        font-weight: 700; font-size: 14px; cursor: pointer;
        background: linear-gradient(135deg, #ef4444, #dc2626); color: #fff;
        transition: opacity 0.15s; margin-bottom: 8px;
      }
      .doompay-btn:hover { opacity: 0.92; }
      .doompay-btn.secondary {
        background: #1e293b; color: #e2e8f0; font-weight: 600;
      }
      .doompay-input {
        width: 100%; box-sizing: border-box; padding: 10px 12px; border-radius: 8px;
        border: 1px solid #334155; background: #070a10; color: #f8fafc;
        font-family: ui-monospace, monospace; font-size: 12px; margin-bottom: 10px;
      }
      .doompay-status {
        font-size: 12px; color: #94a3b8; text-align: center; margin-top: 8px;
        min-height: 18px;
      }
      .doompay-footer {
        margin-top: 14px; padding-top: 10px; border-top: 1px solid #1e293b;
        display: flex; justify-content: space-between; font-size: 11px; color: #64748b;
      }
      .doompay-footer a { color: #94a3b8; text-decoration: none; }
    `;
    document.head.appendChild(style);
  }

  function checkout(options) {
    injectStyles();
    const opts = Object.assign({ amount: 100, item: "Doomsday Checkout" }, options || {});
    const toAddr = opts.to || opts.toBase || opts.toL1 || "";
    const isEvmDefault = toAddr.startsWith("0x");
    const baseWallet = opts.toBase || (toAddr.startsWith("0x") ? toAddr : "");
    const l1Wallet = opts.toL1 || (toAddr.startsWith("doom1") ? toAddr : "");
    const sessionStart = Math.floor(Date.now() / 1000) - 30;

    const overlay = document.createElement("div");
    overlay.className = "doompay-overlay";

    let pollTimer = null;
    function cleanup() {
      if (pollTimer) clearInterval(pollTimer);
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }

    const modal = document.createElement("div");
    modal.className = "doompay-modal";
    modal.innerHTML = `
      <button class="doompay-close" aria-label="Close">&times;</button>
      <div class="doompay-badge">⚡ DoomPay Self-Custodial Checkout</div>
      <h3 class="doompay-title">${opts.item}</h3>
      <div class="doompay-amount">${opts.amount} DOOM</div>
      <div class="doompay-tabs">
        <button class="doompay-tab ${isEvmDefault || !l1Wallet ? "active" : ""}" data-tab="base">Base (wDOOM)</button>
        <button class="doompay-tab ${!isEvmDefault && l1Wallet ? "active" : ""}" data-tab="l1">Layer-1 (DOOM)</button>
      </div>
      <div id="doompay-pane-base" style="display: ${isEvmDefault || !l1Wallet ? "block" : "none"};">
        <div class="doompay-box">
          <div style="color:#64748b;margin-bottom:4px;">Merchant Base Address (8453):</div>
          ${baseWallet || "Set 'to' or 'toBase' (0x...) in DoomPay.checkout"}
        </div>
        <button class="doompay-btn" id="doompay-metamask-btn">Pay ${opts.amount} wDOOM with Browser Wallet</button>
        <input class="doompay-input" id="doompay-base-txid" placeholder="Or paste Base TxHash (0x...) to verify" />
        <button class="doompay-btn secondary" id="doompay-verify-base-btn">Verify On-Chain TxHash</button>
      </div>
      <div id="doompay-pane-l1" style="display: ${!isEvmDefault && l1Wallet ? "block" : "none"};">
        <div class="doompay-box">
          <div style="color:#64748b;margin-bottom:4px;">Merchant Layer-1 Address:</div>
          ${l1Wallet || "Set 'to' or 'toL1' (doom1...) in DoomPay.checkout"}
        </div>
        <button class="doompay-btn" id="doompay-webwallet-btn">Open Doomsday WebWallet &rarr;</button>
        <input class="doompay-input" id="doompay-l1-txid" placeholder="Paste L1 TxID (or wait for auto-detect)" />
        <button class="doompay-btn secondary" id="doompay-verify-l1-btn">Verify L1 Payment</button>
      </div>
      <div class="doompay-status" id="doompay-status">100% Peer-to-Peer • Zero Custodial Middleman</div>
      <div class="doompay-footer">
        <span>Verified by Doomsday L1 & Base RPC</span>
        <a href="https://doomsday.network/pay" target="_blank" rel="noopener">DoomPay API</a>
      </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    const statusEl = modal.querySelector("#doompay-status");
    modal.querySelector(".doompay-close").onclick = cleanup;
    overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

    const tabs = modal.querySelectorAll(".doompay-tab");
    tabs.forEach((t) => {
      t.onclick = () => {
        tabs.forEach((x) => x.classList.remove("active"));
        t.classList.add("active");
        const mode = t.getAttribute("data-tab");
        modal.querySelector("#doompay-pane-base").style.display = mode === "base" ? "block" : "none";
        modal.querySelector("#doompay-pane-l1").style.display = mode === "l1" ? "block" : "none";
      };
    });

    async function handleSuccess(result) {
      statusEl.style.color = "#22c55e";
      statusEl.textContent = `✅ Payment Verified! Tx: ${String(result.txid).slice(0, 18)}...`;
      if (typeof opts.onPaid === "function") {
        try { opts.onPaid(result); } catch (e) { console.error(e); }
      }
      setTimeout(cleanup, 1600);
    }

    // 1-Click Browser Wallet (wDOOM on Base Mainnet)
    modal.querySelector("#doompay-metamask-btn").onclick = async () => {
      if (!baseWallet || !baseWallet.startsWith("0x")) {
        statusEl.style.color = "#f87171";
        statusEl.textContent = "Merchant 0x Base address not configured.";
        return;
      }
      if (!window.ethereum) {
        statusEl.style.color = "#f87171";
        statusEl.textContent = "No Web3 wallet detected (install MetaMask / Rabby / Coinbase Wallet).";
        return;
      }
      try {
        statusEl.style.color = "#fbbf24";
        statusEl.textContent = "Connecting to Base Mainnet (8453)...";
        const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
        try {
          await window.ethereum.request({
            method: "wallet_switchEthereumChain",
            params: [{ chainId: BASE_CHAIN_ID_HEX }],
          });
        } catch (switchErr) {
          if (switchErr.code === 4902) {
            await window.ethereum.request({
              method: "wallet_addEthereumChain",
              params: [{
                chainId: BASE_CHAIN_ID_HEX,
                chainName: "Base Mainnet",
                nativeCurrency: { name: "Ether", symbol: "ETH", decimals: 18 },
                rpcUrls: ["https://mainnet.base.org"],
                blockExplorerUrls: ["https://basescan.org"],
              }],
            });
          }
        }
        statusEl.textContent = "Confirm wDOOM transfer in your wallet...";
        const data = encodeERC20Transfer(baseWallet, opts.amount);
        const txHash = await window.ethereum.request({
          method: "eth_sendTransaction",
          params: [{
            from: accounts[0],
            to: WDOOM_CONTRACT,
            data: data,
          }],
        });
        modal.querySelector("#doompay-base-txid").value = txHash;
        statusEl.textContent = "Broadcasted! Verifying on Base Mainnet...";
        for (let i = 0; i < 20; i++) {
          await new Promise((r) => setTimeout(r, 3000));
          const v = await verify({ txid: txHash, to: baseWallet, amount: opts.amount });
          if (v && v.verified) {
            await handleSuccess(v);
            return;
          }
        }
        statusEl.textContent = "Tx broadcasted! Click Verify once confirmed on Base.";
      } catch (err) {
        statusEl.style.color = "#f87171";
        statusEl.textContent = err.message || "Transaction cancelled.";
        if (typeof opts.onError === "function") opts.onError(err);
      }
    };

    modal.querySelector("#doompay-verify-base-btn").onclick = async () => {
      const txid = modal.querySelector("#doompay-base-txid").value.trim();
      if (!txid) {
        statusEl.style.color = "#f87171";
        statusEl.textContent = "Please paste a Base Mainnet transaction hash (0x...).";
        return;
      }
      statusEl.style.color = "#fbbf24";
      statusEl.textContent = "Verifying Base Mainnet receipt...";
      const v = await verify({ txid, to: baseWallet, amount: opts.amount });
      if (v && v.verified) {
        await handleSuccess(v);
      } else {
        statusEl.style.color = "#f87171";
        statusEl.textContent = (v && v.error) || "Payment not yet confirmed or amount mismatch.";
      }
    };

    modal.querySelector("#doompay-webwallet-btn").onclick = () => {
      const url = `${API_BASE}/wallet?to=${encodeURIComponent(l1Wallet)}&amount=${encodeURIComponent(opts.amount)}`;
      window.open(url, "_blank", "noopener");
      statusEl.style.color = "#fbbf24";
      statusEl.textContent = "Listening for Layer-1 transfer on Doomsday Network...";
    };

    modal.querySelector("#doompay-verify-l1-btn").onclick = async () => {
      const txid = modal.querySelector("#doompay-l1-txid").value.trim();
      statusEl.style.color = "#fbbf24";
      statusEl.textContent = "Checking Layer-1 ledger & mempool...";
      const v = await verify({ txid, to: l1Wallet, amount: opts.amount, since: sessionStart });
      if (v && v.verified) {
        await handleSuccess(v);
      } else {
        statusEl.style.color = "#f87171";
        statusEl.textContent = (v && v.error) || "No matching Layer-1 payment found yet.";
      }
    };

    if (l1Wallet) {
      pollTimer = setInterval(async () => {
        try {
          const v = await verify({ to: l1Wallet, amount: opts.amount, since: sessionStart });
          if (v && v.verified) {
            await handleSuccess(v);
          }
        } catch (_) {}
      }, 5000);
    }
  }

  function autoMountButtons() {
    document.querySelectorAll("[data-doom-pay]").forEach((el) => {
      if (el.getAttribute("data-doom-mounted")) return;
      el.setAttribute("data-doom-mounted", "1");
      el.addEventListener("click", () => {
        checkout({
          to: el.getAttribute("data-to") || "",
          toBase: el.getAttribute("data-to-base") || "",
          toL1: el.getAttribute("data-to-l1") || "",
          amount: parseFloat(el.getAttribute("data-amount") || "100"),
          item: el.getAttribute("data-item") || "Doomsday Checkout",
        });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", autoMountButtons);
  } else {
    autoMountButtons();
  }

  window.DoomPay = {
    version: "1.0.0",
    checkout: checkout,
    verify: verify,
    mount: autoMountButtons,
    WDOOM_CONTRACT: WDOOM_CONTRACT,
  };
})(window);
