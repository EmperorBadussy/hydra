/*
  ╔══════════════════════════════════════════════════════════════════╗
  ║  HYDRA — Harvesting Your DRM Resource Archives                  ║
  ╠══════════════════════════════════════════════════════════════════╣
  ║  Main Process — Electron shell, Python bridge, IPC, queue       ║
  ║                                                                  ║
  ║  "Cut off one head, two more grow back."                        ║
  ║                                                                  ║
  ║  Multi-headed streaming ripper with self-healing modules.       ║
  ║  Mirrors CHARON's Electron patterns:                             ║
  ║  - Frameless OLED-black window                                   ║
  ║  - Python bridge for download engine                             ║
  ║  - Download queue with concurrent processing                     ║
  ║  - System tray with minimize-to-tray                             ║
  ║  - F12 DevTools toggle                                           ║
  ╚══════════════════════════════════════════════════════════════════╝
*/

const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, shell, screen, session } = require('electron');
const path = require('path');
const os = require('os');
const { spawn } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');

let mainWindow = null;
let tray = null;
let pythonBridge = null;
let pendingRequests = new Map();
let globalSettings = {};

// ============ SETTINGS PERSISTENCE ============
const settingsPath = path.join(app.getPath('userData'), 'hydra-settings.json');
const queuePath = path.join(app.getPath('userData'), 'hydra-queue.json');

function loadSettings() {
  try {
    if (fs.existsSync(settingsPath)) {
      globalSettings = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
    }
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
}

function loadQueue() {
  try {
    if (fs.existsSync(queuePath)) {
      const data = JSON.parse(fs.readFileSync(queuePath, 'utf-8'));
      downloadQueue = data.queue || [];
      downloadHistory = data.history || [];
      downloadQueue.forEach(item => {
        if (item.status === 'downloading') item.status = 'queued';
      });
    }
  } catch (e) {
    console.error('Failed to load queue:', e);
  }
}

function saveQueue() {
  try {
    fs.writeFileSync(queuePath, JSON.stringify({
      queue: downloadQueue,
      history: downloadHistory.slice(0, 200)
    }, null, 2));
  } catch (e) {
    console.error('Failed to save queue:', e);
  }
}

// ============ WINDOW ============
function createWindow() {
  const { width: screenW, height: screenH } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width: Math.min(1400, screenW),
    height: Math.min(900, screenH),
    minWidth: 900,
    minHeight: 600,
    frame: false,
    titleBarStyle: 'hidden',
    backgroundColor: '#000000',
    show: false,
    icon: path.join(__dirname, 'icon.ico'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: false,
      webgl: true,
      backgroundThrottling: false,
    }
  });

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': ["default-src * 'unsafe-inline' 'unsafe-eval' data: blob:"]
      }
    });
  });

  mainWindow.loadFile('hydra.html');
  mainWindow.once('ready-to-show', () => mainWindow.show());

  mainWindow.on('maximize', () => {
    mainWindow.webContents.send('window-state', 'maximized');
  });
  mainWindow.on('unmaximize', () => {
    mainWindow.webContents.send('window-state', 'normal');
  });

  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ============ SYSTEM TRAY ============
function createTray() {
  try {
    const iconPath = path.join(__dirname, 'icon.ico');
    if (fs.existsSync(iconPath)) {
      tray = new Tray(iconPath);
    } else {
      const size = 16;
      const canvas = Buffer.alloc(size * size * 4);
      for (let i = 0; i < size * size; i++) {
        const offset = i * 4;
        const x = i % size, y = Math.floor(i / size);
        if (x >= 2 && x <= 13 && y >= 2 && y <= 13) {
          // Green tray icon
          canvas[offset] = 34; canvas[offset + 1] = 197; canvas[offset + 2] = 94; canvas[offset + 3] = 200;
        }
      }
      tray = new Tray(nativeImage.createFromBuffer(canvas, { width: size, height: size }));
    }
    const contextMenu = Menu.buildFromTemplate([
      { label: 'Show HYDRA', click: () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } } },
      { type: 'separator' },
      { label: 'Quit', click: () => {
        if (activeDownloads > 0) {
          const { dialog } = require('electron');
          dialog.showMessageBox({
            type: 'question',
            buttons: ['Keep Running', 'Quit Anyway'],
            defaultId: 0,
            title: 'Downloads Active',
            message: `${activeDownloads} download(s) still running. Quit anyway?`
          }).then(result => {
            if (result.response === 1) { app.isQuitting = true; app.quit(); }
          });
        } else {
          app.isQuitting = true; app.quit();
        }
      }}
    ]);
    tray.setToolTip('HYDRA — Streaming Ripper');
    tray.setContextMenu(contextMenu);
    tray.on('double-click', () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } });
  } catch (e) {
    console.error('Tray creation failed:', e);
  }
}

