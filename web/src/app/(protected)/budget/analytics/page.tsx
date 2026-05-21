"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Analytics are now integrated into the main budget page.
export default function BudgetAnalyticsRedirect() {
  const router = useRouter();
  useEffect(() => { router.replace("/budget"); }, [router]);
  return null;
}
