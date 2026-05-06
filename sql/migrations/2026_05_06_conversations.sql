-- ============================================================================
-- 2026-05-06 — conversations 테이블 + RLS + 인덱스 (TRD-011)
--
-- 적용 방법:
--   (a) Supabase CLI:    supabase db push
--   (b) Dashboard:       SQL Editor 에서 본 파일 내용 붙여넣고 Run
--
-- 영향:
--   - public.conversations 테이블 신규.
--   - RLS 강제 (auth.uid() = user_id 정책).
--   - GIN 인덱스 (state jsonb) — 향후 부분 쿼리·필터 가속.
--   - updated_at 자동 갱신 트리거.
-- ============================================================================

-- uuid 생성 함수 (Supabase 는 기본 활성)
create extension if not exists "uuid-ossp";


-- ============================================================
-- 테이블
-- ============================================================
create table if not exists public.conversations (
    id           uuid primary key default uuid_generate_v4(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    state        jsonb not null,
    title        text,
    updated_at   timestamptz not null default now(),
    created_at   timestamptz not null default now()
);

comment on table public.conversations is
    '대화 영속화 — chatbot.domain.Conversation.model_dump_json 결과를 state jsonb 로 저장.
     RLS 정책으로 사용자 격리 (auth.uid() = user_id).';

comment on column public.conversations.state is
    'frozen Pydantic Conversation.model_dump(mode="json") 결과. turns 시퀀스 포함.';
comment on column public.conversations.title is
    '낙관적 캐시 — 첫 user_message.content 의 첫 30자. 사이드바 빠른 노출용.';


-- ============================================================
-- 인덱스
-- ============================================================
-- 사이드바 — 사용자별 최신순 정렬
create index if not exists conversations_user_updated_idx
    on public.conversations (user_id, updated_at desc);

-- jsonb 부분 쿼리 — 향후 turns/citations/intent 검색 가속 (현재 사용 0, 미래 대비)
create index if not exists conversations_state_gin_idx
    on public.conversations using gin (state);


-- ============================================================
-- RLS — Row Level Security
-- ============================================================
alter table public.conversations enable row level security;

-- 사용자 본인 데이터만 R/W. service_role key 는 RLS 우회 — 백엔드 background save 에 사용.
drop policy if exists "사용자 본인 conversations 만" on public.conversations;
create policy "사용자 본인 conversations 만"
    on public.conversations
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);


-- ============================================================
-- updated_at 자동 갱신 트리거
-- ============================================================
create or replace function public.touch_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists conversations_updated_at on public.conversations;
create trigger conversations_updated_at
    before update on public.conversations
    for each row execute function public.touch_updated_at();


-- ============================================================
-- 검증 쿼리 (수동 실행)
-- ============================================================
-- select count(*) from public.conversations;
-- select id, user_id, jsonb_array_length(state->'turns') as turn_count, updated_at
--   from public.conversations
--   where user_id = auth.uid()
--   order by updated_at desc
--   limit 10;
