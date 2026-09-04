export interface User {
  id: string;
  username: string;
  email: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export interface Project {
  id: string;
  name: string;
  client_name: string;
  hourly_rate: number;
}

export interface TimeEntry {
  id?: string;
  project_id: string;
  start: string; // ISO String
  end: string;   // ISO String
  description: string;
}
