// Spiegelt app/models.py (Check) und architecture/openapi.yaml (Check/NewCheck-Schemas) -
// hält Frontend und Backend synchron, ohne ein Codegen-Tool einzuführen.
export interface Check {
  id: number;
  url: string;
  interval_seconds: number;
  created_at: string;
  owner_id: number | null;
}

export interface NewCheck {
  url: string;
  interval_seconds: number;
}

export interface CheckStatus {
  check_id: number;
  up: boolean;
  timestamp: string;
}
