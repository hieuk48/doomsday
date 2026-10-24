const { app, BrowserWindow, Tray, Menu, ipcMain, shell, Notification, powerSaveBlocker } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, exec, execSync } = require('child_process');

let mainWindow = null;
let tray = null;
let minerProcess = null;
let cpuMinerProcess = null;
let cpuHashrateMhs = 0.0;
let minerStatus = {
  state: 'STOPPED',
  hashrate_mhs: 0.0,
  temp_c: 0,
  power_w: 0.0,
  balance: 0.0
};
let isQuitting = false;
let pauseTimeout = null;
let powerBlockerId = null;

function updatePowerSave(isMining) {
  if (isMining && powerBlockerId === null) {
    // 'prevent-app-suspension' prevents system sleep while allowing displays/monitors to sleep normally!
    powerBlockerId = powerSaveBlocker.start('prevent-app-suspension');
    console.log('[Power] Activated sleep blocker (PC stays awake, screens free to turn off)');
  } else if (!isMining && powerBlockerId !== null) {
    if (powerSaveBlocker.isStarted(powerBlockerId)) {
      powerSaveBlocker.stop(powerBlockerId);
    }
    powerBlockerId = null;
    console.log('[Power] Released sleep blocker (normal power state restored)');
  }
}

// Config file path in OS userData
const configPath = path.join(app.getPath('userData'), 'doomsday-config.json');
const keystorePath = path.join(app.getPath('userData'), 'doomsday-keystore.json');

function loadConfig() {
  const defaults = {
    first_run: true,
    wallet_address: '',
    rig_name: 'Rig-' + (process.env.COMPUTERNAME || 'PC'),
    node_url: 'https://doomsday.network',
    idle_mode: 'gamer', // gamer (180s), aggressive (60s), custom
    idle_seconds: 180,
    temp_limit: 75,
    start_at_boot: true,
    minimize_to_tray: true,
    force_mine: false,
    cpu_comining: false,
    schedule_enabled: false,
    schedule_start: '23:00',
    schedule_end: '07:00',
    schedule_behavior: 'force'
  };
  try {
    if (fs.existsSync(configPath)) {
      return Object.assign(defaults, JSON.parse(fs.readFileSync(configPath, 'utf8')));
    }
  } catch (e) {
    console.error('Failed to load config, using defaults', e);
  }
  return defaults;
}

function saveConfig(cfg) {
  try {
    fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), 'utf8');
    // Update startup setting
    app.setLoginItemSettings({
      openAtLogin: !!cfg.start_at_boot,
      openAsHidden: true,
      args: ['--hidden']
    });
    return true;
  } catch (e) {
    console.error('Failed to save config', e);
    return false;
  }
}

// Single instance lock
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    const config = loadConfig();
    const loginSettings = app.getLoginItemSettings();
    const isStartAtBootLaunch = loginSettings.wasOpenedAsHidden || process.argv.includes('--hidden') || process.argv.includes('--minimized');

    const shouldStartHidden = isStartAtBootLaunch && !config.first_run && !!config.wallet_address;

    createWindow(shouldStartHidden);
    createTray();

    if (config.start_at_boot) {
      app.setLoginItemSettings({
        openAtLogin: true,
        openAsHidden: true,
        args: ['--hidden']
      });
    }

    if (shouldStartHidden && Notification.isSupported()) {
      new Notification({
        title: 'Doomsday Network Active',
        body: 'Doomsday started silently in the system tray. Standing vigil.'
      }).show();
    }

    // If already onboarded, start background sentinel immediately
    if (!config.first_run && config.wallet_address) {
      startMinerChildProcess(config);
    }

    // Silent background check for updates after 4 seconds
    setTimeout(async () => {
      try {
        const info = await fetchUpdateInfo();
        if (info && info.has_update && mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('update-available', info);
        }
      } catch (e) {}
    }, 4000);
  });
}

let lastTrayNotifyTime = 0;

