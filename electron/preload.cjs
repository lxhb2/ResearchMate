const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('researchmate', {
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
  },
  getVersion: () => ipcRenderer.invoke('app:version'),
  checkForUpdates: () => ipcRenderer.invoke('update:check'),
  downloadUpdate: () => ipcRenderer.invoke('update:download'),
  installUpdate: () => ipcRenderer.invoke('update:install'),
})
