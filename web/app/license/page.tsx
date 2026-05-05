import { LegalLayout } from "@/components/LegalLayout";

export const metadata = {
  title: "데이터 출처 / 저작권 — Calvin RAG Chatbot",
};

export default function LicensePage() {
  return (
    <LegalLayout title="데이터 출처 / 저작권" updatedAt="2026-05-04">
      <h2>원본 자료</h2>
      <p>
        본 챗봇이 인용하는 본문은 <strong>장 칼빈, 『기독교 강요』 한국어 번역본</strong>
        입니다. 한국어 번역본의 저작권은 원 출판사에 귀속됩니다. 본 서비스는 출판사의
        명시적 인용 동의 없이 운영되는 개인 학습 / 포트폴리오 도구이며, 상업적 용도로
        사용되지 않습니다.
      </p>

      <h2>인용 정책</h2>
      <ul>
        <li>답변 본문에 인용된 페이지 (<code>[p.N]</code>) 는 본 PDF 의 페이지 번호
          (1-indexed) 입니다.</li>
        <li>출처 카드 / 인라인 인용은 본문 발췌 (200~3000자) 와 함께 표시됩니다.</li>
        <li>발췌 문구는 학술 인용의 정당한 범위 내 사용을 의도하며, 전체 본문의
          체계적 재배포 / 데이터셋 추출은 허용되지 않습니다.</li>
      </ul>

      <h2>이용자에 대한 안내</h2>
      <ul>
        <li>본 챗봇의 답변을 외부에 게시 / 인용 시, 1차 자료 (출판본) 를 직접 확인하고
          그 인용 표기를 따라 주십시오.</li>
        <li>대량 다운로드 / 자동화 추출은 약관 위반으로 차단됩니다.</li>
        <li>출판사 / 저작권자가 본 서비스 운영의 중단 또는 인용 범위 조정을 요구할
          경우, 즉시 응합니다.</li>
      </ul>

      <h2>오픈소스 / 외부 라이브러리</h2>
      <p>
        본 서비스는 다음 오픈소스를 사용합니다 (대표):
      </p>
      <ul>
        <li>LangChain / LangGraph — MIT</li>
        <li>FAISS — MIT</li>
        <li>FastAPI — MIT</li>
        <li>Next.js / React — MIT</li>
        <li>Tailwind CSS — MIT</li>
      </ul>
      <p>
        OpenAI / Neo4j / Supabase 등 외부 서비스는 각 사의 약관을 따릅니다.
      </p>

      <h2>저작권자 / 출판사 안내</h2>
      <p>
        본 서비스 운영의 중단 또는 인용 범위 조정을 요구하실 경우,
        아래로 연락 주시면 <strong>24시간 내</strong>로 응답하고 즉시 비활성화합니다.
      </p>
      <ul>
        <li>이메일: <code>(운영자 이메일)</code></li>
        <li>요구 사항: 본문 발췌 제거 / 서비스 전체 종료 / 인용 범위 조정 등</li>
      </ul>

      <h2>이용자에게 (구매 권장)</h2>
      <p>
        본 챗봇은 발췌·요약을 통한 학습 보조 도구입니다. 칼빈 신학에 본격적으로
        관심이 있으시면 출판본 (한국어 번역본) 을 직접 구매해 읽어보시기를 권합니다.
        본 서비스는 책의 대체재가 아니라 학습 진입을 돕는 도구입니다.
      </p>

      <h2>문의</h2>
      <p>
        저작권 / 인용 / 운영 관련 문의는 운영자에게 연락 주십시오.
      </p>
    </LegalLayout>
  );
}
