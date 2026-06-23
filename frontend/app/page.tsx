'use client'
import { useEffect, useState } from 'react'
import {
  fetchDashboard,
  fetchTopicDistribution,
  fetchSentimentByType
} from '@/lib/api'
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer
} from 'recharts'
import {
  AlertTriangle, TrendingUp, FileText,
  Eye, Activity
} from 'lucide-react'

const COLORS = ['#3b82f6', '#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#84cc16']

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        background: '#1a1a2e',
        border: '1px solid rgba(255,255,255,0.15)',
        borderRadius: '8px',
        padding: '8px 12px'
      }}>
        {label && (
          <p style={{ color: '#ffffff', fontWeight: 600, fontSize: '12px', margin: '0 0 4px 0' }}>
            {label}
          </p>
        )}
        {payload.map((entry: any, i: number) => (
          <p key={i} style={{ color: '#ffffff', fontSize: '12px', margin: '2px 0' }}>
            {entry.name}: {entry.value}
          </p>
        ))}
      </div>
    )
  }
  return null
}

export default function Dashboard() {
  const [stats, setStats] = useState<any>(null)
  const [topics, setTopics] = useState<any[]>([])
  const [sentimentData, setSentimentData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetchDashboard(),
      fetchTopicDistribution(),
      fetchSentimentByType()
    ]).then(([s, t, sent]) => {
      setStats(s)
      setTopics(t.topics?.slice(0, 8) || [])
      const byType: Record<string, any> = {}
      sent.sentiment_by_type?.forEach((row: any) => {
        if (!byType[row.call_type]) byType[row.call_type] = { call_type: row.call_type }
        byType[row.call_type][row.overall_sentiment] = row.count
      })
      setSentimentData(Object.values(byType))
      setLoading(false)
    })
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <div className="flex items-center gap-3 text-white/40">
        <Activity className="w-5 h-5 animate-pulse" />
        <span className="text-sm">Loading intelligence...</span>
      </div>
    </div>
  )

  const callTypeData = Object.entries(stats?.call_type_breakdown || {}).map(
    ([name, value]) => ({ name, value })
  )

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white">Intelligence Dashboard</h1>
        <p className="text-white/40 text-sm mt-1">
          AI analysis across {stats?.total_transcripts} enterprise call transcripts
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {[
          {
            label: 'Total Transcripts',
            value: stats?.total_transcripts,
            icon: FileText,
            color: 'text-blue-400',
            bg: 'bg-blue-500/10'
          },
          {
            label: 'High Risk Calls',
            value: stats?.high_risk_count,
            icon: AlertTriangle,
            color: 'text-red-400',
            bg: 'bg-red-500/10'
          },
          {
            label: 'Avg Sentiment',
            value: stats?.avg_sentiment_score > 0
              ? `+${stats?.avg_sentiment_score?.toFixed(2)}`
              : stats?.avg_sentiment_score?.toFixed(2),
            icon: TrendingUp,
            color: stats?.avg_sentiment_score > 0 ? 'text-emerald-400' : 'text-red-400',
            bg: stats?.avg_sentiment_score > 0 ? 'bg-emerald-500/10' : 'bg-red-500/10'
          },
          {
            label: 'Pending Reviews',
            value: stats?.human_review_pending,
            icon: Eye,
            color: 'text-amber-400',
            bg: 'bg-amber-500/10'
          }
        ].map((card) => (
          <div key={card.label} className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs text-white/40 font-medium uppercase tracking-wider">
                {card.label}
              </span>
              <div className={`w-8 h-8 rounded-lg ${card.bg} flex items-center justify-center`}>
                <card.icon className={`w-4 h-4 ${card.color}`} />
              </div>
            </div>
            <p className={`text-3xl font-semibold ${card.color}`}>{card.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Call Type Breakdown */}
        <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
          <h3 className="text-sm font-medium text-white mb-1">Call Type Breakdown</h3>
          <p className="text-xs text-white/30 mb-6">Distribution across 100 transcripts</p>
          <ResponsiveContainer width="100%" height={180}>
            <PieChart>
              <Pie
                data={callTypeData}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={75}
                paddingAngle={3}
                dataKey="value"
              >
                {callTypeData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap gap-3 mt-2">
            {callTypeData.map((item, i) => (
              <div key={item.name} className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full" style={{ background: COLORS[i] }} />
                <span className="text-xs text-white/50 capitalize">{item.name} ({item.value as number})</span>
              </div>
            ))}
          </div>
        </div>

        {/* Topic Distribution */}
        <div className="lg:col-span-2 bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
          <h3 className="text-sm font-medium text-white mb-1">Topic Distribution</h3>
          <p className="text-xs text-white/30 mb-6">LLM-classified conversation themes</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={topics} layout="vertical" margin={{ left: 0, right: 20 }}>
              <XAxis type="number" tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.3)' }} axisLine={false} tickLine={false} />
              <YAxis
                type="category"
                dataKey="primary_topic"
                tick={{ fontSize: 9, fill: 'rgba(255,255,255,0.4)' }}
                axisLine={false}
                tickLine={false}
                width={160}
                tickFormatter={(v) => v.length > 22 ? v.slice(0, 22) + '…' : v}
              />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                {topics.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Sentiment by Call Type */}
      <div className="bg-white/[0.03] border border-white/[0.06] rounded-xl p-6">
        <h3 className="text-sm font-medium text-white mb-1">Sentiment by Call Type</h3>
        <p className="text-xs text-white/30 mb-6">
          Emotional distribution across support, external, and internal calls
        </p>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={sentimentData}>
            <XAxis
              dataKey="call_type"
              tick={{ fontSize: 11, fill: 'rgba(255,255,255,0.4)' }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) => v.charAt(0).toUpperCase() + v.slice(1)}
            />
            <YAxis tick={{ fontSize: 10, fill: 'rgba(255,255,255,0.3)' }} axisLine={false} tickLine={false} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="positive" fill="#10b981" radius={[4, 4, 0, 0]} name="Positive" />
            <Bar dataKey="neutral" fill="#6b7280" radius={[4, 4, 0, 0]} name="Neutral" />
            <Bar dataKey="negative" fill="#ef4444" radius={[4, 4, 0, 0]} name="Negative" />
          </BarChart>
        </ResponsiveContainer>
        <div className="flex gap-4 mt-3">
          {['positive', 'neutral', 'negative'].map((s) => (
            <div key={s} className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{
                background: s === 'positive' ? '#10b981' : s === 'negative' ? '#ef4444' : '#6b7280'
              }} />
              <span className="text-xs text-white/40 capitalize">{s}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}