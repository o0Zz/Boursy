import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart, LineSeries, LineStyle, type Time } from "lightweight-charts";

export interface Series {
  label: string;
  color: string;
  data: { time: string; value: number }[];
  area?: boolean;
  dashed?: boolean;
}

export default function EquityChart({ series, height = 260 }: { series: Series[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#64748b", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(30,41,59,0.6)" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      crosshair: { mode: 0 },
      handleScroll: false,
      handleScale: false,
    });
    for (const s of series) {
      const data = s.data.map((d) => ({ time: d.time as Time, value: d.value }));
      if (s.area) {
        const area = chart.addSeries(AreaSeries, {
          lineColor: s.color,
          topColor: `${s.color}55`,
          bottomColor: `${s.color}00`,
          lineWidth: 2,
          priceLineVisible: false,
        });
        area.setData(data);
      } else {
        chart
          .addSeries(LineSeries, {
            color: s.color,
            lineWidth: 1,
            lineStyle: s.dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          })
          .setData(data);
      }
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series]);

  return (
    <div>
      {series.length > 1 && (
        <div className="mb-2 flex flex-wrap gap-4 text-xs text-slate-400">
          {series.map((s) => (
            <span key={s.label} className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-4 rounded" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
      <div ref={ref} style={{ height }} className="w-full" />
    </div>
  );
}
