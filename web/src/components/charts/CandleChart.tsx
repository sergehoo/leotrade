import {
  CandlestickSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { useEffect, useRef } from "react"

import type { Candle } from "@/api/market"

/**
 * Graphique en chandeliers.
 *
 * Les couleurs suivent la convention du projet : le vert et le rouge
 * sont réservés au sens financier — ici hausse et baisse de la bougie —
 * et jamais décoratifs.
 *
 * L'échelle de prix n'est pas tronquée. Un axe qui démarre au minimum de
 * la série amplifie visuellement des variations de quelques dixièmes de
 * pour cent, ce qui est précisément le genre de graphique sur lequel on
 * prend une mauvaise décision.
 */
export function CandleChart({
  candles,
  height = 320,
}: {
  candles: Candle[]
  height?: number
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null)

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
        vertLines: { color: `hsl(${token("--border", "215 20% 20%")} / 0.4)` },
        horzLines: { color: `hsl(${token("--border", "215 20% 20%")} / 0.4)` },
      },
      rightPriceScale: {
        borderVisible: false,
        // Marges symétriques : ne pas coller la série aux bords évite de
        // donner l'illusion que le prix touche un plafond ou un plancher.
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: { borderVisible: false, timeVisible: true },
      crosshair: { mode: 1 },
      localization: { locale: "fr-FR" },
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: `hsl(${token("--gain", "152 60% 45%")})`,
      downColor: `hsl(${token("--loss", "0 72% 60%")})`,
      borderVisible: false,
      wickUpColor: `hsl(${token("--gain", "152 60% 45%")})`,
      wickDownColor: `hsl(${token("--loss", "0 72% 60%")})`,
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

    const data = candles
      .map((candle) => ({
        time: Math.floor(new Date(candle.open_time).getTime() / 1000) as UTCTimestamp,
        open: Number(candle.open),
        high: Number(candle.high),
        low: Number(candle.low),
        close: Number(candle.close),
      }))
      // Une bougie incomplète déformerait l'échelle ; on l'écarte plutôt
      // que de la tracer à zéro.
      .filter(
        (point) =>
          Number.isFinite(point.open) &&
          Number.isFinite(point.high) &&
          Number.isFinite(point.low) &&
          Number.isFinite(point.close),
      )

    series.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [candles])

  return <div ref={containerRef} className="w-full" aria-hidden />
}
