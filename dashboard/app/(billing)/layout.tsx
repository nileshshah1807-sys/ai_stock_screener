import { BillingFrame } from "@/components/billing/billing-frame";
import { getSession } from "@/lib/auth";

export default async function BillingLayout({ children }: LayoutProps<"/">) {
  return <BillingFrame session={await getSession()}>{children}</BillingFrame>;
}
