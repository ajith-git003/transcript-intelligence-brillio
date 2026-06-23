'use client'
import { useState, useRef, useEffect } from 'react'
import { sendChatMessage } from '@/lib/api'
import { Send, Bot, User, FileText, Loader2 } from 'lucide-react'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sourceTitles?: string[]
}

const SUGGESTED = [
  "What are the top customer complaints?",
  "Which customers are at highest churn risk?",
  "What features are customers requesting most?",
  "Which calls had the most negative sentiment?",
  "Show me escalation patterns across support calls",
]

function MessageContent({ content }: { content: string }) {
  const parts = content.split(/(\*\*[^*]+\*\*)/g)
  return (
    <p className="text-sm leading-relaxed text-white/80 whitespace-pre-wrap">
      {parts.map((part, i) =>
        part.startsWith('**') && part.endsWith('**')
          ? <strong key={i} className="font-semibold text-white">{part.slice(2, -2)}</strong>
          : part
      )}
    </p>
  )
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (text?: string) => {
    const message = text || input.trim()
    if (!message || loading) return
    setMessages(prev => [...prev, { role: 'user', content: message }])
    setInput('')
    setLoading(true)
    try {
      const history = messages.map(m => ({ role: m.role, content: m.content }))
      const data = await sendChatMessage(message, history)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer,
        sourceTitles: data.source_titles
      }])
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Failed to get response. Please ensure the API is running.'
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-8 py-5 border-b border-white/5 shrink-0">
        <h1 className="text-lg font-semibold text-white">AI Intelligence Chat</h1>
        <p className="text-white/40 text-xs mt-0.5">Ask questions about your transcript data — powered by RAG</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-8 py-6">
        {messages.length === 0 && (
          <div className="max-w-2xl mx-auto">
            <div className="text-center mb-8 pt-4">
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center mx-auto mb-4">
                <Bot className="w-6 h-6 text-white" />
              </div>
              <h2 className="text-lg font-medium text-white">What would you like to know?</h2>
              <p className="text-white/30 text-sm mt-1">I have access to 100 analyzed enterprise call transcripts</p>
            </div>
            <div className="grid grid-cols-1 gap-2">
              {SUGGESTED.map((q) => (
                <button key={q} onClick={() => send(q)}
                  className="text-left px-4 py-3 rounded-xl bg-white/[0.03] border border-white/[0.06] hover:bg-white/[0.06] transition-all text-sm text-white/60 hover:text-white/80">
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Message thread — constrained width, centered */}
        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
              {/* Avatar */}
              <div className={`w-7 h-7 rounded-lg shrink-0 flex items-center justify-center ${
                msg.role === 'user'
                  ? 'bg-blue-500/20'
                  : 'bg-gradient-to-br from-blue-500 to-violet-600'
              }`}>
                {msg.role === 'user'
                  ? <User className="w-3.5 h-3.5 text-blue-400" />
                  : <Bot className="w-3.5 h-3.5 text-white" />}
              </div>

              {/* Bubble */}
              <div className="flex-1 max-w-[85%]">
                <div className={`rounded-2xl px-4 py-3 ${
                  msg.role === 'user'
                    ? 'bg-blue-600 rounded-tr-sm ml-auto w-fit max-w-full'
                    : 'bg-white/[0.05] border border-white/[0.08] rounded-tl-sm'
                }`}>
                  {msg.role === 'user'
                    ? <p className="text-sm text-white">{msg.content}</p>
                    : <MessageContent content={msg.content} />
                  }
                </div>

                {/* Sources */}
                {msg.sourceTitles && msg.sourceTitles.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="text-[10px] text-white/20 self-center">Sources:</span>
                    {msg.sourceTitles.slice(0, 3).map((title, j) => (
                      <span key={j} className="inline-flex items-center gap-1 text-[10px] text-white/30 bg-white/[0.03] border border-white/[0.05] px-2 py-1 rounded-full">
                        <FileText className="w-2.5 h-2.5" />
                        {title.length > 40 ? title.slice(0, 40) + '…' : title}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded-lg shrink-0 bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
                <Bot className="w-3.5 h-3.5 text-white" />
              </div>
              <div className="bg-white/[0.05] border border-white/[0.08] rounded-2xl rounded-tl-sm px-4 py-3">
                <Loader2 className="w-4 h-4 text-white/30 animate-spin" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="px-8 py-5 border-t border-white/5 shrink-0">
        <div className="flex gap-3 max-w-3xl mx-auto">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
            placeholder="Ask about your transcripts..."
            className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-3 text-sm text-white placeholder-white/20 outline-none focus:border-blue-500/40 transition-colors"
          />
          <button onClick={() => send()} disabled={!input.trim() || loading}
            className="w-10 h-10 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center transition-colors shrink-0 self-end">
            <Send className="w-4 h-4 text-white" />
          </button>
        </div>
      </div>
    </div>
  )
}