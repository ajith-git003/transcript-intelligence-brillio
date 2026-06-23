'use client'
import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, AlertTriangle, TrendingUp, FileText, Clock, Users } from 'lucide-react'

export default function TranscriptDetailPage() {
  const params = useParams()
  const router = useRouter()
  const [transcript, setTranscript] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

  useEffect(() => {
    if (params.id) {
      fetch(`${API_URL}/api/transcripts/${params.id}`)
        .then(r => r.json())
        .then(data => { setTranscript(data); setLoading(false) })
        .catch(() => setLoading(false))
    }
  }, [params.id])

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-white/40 text-sm">Loading transcript...</div>
    </div>
  )

  if (!transcript) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-white/40 text-sm">Transcript not found</div>
    </div>
  )

  const riskColor = (level: string) => ({
    high: 'text-red-400 bg-red-500/10 border-red-500/20',
    medium: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
    low: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  }[level] || 'text-white/40 bg-white/5 border-white/10')

  const sentimentColor = (s: string) => ({
    positive: 'text-emerald-400',
    negative: 'text-red-400',
    neutral: 'text-white/40',
  }[s] || 'text-white/40')

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-white/40 hover:text-white/70 text-sm mb-6 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Transcripts
      </button>

      {/* Header */}
      <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6 mb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h1 className="text-xl font-semibold text-white">{transcript.title}</h1>
            <p className="text-white/50 text-sm mt-2">{transcript.one_line_summary}</p>
          </div>
          <span className={`text-xs font-medium px-3 py-1.5 rounded-full border capitalize shrink-0 ${riskColor(transcript.risk_level)}`}>
            {transcript.risk_level} risk
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5 pt-5 border-t border-white/[0.06]">
          {[
            { icon: FileText, label: 'Call Type', value: transcript.call_type },
            { icon: Clock, label: 'Duration', value: `${transcript.duration_minutes?.toFixed(0)} min` },
            { icon: TrendingUp, label: 'Sentiment', value: transcript.overall_sentiment },
            { icon: Users, label: 'Organizer', value: transcript.organizer_email?.split('@')[0] },
          ].map(({ icon: Icon, label, value }) => (
            <div key={label} className="bg-white/[0.03] rounded-lg p-3">
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className="w-3 h-3 text-white/30" />
                <p className="text-[10px] text-white/30 uppercase tracking-wider">{label}</p>
              </div>
              <p className={`text-sm font-medium capitalize ${label === 'Sentiment' ? sentimentColor(value) : 'text-white/70'}`}>
                {value}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Topic + Risk */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Topic */}
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
          <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-3">Topic Analysis</h3>
          <p className="text-sm font-medium text-blue-400 mb-3">{transcript.primary_topic}</p>
          {transcript.themes?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-3">
              {transcript.themes.map((t: string, i: number) => (
                <span key={i} className="text-[10px] bg-white/5 border border-white/10 text-white/50 px-2 py-0.5 rounded-full">{t}</span>
              ))}
            </div>
          )}
          {transcript.keywords?.length > 0 && (
            <div>
              <p className="text-[10px] text-white/20 uppercase tracking-wider mb-1.5">Keywords</p>
              <div className="flex flex-wrap gap-1">
                {transcript.keywords.map((k: string, i: number) => (
                  <span key={i} className="text-[10px] bg-blue-500/10 border border-blue-500/20 text-blue-400/70 px-2 py-0.5 rounded-full">{k}</span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Risk */}
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
          <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-3">Risk Analysis</h3>
          <div className="flex items-center gap-3 mb-3">
            <span className={`text-2xl font-bold ${riskColor(transcript.risk_level).split(' ')[0]}`}>
              {transcript.risk_score?.toFixed(0)}
            </span>
            <span className="text-xs text-white/30">/ 100 risk score</span>
          </div>
          {transcript.churn_indicators?.length > 0 && (
            <div className="mb-3">
              <p className="text-[10px] text-white/20 uppercase tracking-wider mb-1.5">Indicators</p>
              {transcript.churn_indicators.map((ind: string, i: number) => (
                <div key={i} className="flex items-start gap-1.5 mb-1">
                  <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0 mt-0.5" />
                  <span className="text-xs text-white/50">{ind}</span>
                </div>
              ))}
            </div>
          )}
          {transcript.citations?.length > 0 && (
            <div>
              <p className="text-[10px] text-white/20 uppercase tracking-wider mb-1.5">Risk Evidence</p>
              {transcript.citations.map((cite: string, i: number) => (
                <blockquote key={i} className="border-l-2 border-red-500/30 pl-2 mb-1.5">
                  <p className="text-xs text-white/40 italic">"{cite}"</p>
                </blockquote>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ← NEW: Sentiment Key Moments — shows for ALL sentiment types */}
      {transcript.key_moments?.length > 0 && (
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5 mb-6">
          <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-1">
            Key Moments
          </h3>
          <p className="text-[10px] text-white/20 mb-3">
            Sentences that most influenced the{' '}
            <span className={sentimentColor(transcript.overall_sentiment)}>
              {transcript.overall_sentiment}
            </span>{' '}
            sentiment score
          </p>
          <div className="space-y-2">
            {transcript.key_moments.map((moment: string, i: number) => (
              <div key={i} className={`border-l-2 pl-3 py-0.5 ${
                transcript.overall_sentiment === 'positive'
                  ? 'border-emerald-500/40'
                  : transcript.overall_sentiment === 'negative'
                  ? 'border-red-500/40'
                  : 'border-white/20'
              }`}>
                <p className="text-xs text-white/50 italic">"{moment}"</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Key Findings & Recommendations */}
      {(transcript.key_findings?.length > 0 || transcript.recommendations?.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {transcript.key_findings?.length > 0 && (
            <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-3">Key Findings</h3>
              <div className="space-y-2">
                {transcript.key_findings.map((f: string, i: number) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="text-xs font-bold text-white/20 shrink-0 mt-0.5">{i + 1}</span>
                    <p className="text-sm text-white/60">{f}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {transcript.recommendations?.length > 0 && (
            <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-3">Recommendations</h3>
              <div className="space-y-2">
                {transcript.recommendations.map((r: string, i: number) => (
                  <div key={i} className="flex items-start gap-2 bg-blue-500/5 border border-blue-500/10 rounded-lg p-2.5">
                    <span className="text-xs font-bold text-blue-400 shrink-0 mt-0.5">{i + 1}</span>
                    <p className="text-sm text-white/60">{r}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Sentiment Arc */}
      {transcript.sentiment_arc?.length > 0 && (
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5 mb-6">
          <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-3">Sentiment Arc</h3>
          <div className="flex items-center gap-3">
            {transcript.sentiment_arc.map((arc: string, i: number) => (
              <div key={i} className="flex items-center gap-2">
                {i > 0 && <span className="text-white/20">→</span>}
                <span className={`text-sm font-medium capitalize px-3 py-1 rounded-full ${
                  arc === 'positive' ? 'bg-emerald-500/10 text-emerald-400' :
                  arc === 'negative' ? 'bg-red-500/10 text-red-400' :
                  'bg-white/5 text-white/40'
                }`}>{arc}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-white/20 mt-2">
            {transcript.sentiment_arc[0] === 'negative' && transcript.sentiment_arc[transcript.sentiment_arc.length - 1] === 'positive'
              ? '✓ Call resolved positively'
              : transcript.sentiment_arc.every((a: string) => a === 'negative')
              ? '⚠ Consistently negative — escalation risk'
              : 'Sentiment progression through the call'}
          </p>
        </div>
      )}

      {/* Human Review Flag */}
      {transcript.human_review_required === 1 && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-400">Human Review Required</p>
            <p className="text-xs text-white/40 mt-0.5">
              {transcript.review_reason || 'Flagged by AI governance system'}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}