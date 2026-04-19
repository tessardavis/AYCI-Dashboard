import { LineChart, Line, YAxis, ResponsiveContainer } from "recharts";

export default function Sparkline({ data, color = "#0EA5E9" }) {
  const series = (data || []).map((v, i) => ({ i, v: v ?? 0 }));
  if (series.length === 0) {
    return <div className="text-[10px] text-[var(--ayci-ink-muted)]">—</div>;
  }
  return (
    <div className="w-20 h-8">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series}>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
