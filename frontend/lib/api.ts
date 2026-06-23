// frontend/lib/api.ts
// Central API client — all backend calls go through here

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export async function fetchDashboard() {
  const res = await fetch(`${API_URL}/api/dashboard`)
  return res.json()
}

export async function fetchTopicDistribution() {
  const res = await fetch(`${API_URL}/api/dashboard/topic-distribution`)
  return res.json()
}

export async function fetchSentimentByType() {
  const res = await fetch(`${API_URL}/api/dashboard/sentiment-by-type`)
  return res.json()
}

export async function fetchTranscripts(params?: {
  call_type?: string
  risk_level?: string
  limit?: number
}) {
  const query = new URLSearchParams()
  if (params?.call_type) query.append('call_type', params.call_type)
  if (params?.risk_level) query.append('risk_level', params.risk_level)
  if (params?.limit) query.append('limit', params.limit.toString())
  const res = await fetch(`${API_URL}/api/transcripts?${query}`)
  return res.json()
}

export async function fetchHighRisk() {
  const res = await fetch(`${API_URL}/api/risk/high`)
  return res.json()
}

export async function fetchRiskSummary() {
  const res = await fetch(`${API_URL}/api/risk/summary`)
  return res.json()
}

export async function fetchEscalations() {
  const res = await fetch(`${API_URL}/api/sentiment/escalations`)
  return res.json()
}

export async function fetchPendingReviews() {
  const res = await fetch(`${API_URL}/api/review/pending`)
  return res.json()
}

export async function sendChatMessage(message: string, history: Array<{role: string, content: string}>) {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history })
  })
  return res.json()
}