import type { ReactNode } from "react";

/**
 * Public dashboard wrapper.
 * Read-only dashboard pages are public; the individual automation endpoints
 * enforce the owner password server-side. Keep this component as a pass-through
 * for compatibility with older App.tsx versions that still wrap routes in AuthGate.
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
