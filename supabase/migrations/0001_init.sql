-- BoardNotes schema v1. Runs on Supabase (hosted Postgres) and on the local test Postgres.
-- The web app never talks to these tables directly: all access goes through the FastAPI server,
-- which enforces student/lecturer permissions. Row-level security is enabled with no policies
-- so the Supabase anon key can't read anything even if it leaks.

create extension if not exists pgcrypto;

create table profiles (
  id text primary key,
  name text not null,
  initials text not null,
  role text not null check (role in ('student', 'lecturer'))
);

create table lectures (
  id text primary key default 'lec_' || substr(gen_random_uuid()::text, 1, 8),
  title text not null,
  status text not null default 'uploading'
    check (status in ('uploading', 'processing', 'draft', 'in_review', 'verified', 'failed')),
  duration_s double precision,
  video_path text,
  playback_path text,
  width int,
  height int,
  uploaded_by text references profiles(id),
  uploaded_at timestamptz not null default now()
);

create table uploads (
  id text primary key default 'up_' || substr(gen_random_uuid()::text, 1, 12),
  lecture_id text not null references lectures(id) on delete cascade,
  filename text not null,
  size_bytes bigint not null,
  received_bytes bigint not null default 0,
  created_at timestamptz not null default now()
);

create table jobs (
  lecture_id text primary key references lectures(id) on delete cascade,
  stage text not null default 'check_video',
  progress double precision not null default 0,
  detail text not null default '',
  sections_ready int not null default 0,
  error text,
  updated_at timestamptz not null default now()
);

create table transcript_segments (
  lecture_id text not null references lectures(id) on delete cascade,
  start_s double precision not null,
  end_s double precision not null,
  speaker text not null,
  text text not null
);
create index on transcript_segments (lecture_id, start_s);

create table board_blocks (
  id text not null,
  lecture_id text not null references lectures(id) on delete cascade,
  type text not null check (type in ('text', 'math', 'diagram')),
  text text not null,
  latex text,
  confidence double precision not null,
  first_seen_s double precision not null,
  best_frame_s double precision not null,
  bbox double precision[] not null,
  snapshot_path text,
  primary key (lecture_id, id)
);

create table sections (
  id text primary key default 'sec_' || substr(gen_random_uuid()::text, 1, 8),
  lecture_id text not null references lectures(id) on delete cascade,
  ord int not null,
  heading text not null,
  start_s double precision not null,
  end_s double precision not null,
  status text not null default 'draft' check (status in ('draft', 'uncertain', 'verified')),
  said_not_written jsonb not null default '[]'
);

create table bullets (
  id text primary key default 'bul_' || substr(gen_random_uuid()::text, 1, 8),
  section_id text not null references sections(id) on delete cascade,
  ord int not null,
  text text not null,
  latex text,
  confidence double precision not null,
  board_block_ids text[] not null default '{}',
  transcript_ranges jsonb not null default '[]',
  verified boolean not null default false
);

create table suggestions (
  id text primary key default 'sug_' || substr(gen_random_uuid()::text, 1, 8),
  bullet_id text not null references bullets(id) on delete cascade,
  author_id text not null references profiles(id),
  anonymous boolean not null default false,
  proposed_text text not null check (char_length(proposed_text) between 1 and 500),
  reason text,
  verdict text check (verdict in ('agrees', 'disagrees', 'unclear')),
  verdict_reason text,
  flagged boolean not null default false,
  status text not null default 'open' check (status in ('open', 'approved', 'rejected')),
  created_at timestamptz not null default now()
);

create table votes (
  suggestion_id text not null references suggestions(id) on delete cascade,
  user_id text not null references profiles(id),
  primary key (suggestion_id, user_id)
);

create table pdfs (
  id text primary key default 'pdf_' || substr(gen_random_uuid()::text, 1, 8),
  lecture_id text references lectures(id) on delete cascade, -- null = whole module
  path text not null,
  pages int not null,
  generated_at timestamptz not null default now()
);

create table training_examples (
  -- Approved fixes saved for later fine-tuning (Adaption). Written when a lecturer approves a fix.
  id bigserial primary key,
  lecture_id text not null,
  board_block_id text,
  snapshot_path text,
  model_reading text not null,
  corrected_text text not null,
  created_at timestamptz not null default now()
);

alter table profiles enable row level security;
alter table lectures enable row level security;
alter table uploads enable row level security;
alter table jobs enable row level security;
alter table transcript_segments enable row level security;
alter table board_blocks enable row level security;
alter table sections enable row level security;
alter table bullets enable row level security;
alter table suggestions enable row level security;
alter table votes enable row level security;
alter table pdfs enable row level security;
alter table training_examples enable row level security;

-- Demo users (made up)
insert into profiles (id, name, initials, role) values
  ('u_lecturer', 'Dr. Rivera', 'DR', 'lecturer'),
  ('u_sam', 'Sam Patel', 'SP', 'student'),
  ('u_riya', 'Riya K.', 'RK', 'student'),
  ('u_tom', 'Tom W.', 'TW', 'student');
