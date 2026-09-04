import { createContext, useContext, useEffect, useState, ReactNode } from 'react';

interface WebSocketContextType {
  sendMessage: (message: string) => void;
  messages: any[];
  isConnected: boolean;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

export const WebSocketProvider = ({ channelId, token, children }: { channelId: string, token: string, children?: ReactNode }) => {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws/${channelId}?token=${token}`);
    
    ws.onopen = () => setIsConnected(true);
    ws.onclose = () => setIsConnected(false);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setMessages((prev) => [...prev, data]);
    };

    setSocket(ws);
    return () => ws.close();
  }, [channelId, token]);

  const sendMessage = (content: string) => {
    if (socket && isConnected) {
      socket.send(JSON.stringify({ content }));
    }
  };

  return (
    <WebSocketContext.Provider value={{ sendMessage, messages, isConnected }}>
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) throw new Error('useWebSocket must be used within WebSocketProvider');
  return context;
};