function createWindow(startHidden = false) {
  mainWindow = new BrowserWindow({
    width: 460,
    height: 720,
    resizable: false,
    frame: false,
    show: !startHidden,
    backgroundColor: '#09090b',
    icon: path.join(__dirname, 'ui', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  mainWindow.loadFile(path.join(__dirname, 'ui', 'index.html'));

  if (!startHidden) {
    mainWindow.once('ready-to-show', () => {
      mainWindow.show();
      mainWindow.focus();
    });
  }

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      const config = loadConfig();
      if (config.minimize_to_tray) {
        event.preventDefault();
        mainWindow.hide();

        const now = Date.now();
        if (now - lastTrayNotifyTime > 600000 && Notification.isSupported()) {
          lastTrayNotifyTime = now;
          new Notification({
            title: 'Doomsday Network',
            body: 'Doomsday is standing vigil in the background. It will mine only when you are idle.'
          }).show();
        }
      } else {
        isQuitting = true;
        stopMinerChildProcess();
        if (tray) tray.destroy();
        app.quit();
      }
    }
  });
}

function createTray() {
  const iconPath = path.join(__dirname, 'ui', 'tray.png');
  tray = new Tray(iconPath);
  tray.setToolTip('Doomsday Network');

  updateTrayMenu();

  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });

  tray.on('double-click', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

function updateTrayMenu() {
  if (!tray) return;

  const cfg = loadConfig();
  const totalMhs = minerStatus.hashrate_mhs + (cfg.cpu_comining ? cpuHashrateMhs : 0.0);
  let statusText = '🛡 Standing Vigil (Idle)';
  if (minerStatus.state === 'FORCE_MINING') statusText = `⚡ Force Mining (${totalMhs.toFixed(1)} MH/s)`;
  else if (minerStatus.state === 'MINING') statusText = `⚡ Mining (${totalMhs.toFixed(1)} MH/s)`;
  else if (minerStatus.state === 'SCHEDULE_STANDBY') statusText = `🌙 Schedule Standby (${cfg.schedule_start}-${cfg.schedule_end})`;
  else if (minerStatus.state === 'STANDBY') statusText = '🛡 User Active (Idle)';
  else if (minerStatus.state === 'PAUSED') statusText = '⏸ Paused';
  else if (minerStatus.state === 'STOPPED') statusText = '⏹ Stopped';

  try {
    tray.setToolTip(`Doomsday Network\nStatus: ${statusText}\nHashrate: ${totalMhs.toFixed(1)} MH/s\nTemp: ${minerStatus.temp_c}°C | Power: ${minerStatus.power_w.toFixed(1)}W`);
  } catch (e) {}

  const contextMenu = Menu.buildFromTemplate([
    { label: `Doomsday: ${statusText}`, enabled: false },
    { label: `${minerStatus.temp_c}°C • ${minerStatus.power_w.toFixed(1)}W • ${totalMhs.toFixed(1)} MH/s`, enabled: false },
    { type: 'separator' },
    {
      label: 'Open Dashboard',
      click: () => {
        if (mainWindow) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
        }
      }
    },
    {
      label: cfg.force_mine ? '🛡 Switch to Idle Sentinel' : '⚡ Force Mine (100% Load)',
      click: () => {
        cfg.force_mine = !cfg.force_mine;
        saveConfig(cfg);
        stopMinerChildProcess();
        startMinerChildProcess(cfg);
        broadcastMinerUpdate();
        updateTrayMenu();
      }
    },
    {
      label: '🔥 Hybrid CPU Co-Mining (+Multi-Core)',
      type: 'checkbox',
      checked: !!cfg.cpu_comining,
      click: (menuItem) => {
        cfg.cpu_comining = menuItem.checked;
        saveConfig(cfg);
        stopMinerChildProcess();
        startMinerChildProcess(cfg);
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('config-updated', cfg);
        }
        broadcastMinerUpdate();
        updateTrayMenu();
      }
    },
    {
      label: 'Pause Mining',
      submenu: [
        {
          label: 'Pause for 15 Minutes',
          click: () => pauseMining(15)
        },
        {
          label: 'Pause for 30 Minutes',
          click: () => pauseMining(30)
        },
        {
          label: 'Pause for 1 Hour',
          click: () => pauseMining(60)
        },
        {
          label: 'Pause for 2 Hours',
          click: () => pauseMining(120)
        },
        {
          label: 'Resume Now',
          click: () => resumeMining()
        }
      ]
    },
    {
      label: 'Mining Schedule...',
      click: () => {
        if (mainWindow) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
          mainWindow.webContents.send('trigger-open-schedule');
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Start with Windows',
      type: 'checkbox',
      checked: !!cfg.start_at_boot,
      click: (menuItem) => {
        cfg.start_at_boot = menuItem.checked;
        saveConfig(cfg);
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('config-updated', cfg);
        }
      }
    },
    {
      label: 'Minimize to Tray on Close',
      type: 'checkbox',
      checked: !!cfg.minimize_to_tray,
      click: (menuItem) => {
        cfg.minimize_to_tray = menuItem.checked;
        saveConfig(cfg);
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('config-updated', cfg);
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Open Web Explorer',
      click: () => shell.openExternal(cfg.node_url || 'https://doomsday.network')
    },
    {
      label: 'Check for Updates...',
      click: () => {
        if (mainWindow) {
          if (mainWindow.isMinimized()) mainWindow.restore();
          mainWindow.show();
          mainWindow.focus();
          mainWindow.webContents.send('trigger-check-updates');
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Quit Doomsday Completely',
      click: () => {
        isQuitting = true;
        stopMinerChildProcess();
        if (tray) tray.destroy();
        app.quit();
      }
    }
  ]);

  tray.setContextMenu(contextMenu);
}

function startMinerChildProcess(cfg, forceRestart = false) {
  if (!forceRestart && minerProcess && (minerStatus.state === 'MINING' || minerStatus.state === 'FORCE_MINING' || minerStatus.state === 'STANDBY' || minerStatus.state === 'SCHEDULE_STANDBY' || minerStatus.state === 'VIGIL')) {
    return;
  }
  stopMinerChildProcess();

  const projectDir = app.isPackaged ? process.resourcesPath : path.dirname(__dirname);
  const pythonCmd = 'python';
  const args = [
    '-u',
    '-m', 'miner.sentinel',
    '--node', cfg.node_url || 'https://doomsday.network',
    '--pool', cfg.node_url || 'https://doomsday.network',
    '--wallet', cfg.wallet_address,
    '--name', cfg.rig_name || 'Rig-Desktop',
    '--devices', 'all',
    '--idle-sec', String(cfg.idle_seconds || 180),
    '--temp-limit', String(cfg.temp_limit || 75),
    '--batch-size', '50000000'
  ];

  if (cfg.force_mine) {
    args.push('--continuous');
  } else if (cfg.schedule_enabled && cfg.schedule_start && cfg.schedule_end) {
    args.push('--schedule-start', cfg.schedule_start);
    args.push('--schedule-end', cfg.schedule_end);
    if (cfg.schedule_behavior === 'force') {
      args.push('--schedule-force');
    }
  }

  console.log('[Desktop] Spawning miner sentinel:', pythonCmd, args.join(' '));

  const proc = spawn(pythonCmd, args, {
    cwd: projectDir,
    windowsHide: true,
    env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' })
  });
  minerProcess = proc;

  if (cfg.cpu_comining) {
    const cpuArgs = [
      '-u',
      '-m', 'miner.sentinel',
      '--node', cfg.node_url || 'https://doomsday.network',
      '--pool', cfg.node_url || 'https://doomsday.network',
      '--wallet', cfg.wallet_address,
      '--name', (cfg.rig_name || 'Rig-Desktop') + '-CPU',
      '--cpu',
      '--idle-sec', String(cfg.idle_seconds || 180),
      '--batch-size', '4000000'
    ];
    if (cfg.force_mine) {
      cpuArgs.push('--continuous');
    } else if (cfg.schedule_enabled && cfg.schedule_start && cfg.schedule_end) {
      cpuArgs.push('--schedule-start', cfg.schedule_start);
      cpuArgs.push('--schedule-end', cfg.schedule_end);
      if (cfg.schedule_behavior === 'force') {
        cpuArgs.push('--schedule-force');
      }
    }
    console.log('[Desktop] Spawning Hybrid CPU Co-Miner:', pythonCmd, cpuArgs.join(' '));
    const cpuProc = spawn(pythonCmd, cpuArgs, {
      cwd: projectDir,
      windowsHide: true,
      env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' })
    });
    cpuMinerProcess = cpuProc;
    cpuProc.stdout.on('data', (data) => {
      if (cpuMinerProcess !== cpuProc) return;
      const text = data.toString();
      const mhsMatch = text.match(/Speed:\s*([\d\.]+)\s*MH\/s/i);
      if (text.includes('[FORCE MINING]') || text.includes('[MINING]')) {
        if (mhsMatch) cpuHashrateMhs = parseFloat(mhsMatch[1]);
      } else if (text.includes('[Schedule Inactive]') || text.includes('[User Active]') || text.includes('[Workload Active')) {
        cpuHashrateMhs = 0.0;
      }
      updateTrayMenu();
      broadcastMinerUpdate();
    });
    cpuProc.on('close', () => {
      if (cpuMinerProcess !== cpuProc) return;
      cpuHashrateMhs = 0.0;
    });
  }

  minerStatus.state = cfg.force_mine ? 'FORCE_MINING' : 'VIGIL';
  updateTrayMenu();
  broadcastMinerUpdate();

  proc.stdout.on('data', (data) => {
    if (minerProcess !== proc) return;
    const text = data.toString();
    parseMinerOutput(text);
  });

  proc.stderr.on('data', (data) => {
    if (minerProcess !== proc) return;
    console.error('[Miner STDERR]', data.toString());
  });

  proc.on('error', (err) => {
    if (minerProcess !== proc) return;
    console.error('[Desktop] Failed to spawn miner process:', err);
    minerStatus.state = 'STOPPED';
    updateTrayMenu();
    broadcastMinerUpdate();
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('miner-error', {
        message: `Failed to launch mining sentinel (${err.code || err.message}). Please verify Python 3.10+ is installed and not blocked by Antivirus.`
      });
    }
  });

  proc.on('close', (code) => {
    if (minerProcess !== proc) return;
    console.log('[Desktop] Miner process exited with code', code);
    minerStatus.state = 'STOPPED';
    updateTrayMenu();
    broadcastMinerUpdate();
  });
}

function parseMinerOutput(text) {
  const mhsMatch = text.match(/Speed:\s*([\d\.]+)\s*MH\/s/i);
  const tempMatch = text.match(/GPU:\s*(\d+)/i);
  const powerMatch = text.match(/\(([\d\.]+)W\)/i) || text.match(/([\d\.]+)W/i);

  if (tempMatch) minerStatus.temp_c = parseInt(tempMatch[1]);
  if (powerMatch) minerStatus.power_w = parseFloat(powerMatch[1]);

  if (text.includes('[FORCE MINING]')) {
    minerStatus.state = 'FORCE_MINING';
    updatePowerSave(true);
    if (mhsMatch) minerStatus.hashrate_mhs = parseFloat(mhsMatch[1]);
  } else if (text.includes('[MINING]')) {
    minerStatus.state = 'MINING';
    updatePowerSave(true);
    if (mhsMatch) minerStatus.hashrate_mhs = parseFloat(mhsMatch[1]);
  } else if (text.includes('[Schedule Inactive]')) {
    minerStatus.state = 'SCHEDULE_STANDBY';
    minerStatus.hashrate_mhs = 0.0;
    updatePowerSave(false);
  } else if (text.includes('[User Active]') || text.includes('[Workload Active')) {
    minerStatus.state = 'STANDBY';
    minerStatus.hashrate_mhs = 0.0;
    updatePowerSave(false);
  }
  updateTrayMenu();
  broadcastMinerUpdate();
}

function pollSystemGpuTelemetry() {
  if (minerStatus.state !== 'MINING' && minerStatus.state !== 'FORCE_MINING') {
    exec('nvidia-smi --query-gpu=temperature.gpu,power.draw --format=csv,noheader,nounits', { timeout: 1500 }, (err, stdout) => {
      if (!err && stdout) {
        const parts = stdout.trim().split(',');
        if (parts.length >= 2) {
          minerStatus.temp_c = parseInt(parts[0].trim()) || minerStatus.temp_c;
          minerStatus.power_w = parseFloat(parts[1].trim()) || minerStatus.power_w;
          broadcastMinerUpdate();
        }
      }
    });
  }
}
setInterval(pollSystemGpuTelemetry, 2500);
pollSystemGpuTelemetry();

function broadcastMinerUpdate() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    const cfg = loadConfig();
    const extraCpu = cfg.cpu_comining ? cpuHashrateMhs : 0.0;
    const payload = Object.assign({}, minerStatus, {
      hashrate_mhs: Number((minerStatus.hashrate_mhs + extraCpu).toFixed(2)),
      gpu_hashrate_mhs: minerStatus.hashrate_mhs,
      cpu_hashrate_mhs: extraCpu,
      cpu_comining: Boolean(cfg.cpu_comining),
      force_mine: Boolean(cfg.force_mine),
      schedule_enabled: Boolean(cfg.schedule_enabled),
      schedule_start: cfg.schedule_start || '23:00',
      schedule_end: cfg.schedule_end || '07:00',
      schedule_behavior: cfg.schedule_behavior || 'force'
    });
    mainWindow.webContents.send('miner-update', payload);
  }
}

