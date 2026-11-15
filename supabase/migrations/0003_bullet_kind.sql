-- Structured notes: each bullet has a kind (rendered as a box for definitions, examples, results, remarks),
-- an optional box title, and the one diagram worth showing with it.
alter table bullets add column if not exists kind text not null default 'point'
  check (kind in ('point', 'definition', 'example', 'result', 'remark'));
alter table bullets add column if not exists title text;
alter table bullets add column if not exists figure_block_id text;
