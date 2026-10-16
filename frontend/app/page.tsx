import type { Metadata } from "next";
import { LandingPage } from "@/components/landing/landing-page";

export const metadata: Metadata = {
  title: "Wali | Clearer finances, one conversation",
  description:
    "Explore transaction reconciliation, cash-flow forecasting and invoice review with Wali, an AI finance assistant using synthetic business data.",
};

export default function Home() {
  return <LandingPage />;
}
