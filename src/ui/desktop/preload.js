'use strict'

/**
 * Electron preload script — exposes a safe, minimal API to the renderer
 * process via contextBridge. The renderer cannot access Node.js APIs directly.
 */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  /**
   * Open a native folder picker dialog.
   * Returns the selected path string, or null if cancelled.
   */
  selectFolder: () => ipcRenderer.invoke('select-folder'),

  /**
   * Returns the Electron app version string.
   */
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),

  /**
   * Open a folder in the OS file manager (e.g. after document delivery).
   */
  openFolder: (path) => ipcRenderer.invoke('open-folder', path),
})
