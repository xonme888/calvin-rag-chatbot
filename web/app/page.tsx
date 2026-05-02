"use client";

import { ChatPanel } from "@/components/ChatPanel";
import { SessionSidebar } from "@/components/SessionSidebar";
import { useSessions } from "@/lib/sessionStore";

export default function HomePage() {
  const session = useSessions();

  if (!session.ready || !session.active) {
    return (
      <main className="h-screen flex items-center justify-center text-sm text-slate-400">
        세션 로딩 중…
      </main>
    );
  }

  return (
    <main className="h-screen flex">
      <SessionSidebar
        sessions={session.sessions}
        activeId={session.activeId}
        onSelect={session.setActive}
        onNew={() => session.createNew(session.active?.mode ?? "hybrid")}
        onDelete={session.remove}
      />
      <ChatPanel session={session.active} onUpdate={session.updateActive} />
    </main>
  );
}