// ============ PYTHON BRIDGE ============
function startPythonBridge() {
  const bridgePath = path.join(__dirname, 'python', 'hydra_bridge.py');
  if (!fs.existsSync(bridgePath)) {
    console.warn('Python bridge not found at', bridgePath);
    return;
  }

  const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';

  pythonBridge = spawn(pythonCmd, [bridgePath], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    }
  });

  let stdoutBuffer = '';

  pythonBridge.stdout.on('data', (data) => {
    stdoutBuffer += data.toString('utf-8');
    const lines = stdoutBuffer.split('\n');
    stdoutBuffer = lines.pop();

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const response = JSON.parse(line);
        const reqId = response.request_id;

        if (response.status === 'progress') {
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('download-progress', response);
          }
          continue;
        }

        if (reqId && pendingRequests.has(reqId)) {
          const { resolve, timeout } = pendingRequests.get(reqId);
          clearTimeout(timeout);
          pendingRequests.delete(reqId);
          resolve(response);
        }
      } catch (e) {
        console.error('Bridge JSON parse error:', e.message, 'line:', line.substring(0, 200));
      }
    }
  });

  pythonBridge.stderr.on('data', (data) => {
    const msg = data.toString();
    console.error('Bridge:', msg);
    // Forward module update messages to renderer
    if (msg.includes('[HYDRA') && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('hydra-log', msg.trim());
    }
  });

  pythonBridge.on('close', (code) => {
    console.log('Python bridge exited with code', code);
    pythonBridge = null;
    for (const [id, { reject, timeout }] of pendingRequests) {
      clearTimeout(timeout);
      reject(new Error('Bridge process exited'));
    }
    pendingRequests.clear();
  });

  console.log('Python bridge started, PID:', pythonBridge.pid);
}

