import { LegalLayout } from "@/components/LegalLayout";

export const metadata = {
  title: "개인정보 처리방침 — Calvin RAG Chatbot",
};

export default function PrivacyPage() {
  return (
    <LegalLayout title="개인정보 처리방침" updatedAt="2026-05-04">
      <h2>1. 수집 항목</h2>
      <ul>
        <li>사용자 입력 질문 / 답변 텍스트 (운영 / 분석 목적)</li>
        <li>접속 IP 주소 (rate limit, 비정상 트래픽 차단)</li>
        <li>사용 모드 / 응답 시간 / 토큰 수 / 비용 (운영 모니터링)</li>
        <li>인증 도입 후: 이메일 (Magic Link) — Supabase Auth</li>
      </ul>

      <h2>2. PII 자동 마스킹</h2>
      <p>
        저장 전 다음 패턴은 자동으로 <code>[REDACTED:type]</code> 으로 마스킹됩니다:
      </p>
      <ul>
        <li>한국 주민등록번호, 휴대전화번호</li>
        <li>이메일, IPv4 주소</li>
        <li>신용카드 번호 (Luhn 검증 통과 시)</li>
      </ul>
      <p>
        마스킹은 1차 방어선이며, 사용자가 의도적으로 우회하는 입력은 보호되지
        않을 수 있습니다.
      </p>

      <h2>3. 보존 기간</h2>
      <ul>
        <li>대화 세션 (질문 / 답변) — 사용자 명시 삭제까지</li>
        <li>운영 로그 (audit_log) — 90일 후 사용자 식별자 익명화</li>
        <li>관측 trace 로그 — 7일 후 자동 삭제</li>
      </ul>

      <h2>4. 외부 전송</h2>
      <ul>
        <li><strong>OpenAI</strong>: 답변 생성을 위해 질문 + 검색 결과가 OpenAI API 로
          전송됩니다. OpenAI 의 데이터 처리 정책을 따릅니다.</li>
        <li><strong>Supabase</strong> (인증 도입 후): 이메일과 세션 데이터가
          Supabase Postgres 에 저장됩니다.</li>
        <li><strong>Sentry / Slack</strong> (운영 알림): 오류 메시지 전송 시 PII 는
          마스킹 후 발송됩니다.</li>
      </ul>

      <h2>5. 사용자 권리</h2>
      <p>
        다음 권리를 행사할 수 있습니다 (인증 도입 후 자동, 그 전엔 운영자 문의):
      </p>
      <ul>
        <li>본인 데이터 익스포트 (<code>GET /api/me/export</code>) — JSON 다운로드</li>
        <li>본인 데이터 삭제 (<code>DELETE /api/me</code>) — 24시간 내 처리,
          audit_log 익명화 + 세션 cascade 삭제</li>
        <li>처리 정지 / 정정 요청</li>
      </ul>

      <h2>6. 쿠키 / 로컬 저장소</h2>
      <ul>
        <li>대화 세션은 브라우저 IndexedDB 에 저장됩니다.</li>
        <li>인증 도입 후: Supabase JWT 가 HttpOnly 쿠키로 저장됩니다.</li>
        <li>광고 / 추적 쿠키는 사용하지 않습니다.</li>
      </ul>

      <h2>7. 변경 이력</h2>
      <p>
        본 방침은 서비스 변경에 따라 갱신됩니다. 중대 변경은 사용자에게 공지합니다.
      </p>
    </LegalLayout>
  );
}
