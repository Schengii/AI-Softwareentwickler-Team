import React from 'react';
import { useTaskWebSocket } from '../hooks/useTaskWebSocket';

export const TaskList = () => {
  const { tasks, isConnected } = useTaskWebSocket('ws://localhost:8000/ws/tasks');

  return (
    <div className="p-4">
      <h2 className="text-xl font-bold mb-4">Tasks {isConnected ? '🟢' : '🔴'}</h2>
      <ul className="space-y-2">
        {tasks.map((task: any) => (
          <li key={task.id} className="p-2 border rounded shadow-sm">
            {task.title} - <span className="text-sm text-gray-500">{task.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};
