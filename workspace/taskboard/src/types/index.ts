export type TaskStatus = 'todo' | 'in_progress' | 'done';
export type UserRole = 'admin' | 'user';

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  created_at: string;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description?: string;
  status: TaskStatus;
  assignee_id?: string;
  created_at: string;
  updated_at: string;
}

export interface TimeEntry {
  id: string;
  task_id: string;
  user_id: string;
  description?: string;
  start_time: string;
  end_time?: string;
  duration_seconds?: number;
}
