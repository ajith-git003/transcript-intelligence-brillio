'use client'
import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { fetchTranscripts } from '@/lib/api'
import { FileText, Search } from 'lucide-react'

export default function TranscriptsPage() {
  const router = useRouter()
  const [transcripts, setTranscripts] = useState<any[]>([])
  const [filtered, setFiltered] = useState<any[]>([])
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchTranscripts({ limit: 100 }).then(data => {
      setTranscripts(data.transcripts || [])
      setFiltered(data.transcripts || [])
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    let result = transcripts
    if (typeFilter !== 'all') result = result.filter(t => t.call_type === typeFilter)
    if (search) result = result.filter(t =>
      t.title?.toLowerCase().includes(search.toLowerCase())
    )
    setFiltered(result)
  }, [search, typeFilter, transcripts])

  const getRiskBadge = (level: string) => ({
    high: 'text-red-400 bg-red-500/10',
    medium: 'text-amber-400 bg-amber-500/10',
    low: 'text-emerald-400 bg-emerald-500/10',
  }[level] || 'text-white/40 bg-white/5')

  const getSentimentColor = (s: string) => ({
    positive: 'text-emerald-400',
    negative: 'text-red-400',
    neutral: 'text-white/40',
  }[s] || 'text-white/40')

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-white/40 text-sm">Loading transcripts...</div>
    </div>
  )

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white">Transcripts</h1>
        <p className="text-white/40 text-sm mt-1">
          {filtered.length} of {transcripts.length} calls — click any row to view full analysis
        </p>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-6">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/20" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search transcripts..."
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-lg pl-9 pr-4 py-2.5 text-sm text-white placeholder-white/20 outline-none focus:border-blue-500/40"
          />
        </div>
        {['all', 'support', 'external', 'internal'].map(type => (
          <button
            key={type}
            onClick={() => setTypeFilter(type)}
            className={`px-4 py-2 rounded-lg text-sm capitalize transition-all ${
              typeFilter === type
                ? 'bg-white/15 text-white'
                : 'bg-white/[0.03] text-white/40 hover:text-white/60 border border-white/[0.06]'
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-white/[0.06]">
              {['Title', 'Type', 'Topic', 'Sentiment', 'Risk', 'Duration'].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-white/30 uppercase tracking-wider">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {filtered.map((t: any, idx: number) => (
              <tr
                key={`${t.meeting_id}-${idx}`}
                onClick={() => router.push(`/transcripts/${t.meeting_id}`)}
                className="hover:bg-white/[0.04] transition-colors cursor-pointer"
              >
                <td className="px-4 py-3">
                  <div className="flex items-start gap-2">
                    <FileText className="w-4 h-4 text-white/20 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-white font-medium line-clamp-1 max-w-xs">{t.title}</p>
                      <p className="text-xs text-white/30 mt-0.5">{t.start_time?.slice(0, 10)}</p>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className="text-xs text-white/50 capitalize bg-white/5 px-2 py-1 rounded-full">
                    {t.call_type}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <p className="text-xs text-white/40 max-w-[140px] line-clamp-2">{t.primary_topic}</p>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-medium capitalize ${getSentimentColor(t.overall_sentiment)}`}>
                    {t.overall_sentiment}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs font-medium px-2 py-1 rounded-full capitalize ${getRiskBadge(t.risk_level)}`}>
                    {t.risk_level}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className="text-xs text-white/30">{t.duration_minutes?.toFixed(0)}m</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}