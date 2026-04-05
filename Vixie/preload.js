const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // GIF management
  updateGif: (gifUrl) => ipcRenderer.send('update-gif', gifUrl),
  onFlipPet: (callback) => ipcRenderer.on('flip-pet', callback),
  onUpdateGif: (callback) => ipcRenderer.on('update-gif', callback),
  onSetCurrentGif: (callback) => ipcRenderer.on('set-current-gif', callback),

  // Custom window dragging
  startDrag: (screenX, screenY) => ipcRenderer.send('drag-start', { screenX, screenY }),
  stopDrag: () => ipcRenderer.send('drag-end'),

  // Mouse events
  mouseEnter: () => ipcRenderer.send('mouse-enter'),
  mouseLeave: () => ipcRenderer.send('mouse-leave'),

  // WebSocket configuration
  updateWebSocketConfig: (host, port) => ipcRenderer.send('update-websocket-config', { host, port }),
  onWebsocketConfigUpdate: (callback) => ipcRenderer.on('websocket-config-update', callback),
  onConnectionStatus: (callback) => ipcRenderer.on('connection-status', callback),

  // Connection status
  notifyConnectionStatus: (status) => ipcRenderer.send('connection-status', status),

  // Behavior settings
  updateBehavior: (settings) => ipcRenderer.send('update-behavior', settings),

  // Cleanup
  removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel)
});