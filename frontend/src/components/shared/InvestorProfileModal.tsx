import { useState } from 'react'
import { Shield, Scale, Flame, HelpCircle, ChevronLeft, LogOut } from 'lucide-react'
import { setInvestorProfileApi } from '@/lib/api'
import { useAuth, type InvestorProfile } from '@/lib/auth'

type Mode = 'choose' | 'test' | 'result'

interface Question {
  q: string
  options: { label: string; pts: number }[]
}

const QUESTIONS: Question[] = [
  {
    q: '¿Cuál es tu horizonte de inversión principal?',
    options: [
      { label: 'Menos de 1 año (corto plazo)',     pts: 1 },
      { label: 'Entre 1 y 5 años',                 pts: 2 },
      { label: 'Más de 5 años',                    pts: 3 },
    ],
  },
  {
    q: 'Si tu cartera cae 20% en un mes, ¿qué hacés?',
    options: [
      { label: 'Vendo todo para evitar más pérdidas', pts: 1 },
      { label: 'Espero a que se recupere',            pts: 2 },
      { label: 'Compro más, es una oportunidad',      pts: 3 },
    ],
  },
  {
    q: '¿Qué porcentaje de tu capital estás dispuesto a perder en el peor escenario?',
    options: [
      { label: 'Hasta 5%',           pts: 1 },
      { label: 'Entre 10% y 20%',    pts: 2 },
      { label: 'Más del 20%',        pts: 3 },
    ],
  },
  {
    q: '¿Cuál es tu experiencia previa invirtiendo?',
    options: [
      { label: 'Ninguna o muy poca',                  pts: 1 },
      { label: 'Algo, plazos fijos / fondos / bonos', pts: 2 },
      { label: 'Bastante, opero acciones regularmente', pts: 3 },
    ],
  },
  {
    q: '¿Cuál es tu objetivo principal?',
    options: [
      { label: 'Preservar capital, ganarle a la inflación', pts: 1 },
      { label: 'Crecimiento moderado y sostenido',          pts: 2 },
      { label: 'Maximizar retorno aunque haya volatilidad', pts: 3 },
    ],
  },
]

function classifyScore(total: number): InvestorProfile {
  // Total entre 5 y 15
  if (total <= 8)  return 'conservador'
  if (total <= 12) return 'moderado'
  return 'agresivo'
}

const PROFILE_INFO: Record<NonNullable<InvestorProfile>, { label: string; desc: string; icon: any; color: string }> = {
  conservador: {
    label: 'Conservador',
    desc:  'Priorizás preservar el capital. Buscás inversiones de bajo riesgo y volatilidad reducida.',
    icon:  Shield,
    color: '#22c55e',
  },
  moderado: {
    label: 'Moderado',
    desc:  'Aceptás cierto riesgo a cambio de mejor retorno. Diversificás entre activos defensivos y de crecimiento.',
    icon:  Scale,
    color: '#3b82f6',
  },
  agresivo: {
    label: 'Agresivo',
    desc:  'Buscás máximo retorno y tolerás alta volatilidad. Operás activos de mayor riesgo.',
    icon:  Flame,
    color: '#f59e0b',
  },
}

