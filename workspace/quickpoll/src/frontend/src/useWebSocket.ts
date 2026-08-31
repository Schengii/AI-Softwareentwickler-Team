import { useState, useEffect } from 'react';

export const useWebSocket = (pollId: string) => {
  const [results, setResults] = useState(null);
  const [socket, setSocket] = useState<WebSocket | null>(null);

  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8000/ws/polls/${pollId}`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'update') setResults(data.results);
    };
    setSocket(ws);
    return () => ws.close();
  }, [pollId]);

  const vote = (optionId: number) => {
    socket?.send(JSON.stringify({ type: 'vote', option_id: optionId }));
  };

  return { results, vote };
};
