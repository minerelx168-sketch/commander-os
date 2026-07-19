-- Commander OS — Phase 1 schema
CREATE TABLE IF NOT EXISTS agents (
  id serial PRIMARY KEY,
  name text UNIQUE NOT NULL,
  role text NOT NULL,
  model text NOT NULL DEFAULT 'claude-sonnet',
  status text NOT NULL DEFAULT 'IDLE',           -- IDLE / WORKING / WAITING / ERROR
  budget_thb_monthly numeric NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
  id serial PRIMARY KEY,
  parent_id int REFERENCES tasks(id),
  created_by text NOT NULL,                      -- 'owner' | agent name
  assigned_to text NOT NULL,                     -- agent name
  title text NOT NULL,
  description text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'pending',        -- pending/in_progress/waiting_approval/done/failed
  result jsonb,
  thread_id text,                                -- LangGraph checkpoint thread
  cost_tokens int NOT NULL DEFAULT 0,
  cost_thb numeric NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
  id serial PRIMARY KEY,
  task_id int REFERENCES tasks(id),
  agent text NOT NULL,
  action_type text NOT NULL,                     -- e.g. EXECUTE_RECOMMENDATION
  payload jsonb NOT NULL DEFAULT '{}',
  risk text NOT NULL DEFAULT 'medium',           -- low/medium/high
  status text NOT NULL DEFAULT 'pending',        -- pending/approved/rejected/expired
  decided_by text,
  decided_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id serial PRIMARY KEY,
  agent text NOT NULL,
  task_id int,
  event text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cost_entries (
  id serial PRIMARY KEY,
  agent text NOT NULL,
  task_id int,
  model text NOT NULL,
  input_tokens int NOT NULL DEFAULT 0,
  output_tokens int NOT NULL DEFAULT 0,
  cost_thb numeric NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO agents (name, role, model) VALUES
  ('ceo', 'Chief Executive Officer — แตกงาน มอบหมาย รวมรายงาน', 'claude-sonnet'),
  ('cmo', 'Chief Marketing Officer — วิเคราะห์/จัดการ Meta Ads ผ่าน meta-ads-agent', 'claude-sonnet')
ON CONFLICT (name) DO NOTHING;
