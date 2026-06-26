import { LineChart, Line, YAxis } from "recharts";

const WIDTH = 80;
const HEIGHT = 32;

export default function Sparkline({ data, color = "#4457B6" }) {
  const series = (data || []).map((v, i) => ({ i, v: v ?? 0 }));
  if (series.length === 0) {
    return <div className="text-[10px] text-[var(--ayci-ink-muted)]">-</div>;
  }
  return (
    <div style={{ width: WIDTH, height: HEIGHT }}>
      <LineChart width={WIDTH} height={HEIGHT} data={series}>
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Line
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </div>
  );
}
