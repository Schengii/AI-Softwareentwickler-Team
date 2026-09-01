import { useEffect, useState } from 'react';

export const useTaskWebSocket = (url: string) => {
  const [tasks, setTasks] = useState([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const socket = new WebSocket(url);
    socket.onopen = () => setIsConnected(true);
    socket.onmessage = (event) => setTasks(JSON.parse(event.data));
    socket.onclose = () => setIsConnected(false);
    return () => socket.close();
  }, [url]);

  return { tasks, isConnected };
};
