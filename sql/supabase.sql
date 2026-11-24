-- Run in your Supabase SQL editor. Workers should use a server-side service key.
create table if not exists public.paper_tasks (
  id uuid primary key default gen_random_uuid(),
  arxiv_input text not null,
  status text not null default 'pending' check (status in ('pending', 'processing', 'done', 'failed')),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  worker_token uuid,
  code_status text,
  hype_flag boolean,
  result_json jsonb,
  error_msg text
);
create index if not exists paper_tasks_pending on public.paper_tasks (created_at) where status = 'pending';
alter table public.paper_tasks enable row level security;
-- No anonymous access by default. Add policies for your authenticated frontend.
-- After confirming a worker has stopped, manually reset its task to pending,
-- clearing worker_token. Automatic expiry could duplicate a still-running export.
