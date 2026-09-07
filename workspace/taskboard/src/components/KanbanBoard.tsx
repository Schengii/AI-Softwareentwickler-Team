import React, { useState } from 'react';
import { Task, TaskStatus } from '../types';

interface KanbanBoardProps {
  tasks: Task[];
  onStatusChange: (taskId: string, newStatus: TaskStatus) => void;
  onTaskClick: (task: Task) => void;
}

const COLUMNS: { id: TaskStatus; title: string; color: string }[] = [
  { id: 'todo', title: 'Zu erledigen', color: 'border-slate-300' },
  { id: 'in_progress', title: 'In Bearbeitung', color: 'border-indigo-400' },
  { id: 'done', title: 'Abgeschlossen', color: 'border-emerald-500' },
];

export const KanbanBoard: React.FC<KanbanBoardProps> = ({ tasks, onStatusChange, onTaskClick }) => {
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);

  const handleDragStart = (e: React.DragEvent, taskId: string) => {
    setDraggedTaskId(taskId);
    e.dataTransfer.setData('text/plain', taskId);
  };

  const handleDrop = (e: React.DragEvent, status: TaskStatus) => {
    e.preventDefault();
    if (draggedTaskId) {
      onStatusChange(draggedTaskId, status);
      setDraggedTaskId(null);
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 p-4">
      {COLUMNS.map((col) => {
        const columnTasks = tasks.filter((t) => t.status === col.id);
        return (
          <div
            key={col.id}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDrop(e, col.id)}
            className={`bg-slate-50 border-t-4 ${col.color} rounded-lg p-4 min-h-[500px] flex flex-col gap-3 shadow-sm`}
            aria-label={`Spalte ${col.title}`}
          >
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-sm font-bold text-slate-800 uppercase tracking-wider">{col.title}</h2>
              <span className="bg-slate-200 text-slate-700 text-xs px-2 py-1 rounded-full font-medium">
                {columnTasks.length}
              </span>
            </div>

            {columnTasks.map((task) => (
              <div
                key={task.id}
                draggable
                onDragStart={(e) => handleDragStart(e, task.id)}
                onClick={() => onTaskClick(task)}
                className="bg-white p-4 rounded-md shadow-sm border border-slate-200 hover:shadow-md cursor-grab active:cursor-grabbing transition-all ring-offset-2 focus:ring-2 focus:ring-indigo-500"
                tabIndex={0}
                role="button"
                aria-label={`Aufgabe: ${task.title}`}
              >
                <h3 className="text-sm font-semibold text-slate-900 mb-1">{task.title}</h3>
                {task.description && (
                  <p className="text-xs text-slate-500 line-clamp-2">{task.description}</p>
                )}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
};