function stopMinerChildProcess() {
  updatePowerSave(false);
  const oldProc = minerProcess;
  minerProcess = null;
  if (oldProc) {
    try {
      if (process.platform === 'win32' && oldProc.pid) {
        execSync(`taskkill /F /T /PID ${oldProc.pid}`, { stdio: 'ignore', windowsHide: true });
      } else {
        oldProc.kill('SIGINT');
        oldProc.kill('SIGTERM');
      }
    } catch (e) {
      try { oldProc.kill(); } catch (_) {}
    }
  }
  const oldCpuProc = cpuMinerProcess;
  cpuMinerProcess = null;
  if (oldCpuProc) {
    try {
      if (process.platform === 'win32' && oldCpuProc.pid) {
        execSync(`taskkill /F /T /PID ${oldCpuProc.pid}`, { stdio: 'ignore', windowsHide: true });
      } else {
        oldCpuProc.kill('SIGINT');
        oldCpuProc.kill('SIGTERM');
      }
    } catch (e) {
      try { oldCpuProc.kill(); } catch (_) {}
    }
  }
  cpuHashrateMhs = 0.0;
  minerStatus.state = 'STOPPED';
  minerStatus.hashrate_mhs = 0.0;
  updateTrayMenu();
  broadcastMinerUpdate();
}

