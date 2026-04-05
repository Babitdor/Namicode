/**
 * Vixie Nami-Code Integration Client
 * 
 * Connects to Nami-Code's WebSocket server to receive real-time state updates
 * and display appropriate Pokémon sprites based on the agent's current activity.
 */

const NamiState = {
    IDLE: 'idle',
    THINKING: 'thinking',
    WORKING: 'working',
    SUCCESS: 'success',
    ERROR: 'error',
    USER_INPUT: 'user_input',
    PLANNING: 'planning'
};

// Pokémon sprite mappings for each state
const STATE_SPRITES = {
    [NamiState.IDLE]: 'https://play.pokemonshowdown.com/sprites/ani-shiny/victini.gif',
    [NamiState.THINKING]: 'https://play.pokemonshowdown.com/sprites/ani-shiny/sylveon.gif',
    [NamiState.WORKING]: 'https://play.pokemonshowdown.com/sprites/ani-shiny/rapidash.gif',
    [NamiState.SUCCESS]: 'https://play.pokemonshowdown.com/sprites/ani-shiny/mew.gif',
    [NamiState.ERROR]: 'https://play.pokemonshowdown.com/sprites/ani-shiny/ghost.gif',
    [NamiState.USER_INPUT]: 'https://play.pokemonshowdown.com/sprites/ani-shiny/chansey.gif',
    [NamiState.PLANNING]: 'https://play.pokemonshowdown.com/sprites/ani-shiny/alakazam.gif'
};

class VixieNamiClient {
    constructor() {
        this.ws = null;
        this.state = NamiState.IDLE;
        this.spriteUrl = STATE_SPRITES[NamiState.IDLE];
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Start with 1 second, double each attempt
        this.heartbeatInterval = null;
        
        // DOM elements - use correct element ID 'pet'
        this.spriteElement = document.getElementById('pet');
        
        // Initialize
        this.setupEventListeners();
        this.connect();
    }
    
    setupEventListeners() {
        // Handle window focus/blur for state management
        window.addEventListener('focus', () => {
            if (this.connected) {
                this.updateStatus('Ready');
            }
        });
        
        window.addEventListener('blur', () => {
            if (this.connected) {
                this.updateStatus('Paused');
            }
        });

        // Listen for WebSocket config updates from settings
        if (window.electronAPI && window.electronAPI.onWebsocketConfigUpdate) {
            window.electronAPI.onWebsocketConfigUpdate((event, config) => {
                this.handleConfigUpdate(config);
            });
        }
    }
    
