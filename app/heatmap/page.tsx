import { HeatmapPage } from "@/components/heatmap/HeatmapPage";
import { getRealTransactionHeatmapData } from "@/lib/heatmap/real-transaction-data";

export default function SeoulHeatmapRoute() {
  const heatmapData = getRealTransactionHeatmapData();

  return <HeatmapPage initialData={heatmapData} />;
}