export default function InvestorProfileModal() {
  const { setInvestorProfile, logout, username } = useAuth()
  const [mode, setMode]       = useState<Mode>('choose')
  const [answers, setAnswers] = useState<number[]>([])
  const [step, setStep]       = useState(0)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  const [result, setResult]   = useState<NonNullable<InvestorProfile> | null>(null)

  const submit = async (profile: NonNullable<InvestorProfile>) => {
    setError('')
    setSaving(true)
    try {
      await setInvestorProfileApi(profile)
      setInvestorProfile(profile)
    } catch (e: any) {
      setError(e.message || 'Error al guardar el perfil')
      setSaving(false)
    }
  }

  const handleAnswer = (pts: number) => {
    const next = [...answers, pts]
    setAnswers(next)
    if (step + 1 < QUESTIONS.length) {
      setStep(step + 1)
    } else {
      const total = next.reduce((a, b) => a + b, 0)
      const profile = classifyScore(total)!
      setResult(profile)
      setMode('result')
    }
  }

  const resetTest = () => {
    setAnswers([])
    setStep(0)
    setResult(null)
    setMode('choose')
  }

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80 p-4">
      <div className="card-elevated w-full max-w-lg p-6 space-y-5 border border-border rounded-xl shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-text-primary">
              Definí tu perfil de inversor
            </h2>
            <p className="text-xs text-text-muted mt-1">
              Hola <span className="font-medium text-text-secondary">{username}</span>, antes
              de continuar necesitamos saber tu perfil para adaptar las recomendaciones.
            </p>
          </div>
          <button
            onClick={logout}
            title="Cerrar sesión"
            className="p-1.5 rounded-md hover:bg-elevated text-text-muted hover:text-red-400 transition-colors shrink-0"
          >
            <LogOut size={14} />
          </button>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}

        {/* Modo: elección directa */}
        {mode === 'choose' && (
          <div className="space-y-2">
            {(['conservador', 'moderado', 'agresivo'] as const).map(p => {
              const info = PROFILE_INFO[p]
              const Icon = info.icon
              return (
                <button
                  key={p}
                  disabled={saving}
                  onClick={() => submit(p)}
                  className="w-full text-left flex items-start gap-3 p-3 rounded-lg border border-border
                             hover:border-accent hover:bg-elevated/50 transition-colors disabled:opacity-50"
                >
                  <div
                    className="w-8 h-8 rounded-md flex items-center justify-center shrink-0"
                    style={{ backgroundColor: `${info.color}20`, color: info.color }}
                  >
                    <Icon size={16} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-text-primary">{info.label}</p>
                    <p className="text-xs text-text-muted mt-0.5">{info.desc}</p>
                  </div>
                </button>
              )
            })}

            <button
              disabled={saving}
              onClick={() => { setMode('test'); setAnswers([]); setStep(0) }}
              className="w-full text-left flex items-start gap-3 p-3 rounded-lg border border-dashed border-border
                         hover:border-accent hover:bg-elevated/50 transition-colors disabled:opacity-50"
            >
              <div className="w-8 h-8 rounded-md flex items-center justify-center shrink-0
                              bg-accent/10 text-accent">
                <HelpCircle size={16} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text-primary">No lo sé — hacer test del inversor</p>
                <p className="text-xs text-text-muted mt-0.5">
                  {QUESTIONS.length} preguntas rápidas para clasificarte automáticamente.
                </p>
              </div>
            </button>
          </div>
        )}

        {/* Modo: test */}
        {mode === 'test' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between text-xs">
              <button
                onClick={() => {
                  if (step === 0) { resetTest(); return }
                  setStep(step - 1)
                  setAnswers(answers.slice(0, -1))
                }}
                className="flex items-center gap-1 text-text-muted hover:text-text-primary transition-colors"
              >
                <ChevronLeft size={12} /> Atrás
              </button>
              <span className="text-text-muted font-mono">
                {step + 1} / {QUESTIONS.length}
              </span>
            </div>

            {/* Progress bar */}
            <div className="h-1 bg-elevated rounded-full overflow-hidden">
              <div
                className="h-full bg-accent transition-all"
                style={{ width: `${((step + 1) / QUESTIONS.length) * 100}%` }}
              />
            </div>

            <p className="text-sm font-medium text-text-primary">
              {QUESTIONS[step].q}
            </p>

            <div className="space-y-2">
              {QUESTIONS[step].options.map((opt, i) => (
                <button
                  key={i}
                  onClick={() => handleAnswer(opt.pts)}
                  className="w-full text-left p-3 rounded-lg border border-border text-xs
                             text-text-secondary hover:border-accent hover:bg-elevated/50
                             hover:text-text-primary transition-colors"
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Modo: resultado del test */}
        {mode === 'result' && result && (() => {
          const info = PROFILE_INFO[result]
          const Icon = info.icon
          return (
            <div className="space-y-4">
              <div className="flex flex-col items-center text-center gap-3 py-4">
                <div
                  className="w-16 h-16 rounded-full flex items-center justify-center"
                  style={{ backgroundColor: `${info.color}20`, color: info.color }}
                >
                  <Icon size={28} />
                </div>
                <div>
                  <p className="text-xs text-text-muted uppercase tracking-wide">Tu perfil es</p>
                  <p className="text-xl font-semibold text-text-primary mt-1">{info.label}</p>
                </div>
                <p className="text-xs text-text-secondary max-w-sm">{info.desc}</p>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={resetTest}
                  disabled={saving}
                  className="flex-1 h-9 rounded-lg bg-elevated hover:bg-elevated/80 text-text-secondary text-xs
                             disabled:opacity-50"
                >
                  Repetir test
                </button>
                <button
                  onClick={() => submit(result)}
                  disabled={saving}
                  className="flex-1 h-9 rounded-lg bg-accent hover:bg-accent/90 text-white text-xs font-medium
                             disabled:opacity-50"
                >
                  {saving ? 'Guardando...' : 'Confirmar perfil'}
                </button>
              </div>
            </div>
          )
        })()}
      </div>
    </div>
  )
}
