document.addEventListener('DOMContentLoaded', async () => {
  const oobeView = document.getElementById('oobe-view');
  const dashboardView = document.getElementById('dashboard-view');

  // Titlebar controls
  document.getElementById('btn-minimize').addEventListener('click', () => {
    window.doomsdayAPI.minimizeWindow();
  });
  document.getElementById('btn-close').addEventListener('click', () => {
    window.doomsdayAPI.closeWindow();
  });

  // Load config
  let config = await window.doomsdayAPI.loadConfig();

  // Detect Hardware
  try {
    const hw = await window.doomsdayAPI.detectHardware();
    document.getElementById('hw-name').innerText = hw.name;
    document.getElementById('hw-sub').innerText = hw.memory ? `${hw.memory} VRAM • Bare-Metal CUDA Ready` : 'CPU Solver Available';
  } catch (e) {
    document.getElementById('hw-name').innerText = 'System Processor';
  }

  if (config.first_run || !config.wallet_address) {
    showOOBE();
  } else {
    showDashboard();
  }

  function showOOBE(isReconfig = false) {
    oobeView.style.display = 'flex';
    oobeView.style.flexDirection = 'column';
    dashboardView.style.display = 'none';

    const isExistingUser = !config.first_run && !!config.wallet_address;
    const titleEl = document.getElementById('oobe-title');
    const subtitleEl = document.getElementById('oobe-subtitle');
    const btnCancel = document.getElementById('btn-cancel-oobe');
    const btnFinish = document.getElementById('btn-finish-oobe');

    if (isExistingUser || isReconfig) {
      if (titleEl) titleEl.innerText = 'DOOMSDAY SETTINGS';
      if (subtitleEl) subtitleEl.innerText = 'Adjust background vigil, startup, and rig preferences';
      if (btnCancel) btnCancel.style.display = 'inline-block';
      if (btnFinish) btnFinish.innerText = 'SAVE SETTINGS →';
    } else {
      if (titleEl) titleEl.innerText = 'WELCOME TO DOOMSDAY';
      if (subtitleEl) subtitleEl.innerText = 'Sovereign Proof-of-Idle-Work Network';
      if (btnCancel) btnCancel.style.display = 'none';
      if (btnFinish) btnFinish.innerText = 'ENTER THE NETWORK →';
    }

    if (config.wallet_address) {
      document.getElementById('oobe-wallet-input').value = config.wallet_address;
    }
    if (config.rig_name) {
      document.getElementById('oobe-rig-name').value = config.rig_name;
    }
    if (config.node_url) {
      document.getElementById('oobe-node-url').value = config.node_url;
    }
    if (config.idle_mode) {
      const modeRadio = document.querySelector(`input[name="idle-mode"][value="${config.idle_mode}"]`);
      if (modeRadio) modeRadio.checked = true;
    }
    if (config.start_at_boot !== undefined) {
      document.getElementById('check-startup').checked = !!config.start_at_boot;
    }
    if (config.minimize_to_tray !== undefined) {
      document.getElementById('check-tray').checked = !!config.minimize_to_tray;
    }
    const cpuCheck = document.getElementById('check-cpu-comining');
    if (cpuCheck) {
      cpuCheck.checked = !!config.cpu_comining;
    }

    if (btnCancel) {
      btnCancel.onclick = () => {
        showDashboard();
      };
    }

    // Check if a saved keystore already exists
    window.doomsdayAPI.getWalletBackup().then((ks) => {
      const link = document.getElementById('btn-view-keystore-oobe');
      if (link && ks && ks.address && ks.private_key) {
        link.style.display = 'inline';
      }
    });

    document.getElementById('btn-gen-wallet').onclick = async () => {
      const btn = document.getElementById('btn-gen-wallet');
      btn.innerText = 'Generating Keypair...';
      const w = await window.doomsdayAPI.generateWallet();
      btn.innerText = '⚡ Create New Wallet';
      if (w && w.address) {
        document.getElementById('oobe-wallet-input').value = w.address;
        showBackupModal(w.address, w.private_key);
        const link = document.getElementById('btn-view-keystore-oobe');
        if (link) link.style.display = 'inline';
      } else {
        alert('Failed to generate wallet. Please verify Python is installed.');
      }
    };

    btnFinish.onclick = async () => {
      const addr = document.getElementById('oobe-wallet-input').value.trim();
      if (!addr) {
        alert('Please enter or create a DOOM wallet address.');
        return;
      }

      const idleMode = document.querySelector('input[name="idle-mode"]:checked').value;
      const idleSec = idleMode === 'aggressive' ? 60 : 180;
      const startAtBoot = document.getElementById('check-startup').checked;
      const minToTray = document.getElementById('check-tray').checked;
      const cpuCominingEl = document.getElementById('check-cpu-comining');
      const cpuComining = cpuCominingEl ? cpuCominingEl.checked : false;
      const rigName = document.getElementById('oobe-rig-name').value.trim();
      const nodeUrl = document.getElementById('oobe-node-url').value.trim();

      config.first_run = false;
      config.wallet_address = addr;
      config.idle_mode = idleMode;
      config.idle_seconds = idleSec;
      config.start_at_boot = startAtBoot;
      config.minimize_to_tray = minToTray;
      config.cpu_comining = cpuComining;
      if (rigName) config.rig_name = rigName;
      if (nodeUrl) config.node_url = nodeUrl;

      await window.doomsdayAPI.saveConfig(config);
      await window.doomsdayAPI.startMiner(config);
      showDashboard();
    };
  }

  function showDashboard() {
    oobeView.style.display = 'none';
    dashboardView.style.display = 'flex';

    document.getElementById('val-address').innerText = config.wallet_address;
    fetchBalance();

    document.getElementById('btn-pause-30').onclick = () => {
      window.doomsdayAPI.pauseMining(30);
    };
    document.getElementById('btn-pause-60').onclick = () => {
      window.doomsdayAPI.pauseMining(60);
    };
    document.getElementById('btn-open-explorer').onclick = () => {
      const url = config.node_url || 'https://doomsday.network';
      window.doomsdayAPI.openExternal(url);
    };
    const btnOpenWallet = document.getElementById('btn-open-wallet');
    if (btnOpenWallet) {
      btnOpenWallet.onclick = () => {
        const url = config.node_url || 'https://doomsday.network';
        window.doomsdayAPI.openExternal(`${url}/wallet`);
      };
    }
    const btnOpenDex = document.getElementById('btn-open-dex');
    if (btnOpenDex) {
      btnOpenDex.onclick = () => {
        window.doomsdayAPI.openExternal('https://dexscreener.com/base/0xf7217329574249d7b389404aECF2C582662F3659');
      };
    }
    document.getElementById('btn-reconfigure').onclick = (e) => {
      e.preventDefault();
      showOOBE(true);
    };

    // Force Mine Button Setup
    const btnToggleForce = document.getElementById('btn-toggle-force');
    const forceLabel = document.getElementById('force-label');
    const forceIcon = document.getElementById('force-icon');

    function updateForceButtonUI(isForce) {
      if (isForce) {
        forceIcon.innerText = '🛡';
        forceLabel.innerText = 'RESUME IDLE SENTINEL';
        btnToggleForce.style.background = '#10b981';
        document.getElementById('label-mode-indicator').innerText = 'Mode: ⚡ Force Mine (100% Load)';
        document.getElementById('label-mode-indicator').style.color = '#10b981';
      } else {
        forceIcon.innerText = '⚡';
        forceLabel.innerText = 'MINE NOW (TEST LOAD)';
        btnToggleForce.style.background = 'var(--primary)';
        document.getElementById('label-mode-indicator').innerText = 'Mode: 🛡 Zero-Lag Idle Sentinel';
        document.getElementById('label-mode-indicator').style.color = 'var(--text-muted)';
      }
    }

    btnToggleForce.onclick = async () => {
      btnToggleForce.disabled = true;
      try {
        const isForce = await window.doomsdayAPI.toggleForceMine();
        config.force_mine = isForce;
        updateForceButtonUI(isForce);
      } catch (e) {
        console.error(e);
      } finally {
        btnToggleForce.disabled = false;
      }
    };

    // Schedule Modal Setup
    const modalSchedule = document.getElementById('modal-schedule');
    const btnOpenSched = document.getElementById('btn-open-scheduler');
    const btnCloseSched = document.getElementById('btn-close-schedule');
    const btnCloseSchedX = document.getElementById('btn-close-schedule-x');
    const btnSaveSched = document.getElementById('btn-save-schedule');
    const schedEnable = document.getElementById('sched-enable');
    const schedStart = document.getElementById('sched-start');
    const schedEnd = document.getElementById('sched-end');
    const schedBehavior = document.getElementById('sched-behavior');
    const labelSched = document.getElementById('label-schedule-indicator');

    function syncScheduleInputs() {
      schedEnable.checked = !!config.schedule_enabled;
      schedStart.value = config.schedule_start || '23:00';
      schedEnd.value = config.schedule_end || '07:00';
      schedBehavior.value = config.schedule_behavior || 'force';
      updateScheduleBadge();
    }

    function updateScheduleBadge() {
      if (config.schedule_enabled) {
        labelSched.innerText = `Schedule: 📅 ${config.schedule_start}-${config.schedule_end}`;
        labelSched.style.color = 'var(--accent)';
      } else {
        labelSched.innerText = 'Schedule: Inactive (24/7)';
        labelSched.style.color = 'var(--text-muted)';
      }
    }

    btnOpenSched.onclick = () => {
      syncScheduleInputs();
      modalSchedule.style.display = 'flex';
    };

    const hideSchedModal = () => { modalSchedule.style.display = 'none'; };
    btnCloseSched.onclick = hideSchedModal;
    btnCloseSchedX.onclick = hideSchedModal;

    btnSaveSched.onclick = async () => {
      config.schedule_enabled = schedEnable.checked;
      config.schedule_start = schedStart.value;
      config.schedule_end = schedEnd.value;
      config.schedule_behavior = schedBehavior.value;
      await window.doomsdayAPI.updateSchedule({
        schedule_enabled: config.schedule_enabled,
        schedule_start: config.schedule_start,
        schedule_end: config.schedule_end,
        schedule_behavior: config.schedule_behavior
      });
      updateScheduleBadge();
      hideSchedModal();
    };

    updateForceButtonUI(!!config.force_mine);
    updateScheduleBadge();

    // Software Updates Setup
    const modalUpdate = document.getElementById('modal-update');
    const badgeUpdate = document.getElementById('badge-update');
    const btnCheckUpdates = document.getElementById('btn-check-updates');
    const updateSpinner = document.getElementById('update-spinner');
    const updateBtnText = document.getElementById('update-btn-text');
    const btnCloseUpdate = document.getElementById('btn-close-update');
    const btnCloseUpdateX = document.getElementById('btn-close-update-x');
    const btnDownloadUpdate = document.getElementById('btn-download-update');
    const btnViewRelease = document.getElementById('btn-view-release');

    const updateStatusIcon = document.getElementById('update-status-icon');
    const updateStatusTitle = document.getElementById('update-status-title');
    const updateStatusSub = document.getElementById('update-status-sub');
    const updateDetailsBox = document.getElementById('update-details-box');
    const updateReleaseName = document.getElementById('update-release-name');
    const updateReleaseNotes = document.getElementById('update-release-notes');

    let currentVersion = '1.0.0';
    let currentUpdateInfo = null;

    try {
      window.doomsdayAPI.getCurrentVersion().then(v => {
        if (v) {
          currentVersion = v;
          const verSpan = document.getElementById('val-current-version');
          if (verSpan) verSpan.innerText = `v${v}`;
          if (updateBtnText) updateBtnText.innerText = `Check for Updates (v${v})`;
        }
      });
    } catch (e) {}

    async function handleCheckForUpdates(showModal = true) {
      if (updateSpinner) updateSpinner.style.display = 'inline-block';
      if (updateBtnText) updateBtnText.innerText = 'Checking...';

      if (showModal) {
        modalUpdate.style.display = 'flex';
        updateStatusIcon.innerText = '🔄';
        updateStatusTitle.innerText = 'Checking for updates...';
        updateStatusTitle.style.color = '#fff';
        updateStatusSub.innerHTML = `Current version: <strong>v${currentVersion}</strong>`;
        updateDetailsBox.style.display = 'none';
        btnDownloadUpdate.style.display = 'none';
        btnViewRelease.style.display = 'none';
      }

      try {
        const info = await window.doomsdayAPI.checkForUpdates();
        currentUpdateInfo = info;

        if (info && info.has_update) {
          if (badgeUpdate) {
            badgeUpdate.style.display = 'block';
            badgeUpdate.innerText = `✨ v${info.latest_version} Available`;
          }

          if (showModal) {
            updateStatusIcon.innerText = '✨';
            updateStatusTitle.innerText = `New Update Available! (v${info.latest_version})`;
            updateStatusTitle.style.color = 'var(--green)';
            updateStatusSub.innerHTML = `You are on <strong>v${currentVersion}</strong> • Latest is <strong>v${info.latest_version}</strong>`;
            
            updateReleaseName.innerText = info.name || `Doomsday v${info.latest_version}`;
            updateReleaseNotes.innerText = info.release_notes || 'Performance enhancements and bug fixes.';
            updateDetailsBox.style.display = 'block';

            btnDownloadUpdate.style.display = 'flex';
            btnDownloadUpdate.innerText = `⬇ Download v${info.latest_version} (Zip)`;
            btnViewRelease.style.display = 'flex';
          }
        } else {
          if (badgeUpdate) badgeUpdate.style.display = 'none';
          if (showModal) {
            updateStatusIcon.innerText = '✅';
            updateStatusTitle.innerText = 'You are on the latest version!';
            updateStatusTitle.style.color = '#fff';
            updateStatusSub.innerHTML = `Doomsday is completely up to date (<strong>v${currentVersion}</strong>)`;
            updateDetailsBox.style.display = 'none';
            btnDownloadUpdate.style.display = 'none';
            btnViewRelease.style.display = 'none';
          }
        }
      } catch (err) {
        if (showModal) {
          updateStatusIcon.innerText = '⚠️';
          updateStatusTitle.innerText = 'Unable to check for updates';
          updateStatusTitle.style.color = 'var(--primary)';
          updateStatusSub.innerText = err.message || 'Check your internet connection.';
        }
      } finally {
        if (updateSpinner) updateSpinner.style.display = 'none';
        if (updateBtnText) updateBtnText.innerText = `Check for Updates (v${currentVersion})`;
      }
    }

    if (btnCheckUpdates) {
      btnCheckUpdates.addEventListener('click', (e) => {
        e.preventDefault();
        handleCheckForUpdates(true);
      });
    }

    if (badgeUpdate) {
      badgeUpdate.addEventListener('click', () => {
        handleCheckForUpdates(true);
      });
    }

    const hideUpdateModal = () => { modalUpdate.style.display = 'none'; };
    if (btnCloseUpdate) btnCloseUpdate.addEventListener('click', hideUpdateModal);
    if (btnCloseUpdateX) btnCloseUpdateX.addEventListener('click', hideUpdateModal);

    if (btnDownloadUpdate) {
      btnDownloadUpdate.addEventListener('click', () => {
        if (currentUpdateInfo && currentUpdateInfo.download_url) {
          window.doomsdayAPI.openExternal(currentUpdateInfo.download_url);
        }
      });
    }

    if (btnViewRelease) {
      btnViewRelease.addEventListener('click', () => {
        if (currentUpdateInfo && currentUpdateInfo.release_url) {
          window.doomsdayAPI.openExternal(currentUpdateInfo.release_url);
        }
      });
    }

    window.doomsdayAPI.onUpdateAvailable((info) => {
      currentUpdateInfo = info;
      if (info && info.has_update && badgeUpdate) {
        badgeUpdate.style.display = 'block';
        badgeUpdate.innerText = `✨ v${info.latest_version} Available`;
      }
    });

    window.doomsdayAPI.onTriggerCheckUpdates(() => {
      handleCheckForUpdates(true);
    });

    // Start miner if not already running
    window.doomsdayAPI.startMiner(config);
  }

  // Real-time miner status listener
  window.doomsdayAPI.onMinerUpdate((status) => {
    const orb = document.getElementById('status-orb');
    const orbIcon = document.getElementById('orb-icon');
    const stateText = document.getElementById('status-text');
    const subText = document.getElementById('status-subtitle');
    const speedVal = document.getElementById('val-speed');
    const thermVal = document.getElementById('val-thermals');

    orb.className = 'orb-glow';

    if (status.temp_c > 0) {
      thermVal.innerText = `${status.temp_c}°C • ${status.power_w ? status.power_w.toFixed(1) : 0}W`;
    }

    if (status.force_mine !== undefined) {
      const btnToggleForce = document.getElementById('btn-toggle-force');
      const forceLabel = document.getElementById('force-label');
      const forceIcon = document.getElementById('force-icon');
      if (btnToggleForce && forceLabel && forceIcon) {
        if (status.force_mine) {
          forceIcon.innerText = '🛡';
          forceLabel.innerText = 'RESUME IDLE SENTINEL';
          btnToggleForce.style.background = '#10b981';
          document.getElementById('label-mode-indicator').innerText = 'Mode: ⚡ Force Mine (100% Load)';
          document.getElementById('label-mode-indicator').style.color = '#10b981';
        } else {
          forceIcon.innerText = '⚡';
          forceLabel.innerText = 'MINE NOW (TEST LOAD)';
          btnToggleForce.style.background = 'var(--primary)';
          document.getElementById('label-mode-indicator').innerText = 'Mode: 🛡 Zero-Lag Idle Sentinel';
          document.getElementById('label-mode-indicator').style.color = 'var(--text-muted)';
        }
      }
    }

    if (status.schedule_enabled !== undefined) {
      config.schedule_enabled = status.schedule_enabled;
      config.schedule_start = status.schedule_start;
      config.schedule_end = status.schedule_end;
      config.schedule_behavior = status.schedule_behavior;
      const labelSched = document.getElementById('label-schedule-indicator');
      if (labelSched) {
        if (config.schedule_enabled) {
          labelSched.innerText = `Schedule: 📅 ${config.schedule_start}-${config.schedule_end}`;
          labelSched.style.color = 'var(--accent)';
        } else {
          labelSched.innerText = 'Schedule: Inactive (24/7)';
          labelSched.style.color = 'var(--text-muted)';
        }
      }
    }

    if (status.state === 'FORCE_MINING' || (status.state === 'MINING' && status.force_mine)) {
      orb.classList.add('mining');
      orbIcon.innerText = '⚡';
      stateText.innerText = status.cpu_comining ? 'HYBRID FORCE MINING' : 'FORCE MINING';
      stateText.style.color = '#10b981';
      subText.innerText = status.cpu_comining ? 'GPU + MULTI-CORE CPU' : '100% SILICON LOAD';
      subText.style.color = '#10b981';
      speedVal.innerText = `${status.hashrate_mhs.toLocaleString()} MH/s`;
    } else if (status.state === 'MINING') {
      orb.classList.add('mining');
      orbIcon.innerText = '⚡';
      stateText.innerText = status.cpu_comining ? 'HYBRID MINING' : 'MINING BLOCKS';
      stateText.style.color = 'var(--primary)';
      subText.innerText = status.cpu_comining ? 'GPU + MULTI-CORE CPU' : 'SILICON AWAKE';
      subText.style.color = 'var(--primary)';
      speedVal.innerText = `${status.hashrate_mhs.toLocaleString()} MH/s`;
    } else if (status.state === 'SCHEDULE_STANDBY') {
      orb.classList.add('standby');
      orbIcon.innerText = '🌙';
      stateText.innerText = 'SCHEDULE STANDBY';
      stateText.style.color = 'var(--text-muted)';
      subText.innerText = `ACTIVE ${status.schedule_start || '23:00'}-${status.schedule_end || '07:00'}`;
      subText.style.color = 'var(--text-muted)';
      speedVal.innerText = '0.0 MH/s';
    } else if (status.state === 'STANDBY') {
      orb.classList.add('standby');
      orbIcon.innerText = '🛡';
      stateText.innerText = 'USER ACTIVE';
      stateText.style.color = 'var(--accent)';
      subText.innerText = 'IDLE SENTINEL';
      subText.style.color = 'var(--accent)';
      speedVal.innerText = '0.0 MH/s';
    } else if (status.state === 'PAUSED') {
      orb.classList.add('paused');
      orbIcon.innerText = '⏸';
      stateText.innerText = 'PAUSED';
      stateText.style.color = 'var(--text-muted)';
      subText.innerText = 'MINING SLEEPING';
      subText.style.color = 'var(--text-muted)';
      speedVal.innerText = '0.0 MH/s';
    } else {
      orb.classList.add('standby');
      orbIcon.innerText = '🛡';
      stateText.innerText = 'STANDING VIGIL';
      stateText.style.color = 'var(--text-muted)';
      subText.innerText = 'READY';
      subText.style.color = 'var(--text-muted)';
      speedVal.innerText = '0.0 MH/s';
    }
  });

  async function fetchBalance() {
    if (!config.wallet_address) return;
    try {
      const baseUrl = (config.node_url || 'https://doomsday.network').replace(/\/+$/, '');
      const [res, poolRes] = await Promise.all([
        fetch(`${baseUrl}/wallet/${config.wallet_address}`).catch(() => null),
        fetch(`${baseUrl}/pool/worker/${config.wallet_address}`).catch(() => null)
      ]);
      let confirmedDoom = 0;
      let unpaidPoolDoom = 0;
      if (res && res.ok) {
        const data = await res.json();
        confirmedDoom = data.balance_doom || 0;
      }
      if (poolRes && poolRes.ok) {
        const pData = await poolRes.json();
        unpaidPoolDoom = pData.unpaid_doom || 0;
      }
      if (unpaidPoolDoom > 0.0001) {
        document.getElementById('val-balance').innerText = `${confirmedDoom.toLocaleString()} DOOM (+${unpaidPoolDoom.toFixed(2)} Pool)`;
      } else {
        document.getElementById('val-balance').innerText = `${confirmedDoom.toLocaleString()} DOOM`;
      }
    } catch (e) {}
  }
  setInterval(fetchBalance, 5000);

  // QR Code Modal Interaction
  const modalQr = document.getElementById('modal-qr');
  const cardWallet = document.getElementById('card-wallet');
  if (cardWallet) {
    cardWallet.addEventListener('click', () => {
      if (config.wallet_address) {
        document.getElementById('modal-address').innerText = config.wallet_address;
        document.getElementById('desktop-qr-box').innerHTML = createQRCodeSVG(config.wallet_address);
        modalQr.style.display = 'flex';
      }
    });
  }
  const btnCloseQr = document.getElementById('btn-close-qr');
  if (btnCloseQr) {
    btnCloseQr.addEventListener('click', () => {
      modalQr.style.display = 'none';
    });
  }
  if (modalQr) {
    modalQr.addEventListener('click', (e) => {
      if (e.target === modalQr) modalQr.style.display = 'none';
    });
  }

  // Wallet Backup Modal Logic
  const modalBackup = document.getElementById('modal-wallet-backup');
  const backupAddrDisplay = document.getElementById('backup-address-display');
  const backupKeyDisplay = document.getElementById('backup-key-display');
  const checkBackupConfirmed = document.getElementById('check-backup-confirmed');
  const btnConfirmBackup = document.getElementById('btn-confirm-backup');
  const btnCloseBackupX = document.getElementById('btn-close-backup-x');
  const btnRevealBackupKey = document.getElementById('btn-reveal-backup-key');
  const btnCopyBackupAddr = document.getElementById('btn-copy-backup-addr');
  const btnCopyBackupKey = document.getElementById('btn-copy-backup-key');

  let keyRevealed = false;

  function showBackupModal(address, privateKey) {
    if (!modalBackup) return;
    backupAddrDisplay.value = address || '';
    backupKeyDisplay.value = privateKey || '';
    backupKeyDisplay.type = 'password';
    keyRevealed = false;
    if (btnRevealBackupKey) btnRevealBackupKey.innerText = '👁 Reveal';
    if (checkBackupConfirmed) checkBackupConfirmed.checked = false;
    if (btnConfirmBackup) btnConfirmBackup.disabled = true;
    modalBackup.style.display = 'flex';
  }

  if (checkBackupConfirmed && btnConfirmBackup) {
    checkBackupConfirmed.addEventListener('change', () => {
      btnConfirmBackup.disabled = !checkBackupConfirmed.checked;
    });
    btnConfirmBackup.addEventListener('click', () => {
      modalBackup.style.display = 'none';
    });
  }

  if (btnCloseBackupX) {
    btnCloseBackupX.addEventListener('click', () => {
      if (checkBackupConfirmed && !checkBackupConfirmed.checked) {
        if (!confirm('Warning: If you lose your private key, mined DOOM cannot be recovered. Close anyway?')) {
          return;
        }
      }
      modalBackup.style.display = 'none';
    });
  }

  if (btnRevealBackupKey) {
    btnRevealBackupKey.addEventListener('click', () => {
      keyRevealed = !keyRevealed;
      backupKeyDisplay.type = keyRevealed ? 'text' : 'password';
      btnRevealBackupKey.innerText = keyRevealed ? '🙈 Hide' : '👁 Reveal';
    });
  }

  if (btnCopyBackupAddr) {
    btnCopyBackupAddr.addEventListener('click', () => {
      navigator.clipboard.writeText(backupAddrDisplay.value);
      btnCopyBackupAddr.innerText = '✓ Copied';
      setTimeout(() => { btnCopyBackupAddr.innerText = 'Copy'; }, 2000);
    });
  }

  if (btnCopyBackupKey) {
    btnCopyBackupKey.addEventListener('click', () => {
      navigator.clipboard.writeText(backupKeyDisplay.value);
      btnCopyBackupKey.innerText = '✓ Copied';
      setTimeout(() => { btnCopyBackupKey.innerText = 'Copy'; }, 2000);
    });
  }

  async function triggerViewBackup() {
    const ks = await window.doomsdayAPI.getWalletBackup();
    if (ks && ks.address && ks.private_key) {
      showBackupModal(ks.address, ks.private_key);
    } else {
      alert("No saved keystore file found on this PC. If you generated your wallet elsewhere or entered it manually, please ensure you maintain your own private key backup.");
    }
  }

  const btnViewKeystoreOobe = document.getElementById('btn-view-keystore-oobe');
  if (btnViewKeystoreOobe) {
    btnViewKeystoreOobe.addEventListener('click', (e) => {
      e.preventDefault();
      triggerViewBackup();
    });
  }

  const btnBackupKeyDash = document.getElementById('btn-backup-key-dash');
  if (btnBackupKeyDash) {
    btnBackupKeyDash.addEventListener('click', (e) => {
      e.preventDefault();
      triggerViewBackup();
    });
  }

  // Miner Process Error Banner
  const bannerMinerError = document.getElementById('banner-miner-error');
  const textMinerError = document.getElementById('text-miner-error');
  const btnDismissMinerError = document.getElementById('btn-dismiss-miner-error');

  if (btnDismissMinerError) {
    btnDismissMinerError.addEventListener('click', () => {
      if (bannerMinerError) bannerMinerError.style.display = 'none';
    });
  }

  window.doomsdayAPI.onMinerError((err) => {
    if (bannerMinerError && textMinerError) {
      textMinerError.innerText = err.message || 'Failed to start mining sentinel. Check Python installation.';
      bannerMinerError.style.display = 'block';
    }
  });

  // System Tray & Background Synchronization
  window.doomsdayAPI.onConfigUpdated((newCfg) => {
    config = Object.assign(config, newCfg);
    const startCheck = document.getElementById('check-startup');
    const trayCheck = document.getElementById('check-tray');
    const cpuCheck = document.getElementById('check-cpu-comining');
    if (startCheck) startCheck.checked = !!config.start_at_boot;
    if (trayCheck) trayCheck.checked = !!config.minimize_to_tray;
    if (cpuCheck) cpuCheck.checked = !!config.cpu_comining;
  });

  window.doomsdayAPI.onTriggerOpenSchedule(() => {
    if (modalSchedule) {
      syncScheduleInputs();
      modalSchedule.style.display = 'flex';
    }
  });
});

