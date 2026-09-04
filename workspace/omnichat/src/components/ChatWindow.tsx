import React, { useState } from 'react';
import DOMPurify from 'dompurify';
import { useWebSocket } from '../hooks/useWebSocket';

export const ChatWindow = () => {
  const { messages, sendMessage } = useWebSocket();
  const [input, setInput] = useState('');

  const handleSend = () => {
    const cleanContent = DOMPurify.sanitize(input.trim());
    if (cleanContent) {
      sendMessage(cleanContent);
      setInput('');
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#2C2F33] text-white">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.map((msg, i) => (
          <div key={i} className="mb-2">
            <span className="font-bold">{msg.user}: </span>
            <span dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(msg.content) }} />
          </div>
        ))}
      </div>
      <div className="p-4 bg-[#23272A]">
        <input
          className="w-full p-2 bg-[#2C2F33] rounded"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Nachricht senden..."
        />
      </div>
    </div>
  );
};