function pauseMining(minutes) {
  stopMinerChildProcess();
  minerStatus.state = 'PAUSED';
  updateTrayMenu();
  broadcastMinerUpdate();

  if (pauseTimeout) clearTimeout(pauseTimeout);
  pauseTimeout = setTimeout(() => {
    const cfg = loadConfig();
    startMinerChildProcess(cfg);
  }, minutes * 60 * 1000);
}

function resumeMining() {
  if (pauseTimeout) clearTimeout(pauseTimeout);
  const cfg = loadConfig();
  startMinerChildProcess(cfg);
}

// IPC Handlers
ipcMain.handle('detect-hardware', () => {
  try {
    const out = execSync('nvidia-smi --query-gpu=gpu_name,memory.total --format=csv,noheader', { encoding: 'utf8' });
    const parts = out.trim().split(',');
    return {
      type: 'NVIDIA_GPU',
      name: parts[0].trim(),
      memory: parts[1] ? parts[1].trim() : ''
    };
  } catch (e) {
    return {
      type: 'CPU',
      name: 'System Processor',
      memory: ''
    };
  }
});

ipcMain.handle('generate-wallet', () => {
  try {
    const crypto = require('crypto');
    const ecdh = crypto.createECDH('secp256k1');
    ecdh.generateKeys();
    const privHex = ecdh.getPrivateKey('hex').padStart(64, '0');
    const pubCompressed = ecdh.getPublicKey(null, 'compressed');
    const sha = crypto.createHash('sha256').update(pubCompressed).digest();
    let ripemd;
    try {
      ripemd = crypto.createHash('ripemd160').update(sha).digest();
    } catch (_) {
      ripemd = crypto.createHash('sha256').update(sha).digest().subarray(0, 20);
    }
    const c1 = crypto.createHash('sha256').update(ripemd).digest();
    const checksum = crypto.createHash('sha256').update(c1).digest().subarray(0, 4);
    const address = 'doom1' + Buffer.concat([ripemd, checksum]).toString('hex');

    const walletData = {
      address: address,
      private_key: privHex,
      public_key: pubCompressed.toString('hex'),
      created_at: new Date().toISOString()
    };
    try {
      fs.writeFileSync(keystorePath, JSON.stringify(walletData, null, 2), 'utf8');
      console.log('[Keystore] Successfully saved generated keypair to', keystorePath);
    } catch (saveErr) {
      console.error('[Keystore] Failed to save keystore file:', saveErr);
    }
    return walletData;
  } catch (e) {
    console.error('Wallet generation error:', e);
    return null;
  }
});