    handleConfigUpdate(config) {
        console.log('WebSocket config updated:', config);
        this.disconnect();
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        this.connect();
    }
    
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
        this.connected = false;
    }
    
    connect() {
        const host = localStorage.getItem('namiWebSocketHost') || '127.0.0.1';
        const port = localStorage.getItem('namiWebSocketPort') || '8765';
        const url = `ws://${host}:${port}`;
        
        console.log(`Connecting to Nami-Code at ${url}...`);
        this.notifyConnectionStatus('connecting');
        
        try {
            this.ws = new WebSocket(url);
        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.reconnect();
            return;
        }
        
        this.ws.onopen = () => {
            this.connected = true;
            this.reconnectAttempts = 0;
            this.reconnectDelay = 1000;
            console.log('Connected to Nami-Code WebSocket');
            this.notifyConnectionStatus('connected');
            
            // Start heartbeat
            this.heartbeatInterval = setInterval(() => {
                this.sendHeartbeat();
            }, 30000);
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (error) {
                console.error('Failed to parse WebSocket message:', error);
            }
        };
        
        this.ws.onclose = () => {
            this.connected = false;
            console.log('WebSocket connection closed');
            this.notifyConnectionStatus('disconnected');
            
            // Clear heartbeat
            if (this.heartbeatInterval) {
                clearInterval(this.heartbeatInterval);
                this.heartbeatInterval = null;
            }
            
            // Attempt reconnection
            this.reconnect();
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.notifyConnectionStatus('disconnected');
        };
    }
    
    reconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Reconnecting in ${this.reconnectDelay/1000}s... (attempt ${this.reconnectAttempts})`);
            
            setTimeout(() => {
                this.connect();
            }, this.reconnectDelay);
            
            // Double the delay for next attempt (exponential backoff)
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
        } else {
            console.log('Max reconnection attempts reached');
            this.notifyConnectionStatus('disconnected');
        }
    }
    
    handleMessage(data) {
        switch (data.event_type) {
            case 'state_update':
                this.handleStateUpdate(data.data);
                break;
                
            case 'task_completed':
                this.handleTaskCompleted(data.data);
                break;
                
            case 'task_failed':
                this.handleTaskFailed(data.data);
                break;
                
            case 'user_input_required':
                this.handleUserInputRequired(data.data);
                break;
                
            case 'error':
                this.handleError(data.data);
                break;
                
            case 'pong':
                // Heartbeat response
                break;
                
            default:
                console.log('Unknown event type:', data.event_type);
        }
    }
    
    handleStateUpdate(data) {
        const newState = data.state;
        const previousState = this.state;
        this.state = newState;
        
        // Update sprite
        this.spriteUrl = STATE_SPRITES[newState] || STATE_SPRITES[NamiState.IDLE];
        if (this.spriteElement && this.spriteElement.src !== this.spriteUrl) {
            this.spriteElement.src = this.spriteUrl;
        }
        
        // Show popup message if state changed and popup is enabled
        const popupEnabled = localStorage.getItem('popupEnabled') !== 'false';
        if (previousState !== newState && popupEnabled && typeof showPopup === 'function') {
            const stateMessages = {
                'idle': 'Ready',
                'thinking': 'Thinking...',
                'working': 'Working...',
                'success': 'Done!',
                'error': 'Error',
                'user_input': 'Waiting for input',
                'planning': 'Planning...'
            };
            const message = stateMessages[newState] || this.formatStateName(newState);
            showPopup(message, newState);
        }
        
        console.log(`State updated: ${newState}`);
    }
    
    handleTaskCompleted(data) {
        console.log(`Task completed: ${data.task_name}`);
        
        // Briefly show success sprite
        const originalSprite = this.spriteUrl;
        this.spriteUrl = STATE_SPRITES[NamiState.SUCCESS];
        if (this.spriteElement) {
            this.spriteElement.src = this.spriteUrl;
        }
        
        const popupEnabled = localStorage.getItem('popupEnabled') !== 'false';
        if (popupEnabled && typeof showPopup === 'function') {
            showPopup(`✓ ${data.task_name}`, 'success');
        }
        
        setTimeout(() => {
            this.spriteUrl = originalSprite;
            if (this.spriteElement) {
                this.spriteElement.src = this.spriteUrl;
            }
        }, 2000);
    }
    
    handleTaskFailed(data) {
        console.error(`Task failed: ${data.task_name} - ${data.error}`);
        
        // Briefly show error sprite
        const originalSprite = this.spriteUrl;
        this.spriteUrl = STATE_SPRITES[NamiState.ERROR];
        if (this.spriteElement) {
            this.spriteElement.src = this.spriteUrl;
        }
        
        const popupEnabled = localStorage.getItem('popupEnabled') !== 'false';
        if (popupEnabled && typeof showPopup === 'function') {
            showPopup(`✗ ${data.task_name}`, 'error');
        }
        
        setTimeout(() => {
            this.spriteUrl = originalSprite;
            if (this.spriteElement) {
                this.spriteElement.src = this.spriteUrl;
            }
        }, 2000);
    }
    
    handleUserInputRequired(data) {
        console.log('User input required:', data.prompt);
        
        // Show user input sprite
        this.spriteUrl = STATE_SPRITES[NamiState.USER_INPUT];
        if (this.spriteElement) {
            this.spriteElement.src = this.spriteUrl;
        }
        
        const popupEnabled = localStorage.getItem('popupEnabled') !== 'false';
        if (popupEnabled && typeof showPopup === 'function') {
            showPopup('Waiting for input', 'user_input');
        }
    }
    
    handleError(data) {
        console.error('Nami-Code error:', data.message);
        
        // Show error sprite
        this.spriteUrl = STATE_SPRITES[NamiState.ERROR];
        if (this.spriteElement) {
            this.spriteElement.src = this.spriteUrl;
        }
        
        const popupEnabled = localStorage.getItem('popupEnabled') !== 'false';
        if (popupEnabled && typeof showPopup === 'function') {
            showPopup(data.message || 'Error', 'error');
        }
    }
    
    formatStateName(state) {
        return state
            .split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }
    
    updateStatus(text) {
        console.log(`Status: ${text}`);
    }
    
    notifyConnectionStatus(status) {
        // Update local connection indicator directly
        if (typeof window.updateConnectionStatus === 'function') {
            window.updateConnectionStatus(status);
        }
        // Notify main process (forwards to settings window)
        if (window.electronAPI && window.electronAPI.notifyConnectionStatus) {
            window.electronAPI.notifyConnectionStatus(status);
        }
    }
    
    // Send heartbeat to server
    sendHeartbeat() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'ping' }));
        }
    }
    
    // Configuration methods
    setWebSocketConfig(host, port) {
        localStorage.setItem('namiWebSocketHost', host);
        localStorage.setItem('namiWebSocketPort', port);
        this.disconnect();
        this.reconnectAttempts = 0;
        this.reconnectDelay = 1000;
        this.connect();
    }
    
    getWebSocketConfig() {
        return {
            host: localStorage.getItem('namiWebSocketHost') || '127.0.0.1',
            port: localStorage.getItem('namiWebSocketPort') || '8765'
        };
    }
}

// Initialize when DOM is ready
let client = null;
document.addEventListener('DOMContentLoaded', () => {
    client = new VixieNamiClient();
});

// Export for testing
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { VixieNamiClient, NamiState };
}