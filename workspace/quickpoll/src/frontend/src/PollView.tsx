import React from 'react';
import { useWebSocket } from './useWebSocket';

export const PollView = ({ pollId, options }: { pollId: string, options: { id: number, text: string }[] }) => {
  const { results, vote } = useWebSocket(pollId);

  return (
    <div className="p-4 max-w-md mx-auto">
      <h2 className="text-xl font-bold mb-4">Live Umfrage</h2>
      {options.map(opt => (
        <button 
          key={opt.id}
          onClick={() => vote(opt.id)}
          className="block w-full p-2 mb-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          {opt.text} {results?.[opt.id] ? `(${results[opt.id]} Stimmen)` : ''}
        </button>
      ))}
    </div>
  );
};
