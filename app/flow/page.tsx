import { MarketFlowPage } from "@/components/market-flow/MarketFlowPage";
import { marketFlowSnapshots } from "@/lib/market-flow/mock-data";

export default function FlowRoute() {
  return <MarketFlowPage snapshots={marketFlowSnapshots} />;
}