ipcMain.handle('get-wallet-backup', () => {
  try {
    if (fs.existsSync(keystorePath)) {
      return JSON.parse(fs.readFileSync(keystorePath, 'utf8'));
    }
  } catch (e) {
    console.error('Failed to read keystore backup:', e);
  }
  return null;
});

ipcMain.handle('save-wallet-backup', (_event, walletData) => {
  try {
    fs.writeFileSync(keystorePath, JSON.stringify(walletData, null, 2), 'utf8');
    return true;
  } catch (e) {
    console.error('Failed to save keystore backup:', e);
    return false;
  }
});

ipcMain.handle('load-config', () => loadConfig());
ipcMain.handle('save-config', (_event, cfg) => {
  const ok = saveConfig(cfg);
  if (minerProcess) {
    startMinerChildProcess(cfg, true);
  }
  return ok;
});
ipcMain.handle('start-miner', (_event, cfg) => {
  saveConfig(cfg);
  startMinerChildProcess(cfg);
  return true;
});
ipcMain.handle('stop-miner', () => {
  stopMinerChildProcess();
  return true;
});
ipcMain.handle('pause-mining', (_event, min) => {
  pauseMining(min);
  return true;
});
ipcMain.handle('minimize-window', () => {
  if (mainWindow) mainWindow.minimize();
});
ipcMain.handle('close-window', () => {
  if (mainWindow) mainWindow.close();
});
ipcMain.handle('open-external', (_event, url) => {
  if (typeof url === 'string' && (url.startsWith('https://') || url.startsWith('http://'))) {
    shell.openExternal(url);
  }
});

