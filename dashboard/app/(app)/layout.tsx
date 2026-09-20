import { requireAccess } from "@/lib/auth";
import { mark } from "@/lib/trace";

/**
 * Authorization for every signed-in route.
 *
 * This used to also fetch the run and render the chrome. Both moved down to
 * `[market]/layout.tsx`, because both depend on which market is being viewed
 * and a parent layout cannot read a child segment's params. What is left is
 * the one thing that is true of every route below regardless of market: the
 * viewer must be on the invite list.
 *
 * It stays a layout rather than middleware so the redirect happens before any
 * page work, and so layouts below it still do not re-render on navigation.
 */
export default async function AppLayout({ children }: LayoutProps<"/">) {
  mark("(app)/layout RENDERED");
  await requireAccess();
  return <>{children}</>;
}