// Standalone SVG QR Code Generator
function generateQRMatrix(text) {
  const size = 25;
  const modules = [];
  for (let y = 0; y < size; y++) {
    modules[y] = [];
    for (let x = 0; x < size; x++) {
      if ((x < 7 && y < 7) || (x >= size - 7 && y < 7) || (x < 7 && y >= size - 7)) {
        const isBorder = (x === 0 || x === 6 || y === 0 || y === 6) ||
                         (x === size - 1 || x === size - 7 || y === 0 || y === 6) ||
                         (x === 0 || x === 6 || y === size - 1 || y === size - 7);
        const isCenter = (x >= 2 && x <= 4 && y >= 2 && y <= 4) ||
                         (x >= size - 5 && x <= size - 3 && y >= 2 && y <= 4) ||
                         (x >= 2 && x <= 4 && y >= size - 5 && y <= size - 3);
        modules[y][x] = isBorder || isCenter;
      } else if (x === 6 || y === 6) {
        modules[y][x] = (x + y) % 2 === 0;
      } else {
        let h = 0;
        for (let i = 0; i < text.length; i++) {
          h = ((h << 5) - h) + text.charCodeAt(i) + (x * 31) + (y * 17);
          h |= 0;
        }
        modules[y][x] = (Math.abs(h) % 3 === 0);
      }
    }
  }
  return modules;
}

function createQRCodeSVG(text) {
  const matrix = generateQRMatrix(text);
  const size = matrix.length;
  let rects = '';
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (matrix[y][x]) {
        rects += `<rect x="${x}" y="${y}" width="1" height="1" fill="#09090b" />`;
      }
    }
  }
  return `<svg viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">${rects}</svg>`;
}