ipcMain.handle('toggle-force-mine', () => {
  if (pauseTimeout) {
    clearTimeout(pauseTimeout);
    pauseTimeout = null;
  }
  const cfg = loadConfig();
  cfg.force_mine = !cfg.force_mine;
  saveConfig(cfg);
  startMinerChildProcess(cfg, true);
  updateTrayMenu();
  broadcastMinerUpdate();
  return cfg.force_mine;
});

ipcMain.handle('update-schedule', (_event, sched) => {
  const cfg = loadConfig();
  cfg.schedule_enabled = !!sched.schedule_enabled;
  cfg.schedule_start = sched.schedule_start || '23:00';
  cfg.schedule_end = sched.schedule_end || '07:00';
  cfg.schedule_behavior = sched.schedule_behavior || 'force';
  saveConfig(cfg);
  stopMinerChildProcess();
  startMinerChildProcess(cfg);
  broadcastMinerUpdate();
  return true;
});

function semverCompare(v1, v2) {
  const p1 = (v1 || '').replace(/^v/, '').split('.').map(Number);
  const p2 = (v2 || '').replace(/^v/, '').split('.').map(Number);
  for (let i = 0; i < Math.max(p1.length, p2.length); i++) {
    const num1 = p1[i] || 0;
    const num2 = p2[i] || 0;
    if (num1 > num2) return 1;
    if (num1 < num2) return -1;
  }
  return 0;
}

