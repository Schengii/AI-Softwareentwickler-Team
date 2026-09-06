export interface Item {
  id: number;
  title: string;
  description: string | null;
  owner_id: number;
  created_at: string;
}

export interface User {
  id: number;
  email: string;
  is_active: boolean;
  created_at: string;
}

export interface ItemPayload {
  title: string;
  description?: string;
}
