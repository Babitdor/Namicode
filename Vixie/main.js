const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  nativeImage,
  screen,
  ipcMain,
} = require("electron");
const path = require("path");
const {
  startMouseCheck,
  stopGravity,
  toggleGravity,
  cleanUp,
  startDragging,
  stopDragging,
} = require("./gravity.js");

let tray = null;
let mainWindow;
let settingsWindow = null;

// Store behavior settings
let behaviorSettings = {
  gravity: true,
  sound: false,
  popup: true,
  size: 'medium'
};

// Size mappings
const SIZE_MAP = {
  'small': { width: 80, height: 80 },
  'medium': { width: 120, height: 120 },
  'large': { width: 160, height: 160 },
  'xlarge': { width: 200, height: 200 }
};

function createWindow() {
  const size = SIZE_MAP[behaviorSettings.size] || SIZE_MAP.medium;

  mainWindow = new BrowserWindow({
    width: size.width,
    height: size.height,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  mainWindow.loadFile(path.join(__dirname, "index.html"));

  // Start click-through until cursor hovers over the pet
  mainWindow.setIgnoreMouseEvents(true, { forward: true });

  startMouseCheck(mainWindow, screen);

  mainWindow.on("close", () => {
    cleanUp();
    mainWindow = null;
  });
}

function openSettingsWindow() {
  if (settingsWindow) {
    settingsWindow.focus();
    return;
  }

  settingsWindow = new BrowserWindow({
    width: 520,
    height: 680,
    title: "Vixie Settings",
    resizable: false,
    frame: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });

  settingsWindow.loadFile(path.join(__dirname, "settings.html"));

  // Send updated GIF URL back to main window
  settingsWindow.webContents.once("did-finish-load", () => {
    if (
      mainWindow &&
      !mainWindow.isDestroyed() &&
      settingsWindow &&
      !settingsWindow.isDestroyed()
    ) {
      mainWindow.webContents
        .executeJavaScript('document.getElementById("pet").src')
        .then((src) => {
          if (settingsWindow && !settingsWindow.isDestroyed()) {
            settingsWindow.webContents.send("set-current-gif", src);
          }
        })
        .catch(() => {
          if (settingsWindow && !settingsWindow.isDestroyed()) {
            settingsWindow.webContents.send(
              "set-current-gif",
              "https://play.pokemonshowdown.com/sprites/ani-shiny/victini.gif"
            );
          }
        });
    }
  });

  settingsWindow.on("closed", () => {
    if (settingsWindow && !settingsWindow.isDestroyed()) {
      settingsWindow.webContents.removeAllListeners();
    }
    settingsWindow = null;
  });
}

function flipPet() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("flip-pet");
  }
}

function createTray() {
  const iconPath = path.join(__dirname, "assets", "app-icon.png");
  const icon = nativeImage
    .createFromPath(iconPath)
    .resize({ width: 16, height: 16 });

  tray = new Tray(icon);

  const contextMenu = Menu.buildFromTemplate([
    { label: "Settings", click: () => openSettingsWindow() },
    { type: "separator" },
    { label: "Flip Pet", click: () => flipPet() },
    { label: "Toggle Gravity", click: () => toggleGravity(mainWindow, screen) },
    { type: "separator" },
    {
      label: "Show Pet",
      click: () => {
        if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show();
      },
    },
    {
      label: "Hide Pet",
      click: () => {
        if (mainWindow && !mainWindow.isDestroyed()) mainWindow.hide();
      },
    },
    { type: "separator" },
    { label: "Quit", role: "quit" },
  ]);

  tray.setToolTip("Vixie - Your Desktop Pet");
  tray.setContextMenu(contextMenu);
}

app.whenReady().then(() => {
  createWindow();
  createTray();
});

app.on("before-quit", () => {
  cleanUp(); // Ensure all intervals are cleaned
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

/**
 * IPC Logic for custom window dragging
 * (polls cursor position in main process so drag works even when cursor exits the small window)
 */
let customDragState = null;
let customDragInterval = null;

ipcMain.on("drag-start", (event, { screenX, screenY }) => {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  startDragging();
  const bounds = mainWindow.getBounds();
  customDragState = {
    startCursorX: screenX,
    startCursorY: screenY,
    startWinX: bounds.x,
    startWinY: bounds.y,
  };
  customDragInterval = setInterval(() => {
    if (!customDragState || !mainWindow || mainWindow.isDestroyed()) return;
    const cursor = screen.getCursorScreenPoint();
    const dx = cursor.x - customDragState.startCursorX;
    const dy = cursor.y - customDragState.startCursorY;
    mainWindow.setPosition(
      customDragState.startWinX + dx,
      customDragState.startWinY + dy
    );
  }, 16);
});

ipcMain.on("drag-end", () => {
  customDragState = null;
  if (customDragInterval) {
    clearInterval(customDragInterval);
    customDragInterval = null;
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    stopDragging(mainWindow, screen);
  }
});

/**
 * IPC Logic for GIF management
 */
ipcMain.on("update-gif", (event, newGifUrl) => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("update-gif", newGifUrl);
  }
});

ipcMain.on("mouse-enter", () => {
  stopGravity();
});

ipcMain.on("mouse-leave", () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    const { startGravity } = require("./gravity.js");
    startGravity(mainWindow, screen);
  }
});

/**
 * IPC Logic for WebSocket configuration
 */
ipcMain.on("update-websocket-config", (event, { host, port }) => {
  // Forward to main window for nami-client.js to handle
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("websocket-config-update", { host, port });
  }
});

/**
 * IPC Logic for behavior settings
 */
ipcMain.on("update-behavior", (event, settings) => {
  behaviorSettings = { ...behaviorSettings, ...settings };

  // Handle size changes
  if (settings.size && mainWindow && !mainWindow.isDestroyed()) {
    const size = SIZE_MAP[settings.size] || SIZE_MAP.medium;
    mainWindow.setSize(size.width, size.height);
    mainWindow.webContents.send("size-update", settings.size);
  }

  // Handle gravity toggle
  if (settings.gravity !== undefined) {
    if (settings.gravity) {
      const { startGravity } = require("./gravity.js");
      startGravity(mainWindow, screen);
    } else {
      stopGravity();
    }
  }
});

/**
 * IPC for connection status updates
 */
ipcMain.on("connection-status", (event, status) => {
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    settingsWindow.webContents.send("connection-status", status);
  }
});