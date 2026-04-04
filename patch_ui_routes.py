<<<<<<< SEARCH
  poll_interval_seconds: number;
}
=======
  poll_interval_seconds: number;
}

export interface SystemHealth {
  status: 'ok' | 'degraded' | 'error';
  last_dispatch_at: string | null;
  pending_count: number;
  error_count: number;
  poll_interval_seconds: number;
}
>>>>>>> REPLACE
