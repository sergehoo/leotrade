import {
  AreaSeries,
  ColorType,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts"
import { useEffect, useRef } from "react"

import type { EquityPoint } from "@/api/portfolio"

/**
 * Courbe de valorisation.
 *
 * L'échelle inclut toujours zéro, DANS LES DEUX SENS. Une première
 * version n'ancrait que vers le bas (`Math.min(0, minValue)`) : sur une
 * série entièrement négative — une valorisation peut l'être, rien ne
 * borne le champ — zéro n'entrait jamais dans la plage et l'axe se
 * recalait sur l'amplitude observée. Un portefeuille à −464 000 dérivant
 * de 0,1 % était alors rendu comme un effondrement pleine hauteur.
 *
 * Une ligne de zéro est tracée dès que la série touche ou franchit le
 * négatif. Sans elle, l'aire d'une courbe négative est peinte du même
 * dégradé que celle d'une courbe positive, et le passage sous zéro — le
 * seul point qui compte — n'est marqué par rien.
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
  const zeroLineRef = useRef<IPriceLine | null>(null)

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
      // Ancrage bidirectionnel : zéro appartient toujours à la plage,
      // que la série soit positive, négative ou à cheval.
      autoscaleInfoProvider: (original: () => { priceRange: { minValue: number; maxValue: number } } | null) => {
        const result = original()
        if (!result) return result
        return {
          ...result,
          priceRange: {
            minValue: Math.min(0, result.priceRange.minValue),
            maxValue: Math.max(0, result.priceRange.maxValue),
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

    // Ligne de zéro, seulement quand elle a un sens : sur une série
    // strictement positive elle encombrerait le bas du cadre sans rien
    // apprendre. Dès que la valorisation touche le négatif, c'est la
    // seule référence qui distingue « en baisse » de « à découvert ».
    if (zeroLineRef.current) {
      series.removePriceLine(zeroLineRef.current)
      zeroLineRef.current = null
    }
    if (data.some((point) => point.value < 0)) {
      zeroLineRef.current = series.createPriceLine({
        price: 0,
        color: `hsl(${getComputedStyle(document.documentElement)
          .getPropertyValue("--loss")
          .trim() || "0 72% 60%"})`,
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: "zéro",
      })
    }

    chartRef.current?.timeScale().fitContent()
  }, [points])

  return <div ref={containerRef} className="w-full" aria-hidden />
}
