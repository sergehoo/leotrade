import {
  AreaSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { useEffect, useRef } from "react"

import type { EquityPoint } from "@/api/portfolio"

/**
 * Courbe de valorisation.
 *
 * L'échelle de valeur est volontairement NON tronquée : elle inclut
 * toujours zéro quand la série reste positive. Une courbe dont l'axe
 * démarre au minimum observé transforme une variation de 0,5 % en une
 * pente spectaculaire — c'est la manière la plus commune de mentir avec
 * un graphique honnête par ailleurs.
 */
export function EquityChart({
  points,
  height = 240,
}: {
  points: EquityPoint[]
  height?: number
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const styles = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      styles.getPropertyValue(name).trim() || fallback

    const chart = createChart(container, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: `hsl(${token("--muted-foreground", "215 16% 60%")})`,
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: `hsl(${token("--border", "215 20% 20%")} / 0.4)` },
      },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.15, bottom: 0.1 } },
      timeScale: { borderVisible: false, timeVisible: false },
      crosshair: { mode: 1 },
      localization: { locale: "fr-FR" },
    })

    const series = chart.addSeries(AreaSeries, {
      lineColor: `hsl(${token("--primary", "168 70% 45%")})`,
      topColor: `hsl(${token("--primary", "168 70% 45%")} / 0.25)`,
      bottomColor: `hsl(${token("--primary", "168 70% 45%")} / 0.02)`,
      lineWidth: 2,
      // Ancre l'échelle sur zéro : sans elle, l'axe se cale sur le
      // minimum de la série et amplifie optiquement chaque variation.
      autoscaleInfoProvider: (original: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
        const result = original()
        if (!result) return result
        return {
          ...result,
          priceRange: {
            minValue: Math.min(0, result.priceRange.minValue),
            maxValue: result.priceRange.maxValue,
          },
        }
      },
    })

    chartRef.current = chart
    seriesRef.current = series

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width) chart.applyOptions({ width })
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [height])

  useEffect(() => {
    const series = seriesRef.current
    if (!series) return

    const data = points
      .map((point) => ({
        time: Math.floor(new Date(point.at).getTime() / 1000) as UTCTimestamp,
        value: Number(point.equity),
      }))
      .filter((point) => Number.isFinite(point.value))

    series.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [points])

  return <div ref={containerRef} className="w-full" aria-hidden />
}
