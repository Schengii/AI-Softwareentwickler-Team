import { WSMessage } from '../types';

type MessageHandler = (message: WSMessage) => void;

export class DevPulseWebSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private handlers: MessageHandler[] = [];
  private reconnectInterval = 3000;
  private maxReconnectAttempts = 5;
  private attempts = 0;
  private isExplicitlyClosed = false;

  constructor(url: string = `ws://${window.location.host}/ws/updates`) {
    this.url = url;
  }

  public connect(): void {
    this.isExplicitlyClosed = false;
    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('[DevPulse WS] Connected to live updates gateway.');
        this.attempts = 0;
      };

      this.ws.onmessage = (event) => {
        try {
          const data: WSMessage = JSON.parse(event.data);
          this.handlers.forEach((handler) => handler(data));
        } catch (err) {
          console.error('[DevPulse WS] Error parsing websocket message:', err);
        }
      };

      this.ws.onclose = () => {
        if (!this.isExplicitlyClosed) {
          this.scheduleReconnect();
        }
      };

      this.ws.onerror = (err) => {
        console.warn('[DevPulse WS] WebSocket encountered an error.', err);
      };
    } catch (e) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.attempts < this.maxReconnectAttempts) {
      this.attempts++;
      setTimeout(() => this.connect(), this.reconnectInterval);
    }
  }

  public subscribe(handler: MessageHandler): () => void {
    this.handlers.push(handler);
    return () => {
      this.handlers = this.handlers.filter((h) => h !== handler);
    };
  }

  public disconnect(): void {
    this.isExplicitlyClosed = true;
    if (this.ws) {
      this.ws.close();
    }
  }
}
