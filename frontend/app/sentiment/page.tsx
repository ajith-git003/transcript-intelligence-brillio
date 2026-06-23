'use client'
import { useEffect, useState } from 'react'
import { fetchEscalations, fetchSentimentByType } from '@/lib/api'
import { TrendingUp, TrendingDown, AlertCircle } from 'lucide-react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'

export default function SentimentPage() {
  const [escalations, setEscalations] = useState<any[]>([])
  const [sentimentData, setSentimentData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([fetchEscalations(), fetchSentimentByType()]).then(([e, s]) => {
      setEscalations(e.escalations || [])
      const byType: Record<string, any> = {}
      s.sentiment_by_type?.forEach((row: any) => {
        if (!byType[row.call_type]) byType[row.call_type] = { call_type: row.call_type }
        byType[row.call_type][row.overall_sentiment] = row.count
      })
      setSentimentData(Object.values(byType))
      setLoading(false)
    })
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-white/40 text-sm">Loading sentiment data...</div>
    </div>
  )

  // Converts -1.0 to +1.0 score into a readable color
  const scoreColor = (score: number) => {
    if (score >= 0.2) return 'text-emerald-400'
    if (score <= -0.2) return 'text-red-400'
    return 'text-white/40'
  }

  // Converts score to a human-readable label
  const scoreLabel = (score: number) => {
    if (score >= 0.2) return 'positive'
    if (score <= -0.2) return 'negative'
    return 'neutral'
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white">Sentiment Intelligence</h1>
        <p className="text-white/40 text-sm mt-1">Emotional trends and escalation detection</p>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {[
          {
            label: 'Escalations Detected',
            value: escalations.length,
            sub: 'Calls needing manager attention',
            icon: AlertCircle,
            color: 'text-red-400',
            bg: 'bg-red-500/10'
          },
          {
            label: 'Frustration Flagged',
            value: escalations.filter(e => e.frustration_detected).length,
            sub: 'Customers showing frustration',
            icon: TrendingDown,
            color: 'text-amber-400',
            bg: 'bg-amber-500/10'
          },
          {
            label: 'Resolved Calls',
            value: escalations.filter(e => e.resolution_detected).length,
            sub: 'Issues resolved during call',
            icon: TrendingUp,
            color: 'text-emerald-400',
            bg: 'bg-emerald-500/10'
          },
        ].map(card => (
          <div key={card.label} className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-white/40 uppercase tracking-wider font-medium">{card.label}</span>
              <div className={`w-8 h-8 rounded-lg ${card.bg} flex items-center justify-center`}>
                <card.icon className={`w-4 h-4 ${card.color}`} />
              </div>
            </div>
            <p className={`text-3xl font-semibold ${card.color}`}>{card.value}</p>
            <p className="text-xs text-white/20 mt-1">{card.sub}</p>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6 mb-6">
        <h3 className="text-sm font-medium text-white mb-1">Sentiment Distribution by Call Type</h3>
        <p className="text-xs text-white/30 mb-5">
          Support calls skew negative — external calls are mixed — internal calls are mostly neutral
        </p>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={sentimentData}>
            <XAxis
              dataKey="call_type"
              tick={{ fontSize: 11, fill: 'rgba(255,255,255,0.4)' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={v => v.charAt(0).toUpperCase() + v.slice(1)}
            />
            <YAxis
              tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.3)' }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              contentStyle={{
                background: '#1a1a2e',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '8px',
                color: '#fff',
                fontSize: '12px'
              }}
            />
            <Bar dataKey="positive" fill="#10b981" radius={[4, 4, 0, 0]} name="Positive" />
            <Bar dataKey="neutral" fill="#6b7280" radius={[4, 4, 0, 0]} name="Neutral" />
            <Bar dataKey="negative" fill="#ef4444" radius={[4, 4, 0, 0]} name="Negative" />
          </BarChart>
        </ResponsiveContainer>
        <div className="flex gap-4 mt-3">
          {[['Positive', '#10b981'], ['Neutral', '#6b7280'], ['Negative', '#ef4444']].map(([s, c]) => (
            <div key={s} className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{ background: c }} />
              <span className="text-xs text-white/30">{s}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Escalations List */}
      <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-white/[0.06]">
          <h3 className="text-sm font-medium text-white">
            Escalation-Flagged Calls ({escalations.length})
          </h3>
          {/* ← This explains the score column so it's no longer confusing */}
          <p className="text-xs text-white/30 mt-1">
            Sentiment score: -1.0 = very negative · 0 = neutral · +1.0 = very positive
          </p>
        </div>
        <div className="divide-y divide-white/[0.04]">
          {escalations.slice(0, 20).map((e: any, idx: number) => (
            <div key={`${e.meeting_id}-${idx}`} className="px-5 py-3.5 flex items-center gap-4 hover:bg-white/[0.02] transition-colors">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-white font-medium truncate">{e.title}</p>
                <p className="text-xs text-white/30 mt-0.5 truncate">{e.one_line_summary}</p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-xs text-white/40 capitalize bg-white/5 px-2 py-0.5 rounded-full">
                  {e.call_type}
                </span>
                {e.frustration_detected === 1 && (
                  <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full font-medium">
                    Frustrated
                  </span>
                )}
                {e.resolution_detected === 1 && (
                  <span className="text-[10px] text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full font-medium">
                    Resolved
                  </span>
                )}
                {/* Score with label — no longer just a confusing red number */}
                <div className="text-right min-w-[56px]">
                  <p className={`text-xs font-bold ${scoreColor(e.sentiment_score)}`}>
                    {e.sentiment_score > 0 ? '+' : ''}{e.sentiment_score?.toFixed(2)}
                  </p>
                  <p className="text-[9px] text-white/20 capitalize">
                    {scoreLabel(e.sentiment_score)}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}