function sendBridgeCommand(action, params = {}, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    if (!pythonBridge || pythonBridge.killed) {
      reject(new Error('Python bridge not running'));
      return;
    }

    const requestId = crypto.randomUUID();
    const command = JSON.stringify({ action, params, request_id: requestId }) + '\n';

    const timeout = setTimeout(() => {
      pendingRequests.delete(requestId);
      reject(new Error(`Bridge command "${action}" timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    pendingRequests.set(requestId, { resolve, reject, timeout });

    try {
      pythonBridge.stdin.write(command);
    } catch (e) {
      pendingRequests.delete(requestId);
      clearTimeout(timeout);
      reject(new Error('Failed to write to bridge: ' + e.message));
    }
  });
}

// ============ DOWNLOAD QUEUE ============
let downloadQueue = [];
let activeDownloads = 0;
let maxConcurrent = 3;
let downloadHistory = [];

function processQueue() {
  maxConcurrent = parseInt(globalSettings.concurrent) || 3;

  while (activeDownloads < maxConcurrent && downloadQueue.length > 0) {
    const nextIdx = downloadQueue.findIndex(item => item.status === 'queued');
    if (nextIdx === -1) break;

    const item = downloadQueue[nextIdx];
    item.status = 'downloading';
    activeDownloads++;

    notifyRenderer('queue-update', { queue: downloadQueue, history: downloadHistory });
    saveQueue();

    const downloadDir = globalSettings.downloadDir || path.join(os.homedir(), 'Videos', 'HYDRA');

    sendBridgeCommand('download', {
      url: item.url,
      service: item.service,
      quality: item.quality || globalSettings.quality || 'best',
      item_id: item.id,
      output_dir: downloadDir,
    }, 3600000) // 1 hour timeout for video
      .then(result => {
        item.status = 'completed';
        item.completedAt = Date.now();
        if (result.data) {
          item.filePath = result.data.file_path;
          item.fileSize = result.data.file_size;
        }
        downloadHistory.unshift(item);
        downloadQueue = downloadQueue.filter(q => q.id !== item.id);
        activeDownloads--;
        notifyRenderer('queue-update', { queue: downloadQueue, history: downloadHistory });
        notifyRenderer('download-complete', item);
        saveQueue();
        processQueue();
      })
      .catch(err => {
        item.status = 'error';
        item.error = err.message;
        activeDownloads--;
        notifyRenderer('queue-update', { queue: downloadQueue, history: downloadHistory });
        saveQueue();
        processQueue();
      });
  }
}

function notifyRenderer(channel, data) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, data);
  }
}

// ============ IPC HANDLERS ============
ipcMain.on('window-minimize', () => mainWindow?.minimize());
ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});
ipcMain.on('window-close', () => mainWindow?.close());
ipcMain.handle('window-is-maximized', () => mainWindow ? mainWindow.isMaximized() : false);

// Bridge commands
ipcMain.handle('bridge-command', async (event, action, params) => {
  try {
    const timeout = action === 'download' ? 3600000 : action === 'update_modules' ? 120000 : 30000;
    return await sendBridgeCommand(action, params, timeout);
  } catch (e) {
    return { status: 'error', error: e.message };
  }
});

// Queue management
ipcMain.handle('queue-add', (event, item) => {
  item.id = item.id || crypto.randomUUID();
  item.status = 'queued';
  item.addedAt = Date.now();
  downloadQueue.push(item);
  notifyRenderer('queue-update', { queue: downloadQueue, history: downloadHistory });
  saveQueue();
  processQueue();
  return { success: true, id: item.id };
});

ipcMain.handle('queue-remove', (event, itemId) => {
  downloadQueue = downloadQueue.filter(q => q.id !== itemId);
  notifyRenderer('queue-update', { queue: downloadQueue, history: downloadHistory });
  saveQueue();
  return { success: true };
});

ipcMain.handle('queue-get', () => {
  return { queue: downloadQueue, history: downloadHistory };
});

ipcMain.handle('queue-clear-completed', () => {
  downloadHistory = [];
  notifyRenderer('queue-update', { queue: downloadQueue, history: downloadHistory });
  saveQueue();
  return { success: true };
});

// System
ipcMain.handle('open-folder', (event, folderPath) => {
  try { shell.showItemInFolder(folderPath); return { success: true }; }
  catch (e) { return { success: false, error: e.message }; }
});

ipcMain.handle('open-url', (event, url) => {
  try { shell.openExternal(url); return { success: true }; }
  catch (e) { return { success: false, error: e.message }; }
});

// Settings
ipcMain.handle('settings-get', () => globalSettings);
ipcMain.handle('settings-set', (event, settings) => {
  globalSettings = settings;
  try {
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
  } catch (e) {
    return { success: false, error: e.message };
  }
  return { success: true };
});

// Dependency check
ipcMain.handle('check-dependencies', async () => {
  const result = { python: false, devine: false, ffmpeg: false, yt_dlp: false };
  const checkCmd = (cmd, args) => new Promise(resolve => {
    let resolved = false;
    const done = (val) => { if (!resolved) { resolved = true; resolve(val); } };
    try {
      const proc = spawn(cmd, args, { env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
      proc.on('close', (code) => done(code === 0));
      proc.on('error', () => done(false));
      setTimeout(() => { try { proc.kill(); } catch (e) {} done(false); }, 5000);
    } catch (e) { done(false); }
  });

  result.python = await checkCmd('python', ['--version']);
  result.devine = await checkCmd('python', ['-c', 'import devine; print("ok")']);
  result.ffmpeg = await checkCmd('ffmpeg', ['-version']);
  result.yt_dlp = await checkCmd('python', ['-c', 'import yt_dlp; print("ok")']);

  return result;
});

// ============ APP LIFECYCLE ============
process.on('uncaughtException', (err) => {
  console.error('UNCAUGHT:', err);
});

app.whenReady().then(() => {
  loadSettings();
  loadQueue();
  createWindow();
  createTray();
  startPythonBridge();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {});

app.on('before-quit', (e) => {
  if (activeDownloads > 0 && !app.isQuitting) {
    e.preventDefault();
    if (mainWindow) mainWindow.hide();
    return;
  }
  app.isQuitting = true;
  saveQueue();
  if (pythonBridge && !pythonBridge.killed) {
    pythonBridge.kill();
  }
});

app.on('browser-window-created', (_, win) => {
  win.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12') {
      win.webContents.toggleDevTools();
      event.preventDefault();
    }
  });
});