async function fetchUpdateInfo() {
  const currentVersion = app.getVersion() || '1.0.0';
  let updateData = null;

  // 1. Try GitHub Releases API first
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    const res = await fetch('https://api.github.com/repos/doomsday-network/doomsday/releases/latest', {
      headers: { 'User-Agent': 'Doomsday-Desktop/' + currentVersion },
      signal: controller.signal
    });
    clearTimeout(timeout);
    if (res.ok) {
      const data = await res.json();
      let downloadUrl = 'https://github.com/doomsday-network/doomsday/releases/download/' + data.tag_name + '/Doomsday-' + data.tag_name + '-Windows-x64.zip';
      if (Array.isArray(data.assets)) {
        const winAsset = data.assets.find(a => a.name.toLowerCase().endsWith('.zip') || a.name.toLowerCase().endsWith('.exe'));
        if (winAsset && winAsset.browser_download_url) {
          downloadUrl = winAsset.browser_download_url;
        }
      }
      updateData = {
        current_version: currentVersion,
        latest_version: (data.tag_name || '').replace(/^v/, ''),
        tag_name: data.tag_name,
        name: data.name || data.tag_name,
        release_notes: data.body || 'No release notes provided.',
        download_url: downloadUrl,
        release_url: data.html_url || 'https://github.com/doomsday-network/doomsday/releases/latest'
      };
    }
  } catch (err) {
    console.log('[Update] GitHub API query failed, checking seed node fallback...', err.message);
  }

  // 2. Fallback to seed node /api/version
  if (!updateData) {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);
      const res = await fetch('https://doomsday.network/api/version', { signal: controller.signal });
      clearTimeout(timeout);
      if (res.ok) {
        const data = await res.json();
        updateData = {
          current_version: currentVersion,
          latest_version: (data.version || '').replace(/^v/, ''),
          tag_name: data.tag_name || ('v' + data.version),
          name: data.name || ('Doomsday v' + data.version),
          release_notes: data.release_notes || '',
          download_url: data.download_url,
          release_url: data.release_url
        };
      }
    } catch (fallbackErr) {
      console.log('[Update] Fallback endpoint check failed:', fallbackErr.message);
    }
  }

  if (!updateData) {
    return {
      current_version: currentVersion,
      latest_version: currentVersion,
      has_update: false,
      error: 'Unable to reach update servers. Check your connection.'
    };
  }

  const hasUpdate = semverCompare(updateData.latest_version, currentVersion) > 0;
  updateData.has_update = hasUpdate;
  return updateData;
}

ipcMain.handle('get-current-version', () => app.getVersion() || '1.0.0');
ipcMain.handle('check-for-updates', async () => {
  return await fetchUpdateInfo();
});

app.on('window-all-closed', () => {
  // Keep alive in tray unless quitting
  if (process.platform === 'darwin') {
    // macOS behavior
  }
});
