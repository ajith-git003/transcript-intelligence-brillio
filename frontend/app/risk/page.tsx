'use client'
import { useEffect, useState } from 'react'
import { fetchTranscripts, fetchRiskSummary } from '@/lib/api'
import { AlertTriangle } from 'lucide-react'

type RiskLevel = 'high' | 'medium' | 'low'

export default function RiskPage() {
  const [transcripts, setTranscripts] = useState<any[]>([])
  const [summary, setSummary] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<any>(null)
  const [filter, setFilter] = useState<RiskLevel>('high')

  useEffect(() => {
    Promise.all([fetchTranscripts({ limit: 100 }), fetchRiskSummary()])
      .then(([t, rs]) => {
        setTranscripts(t.transcripts || [])
        setSummary(rs.risk_summary || [])
        setLoading(false)
      })
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-white/40 text-sm">Loading risk analysis...</div>
    </div>
  )

  const filtered = transcripts.filter(t => t.risk_level === filter)
  const summaryMap = Object.fromEntries(summary.map(s => [s.risk_level, s]))

  const riskConfig = {
    high: { dot: 'bg-red-400', card: 'border-red-500/30 bg-red-500/10', text: 'text-red-400', ring: 'ring-red-500/30' },
    medium: { dot: 'bg-amber-400', card: 'border-amber-500/30 bg-amber-500/10', text: 'text-amber-400', ring: 'ring-amber-500/30' },
    low: { dot: 'bg-emerald-400', card: 'border-emerald-500/30 bg-emerald-500/10', text: 'text-emerald-400', ring: 'ring-emerald-500/30' },
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white">Risk Analysis</h1>
        <p className="text-white/40 text-sm mt-1">Click a card to filter by risk level</p>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-8">
        {(['high', 'medium', 'low'] as RiskLevel[]).map((level) => {
          const s = summaryMap[level] || { count: 0, avg_score: 0 }
          const cfg = riskConfig[level]
          const isActive = filter === level
          return (
            <button
              key={level}
              onClick={() => { setFilter(level); setSelected(null) }}
              className={`border rounded-xl p-5 text-left transition-all cursor-pointer ${
                isActive ? cfg.card + ' ring-1 ' + cfg.ring : 'bg-white/[0.02] border-white/[0.06] hover:bg-white/[0.05]'
              }`}
            >
              <div className="flex items-center gap-2 mb-3">
                <div className={`w-2.5 h-2.5 rounded-full ${cfg.dot}`} />
                <span className={`text-xs font-medium uppercase tracking-wider capitalize ${isActive ? cfg.text : 'text-white/40'}`}>
                  {level} Risk
                </span>
              </div>
              <p className={`text-3xl font-semibold ${isActive ? cfg.text : 'text-white/70'}`}>{s.count}</p>
              <p className="text-xs text-white/30 mt-1">Avg score: {s.avg_score?.toFixed(0)}/100</p>
            </button>
          )
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2">
          <h3 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-4">
            {filter} Risk Calls ({filtered.length})
          </h3>
          <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
            {filtered.length === 0 && (
              <div className="text-center py-8 text-white/20 text-sm">No {filter} risk calls</div>
            )}
            {filtered.map((item: any, idx: number) => (
              <button
                key={item.meeting_id + idx}
                onClick={() => setSelected(item)}
                className={`w-full text-left p-4 rounded-xl border transition-all ${
                  selected?.meeting_id === item.meeting_id
                    ? riskConfig[filter].card + ' ring-1 ' + riskConfig[filter].ring
                    : 'bg-white/[0.02] border-white/[0.05] hover:bg-white/[0.05]'
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm text-white font-medium leading-snug line-clamp-2">{item.title}</p>
                  <span className={`text-xs font-bold shrink-0 ${riskConfig[filter].text}`}>{item.risk_score}</span>
                </div>
                <div className="flex items-center gap-2 mt-2 flex-wrap">
                  <span className="text-xs text-white/30 capitalize bg-white/5 px-2 py-0.5 rounded-full">{item.call_type}</span>
                  {item.frustration_detected === 1 && (
                    <span className="text-[10px] text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded-full">Frustrated</span>
                  )}
                  {item.overall_sentiment === 'negative' && (
                    <span className="text-[10px] text-red-400 bg-red-500/10 px-2 py-0.5 rounded-full">Negative</span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="lg:col-span-3">
          {selected ? (
            <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6 sticky top-6">
              <div className="flex items-start justify-between mb-4 pb-4 border-b border-white/[0.06]">
                <div className="flex-1 mr-4">
                  <h3 className="text-base font-semibold text-white">{selected.title}</h3>
                  <p className="text-sm text-white/40 mt-1">{selected.one_line_summary}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className={`text-3xl font-bold ${riskConfig[filter].text}`}>{selected.risk_score}</p>
                  <p className="text-xs text-white/20">risk score</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-4">
                {[
                  { label: 'Call Type', value: selected.call_type },
                  { label: 'Sentiment', value: selected.overall_sentiment },
                  { label: 'Risk Level', value: selected.risk_level },
                  { label: 'Topic', value: selected.primary_topic },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-white/[0.03] rounded-lg p-3 border border-white/[0.05]">
                    <p className="text-[10px] text-white/30 uppercase tracking-wider mb-1">{label}</p>
                    <p className="text-sm text-white/70 capitalize font-medium line-clamp-2">{value || '—'}</p>
                  </div>
                ))}
              </div>
              <div className="bg-amber-500/5 border border-amber-500/10 rounded-lg p-4">
                <p className="text-xs font-semibold text-amber-400/70 uppercase tracking-wider mb-2">Summary</p>
                <p className="text-sm text-white/60">{selected.one_line_summary || 'No summary available'}</p>
              </div>
            </div>
          ) : (
            <div className="bg-white/[0.02] border-2 border-dashed border-white/[0.05] rounded-xl p-8 flex flex-col items-center justify-center text-center h-64">
              <AlertTriangle className="w-8 h-8 text-white/10 mb-3" />
              <p className="text-sm text-white/30 font-medium">Select a call to view details</p>
              <p className="text-xs text-white/20 mt-1">Click any call from the list on the left</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}