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

  const isActivePending = session.pendingIds.has(session.active.id);

  return (
    <main className="h-screen flex">
      <SessionSidebar
        sessions={session.sessions}
        activeId={session.activeId}
        pendingIds={session.pendingIds}
        onSelect={session.setActive}
        onNew={() => session.createNew("auto")}
        onDelete={session.remove}
      />
      <ChatPanel
        session={session.active}
        onUpdate={session.updateActive}
        onUpdateById={session.updateById}
        isPending={isActivePending}
        markPending={session.markPending}
      />
    </main>
  );
}
