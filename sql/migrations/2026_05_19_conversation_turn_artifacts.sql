-- ============================================================================
-- 2026-05-19 — conversation_turn_artifacts 테이블 + RLS + 인덱스
--
-- 목적:
-- - Conversation 본문을 가볍게 유지하면서 턴별 retrieval 근거를 경량 요약으로 보존.
-- - reopen 시 근거 패널 복원 + stale 판정(index_version, TTL) 지원.
-- ============================================================================

create table if not exists public.conversation_turn_artifacts (
    retrieval_result_ref text primary key,
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    turn_index integer not null check (turn_index >= 0),
    pattern text,
    selected_strategy text,
    standalone_question text,
    index_version text not null default 'unknown',
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

comment on table public.conversation_turn_artifacts is
    '턴 단위 retrieval 스냅샷(경량 요약). 원문 문서/서브그래프 전체는 저장하지 않는다.';

comment on column public.conversation_turn_artifacts.payload is
    'citations/documents/graph/tool 요약 JSON.';

create unique index if not exists conversation_turn_artifacts_conv_turn_uq
    on public.conversation_turn_artifacts (conversation_id, turn_index);

create unique index if not exists conversation_turn_artifacts_ref_uq
    on public.conversation_turn_artifacts (retrieval_result_ref);

create index if not exists conversation_turn_artifacts_user_created_idx
    on public.conversation_turn_artifacts (user_id, created_at desc);

create index if not exists conversation_turn_artifacts_payload_gin_idx
    on public.conversation_turn_artifacts using gin (payload);

alter table public.conversation_turn_artifacts enable row level security;

drop policy if exists "사용자 본인 artifacts 만" on public.conversation_turn_artifacts;
create policy "사용자 본인 artifacts 만"
    on public.conversation_turn_artifacts
    for all
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);
