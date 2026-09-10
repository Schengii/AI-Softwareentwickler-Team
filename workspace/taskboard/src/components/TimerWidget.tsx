import React, { useState, useEffect } from 'react';

export const TimerWidget: React.FC = () => {
  const [isRunning, setIsRunning] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [description, setDescription] = useState('');

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (isRunning) {
      interval = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
    return () => clearInterval(interval);
  }, [isRunning]);

  const formatTime = (totalSec: number) => {
    const h = Math.floor(totalSec / 3600).toString().padStart(2, '0');
    const m = Math.floor((totalSec % 3600) / 60).toString().padStart(2, '0');
    const s = (totalSec % 60).toString().padStart(2, '0');
    return `${h}:${m}:${s}`;
  };

  const handleStop = async () => {
    setIsRunning(false);
    // API Call: POST /api/v1/time-entries
    setSeconds(0);
    setDescription('');
  };

  return (
    <aside className="fixed bottom-0 left-0 right-0 bg-white border-t border-slate-200 p-4 shadow-lg z-50 flex items-center justify-between px-6">
      <div className="flex items-center gap-4 flex-1 max-w-md">
        <input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Woran arbeitest du gerade?"
          className="w-full px-3 py-2 text-sm border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>

      <div className="flex items-center gap-4">
        <span className="font-mono text-lg font-semibold text-slate-900" aria-live="polite">
          {formatTime(seconds)}
        </span>

        {!isRunning ? (
          <button
            onClick={() => setIsRunning(true)}
            className="bg-indigo-600 text-white px-4 py-2 rounded-md font-medium text-sm hover:bg-indigo-700 transition-colors focus:ring-2 focus:ring-indigo-500 focus:outline-none"
          >
            Start
          </button>
        ) : (
          <button
            onClick={handleStop}
            className="bg-rose-600 text-white px-4 py-2 rounded-md font-medium text-sm hover:bg-rose-700 transition-colors focus:ring-2 focus:ring-rose-500 focus:outline-none"
          >
            Stopp
          </button>
        )}
      </div>
    </aside>
  );
};
