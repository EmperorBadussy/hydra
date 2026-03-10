/*
  ╔══════════════════════════════════════════════════════════════════╗
  ║  HYDRA — Preload Script                                         ║
  ║  Context bridge: exposes safe IPC channels to the renderer      ║
  ╚══════════════════════════════════════════════════════════════════╝
*/

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('hydra', {
  // ── Window controls ──
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  isMaximized: () => ipcRenderer.invoke('window-is-maximized'),
  onWindowState: (callback) => {
    ipcRenderer.on('window-state', (_event, state) => callback(state));
  },

  // ── Python bridge commands ──
  bridge: (action, params) => ipcRenderer.invoke('bridge-command', action, params),

  // ── Module management ──
  listModules: () => ipcRenderer.invoke('bridge-command', 'list_modules', {}),
  updateModules: () => ipcRenderer.invoke('bridge-command', 'update_modules', {}),
  healthCheck: () => ipcRenderer.invoke('bridge-command', 'health_check', {}),
  moduleStatus: (module) => ipcRenderer.invoke('bridge-command', 'module_status', { module }),

  // ── Search ──
  search: (query, service, mediaType, limit) =>
    ipcRenderer.invoke('bridge-command', 'search', { query, service, media_type: mediaType, limit }),

  // ── Download ──
  getMetadata: (url, service) =>
    ipcRenderer.invoke('bridge-command', 'get_metadata', { url, service }),

  // ── Auth ──
  authenticate: (service, credentials) =>
    ipcRenderer.invoke('bridge-command', 'authenticate', { service, credentials }),

  // ── Download queue ──
  queueAdd: (item) => ipcRenderer.invoke('queue-add', item),
  queueRemove: (itemId) => ipcRenderer.invoke('queue-remove', itemId),
  queueGet: () => ipcRenderer.invoke('queue-get'),
  queueClearCompleted: () => ipcRenderer.invoke('queue-clear-completed'),

  // ── Settings ──
  getSettings: () => ipcRenderer.invoke('settings-get'),
  setSettings: (settings) => ipcRenderer.invoke('settings-set', settings),

  // ── System ──
  checkDeps: () => ipcRenderer.invoke('check-dependencies'),
  openFolder: (folderPath) => ipcRenderer.invoke('open-folder', folderPath),
  openUrl: (url) => ipcRenderer.invoke('open-url', url),

  // ── Event listeners ──
  onQueueUpdate: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on('queue-update', handler);
    return () => ipcRenderer.removeListener('queue-update', handler);
  },

  onDownloadProgress: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on('download-progress', handler);
    return () => ipcRenderer.removeListener('download-progress', handler);
  },

  onDownloadComplete: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on('download-complete', handler);
    return () => ipcRenderer.removeListener('download-complete', handler);
  },

  onHydraLog: (callback) => {
    const handler = (event, data) => callback(data);
    ipcRenderer.on('hydra-log', handler);
    return () => ipcRenderer.removeListener('hydra-log', handler);
  },
});
