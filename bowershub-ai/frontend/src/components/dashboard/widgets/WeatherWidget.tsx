import type { WidgetProps } from '../WidgetRegistry'

interface CurrentWeather {
  temp_f: number
  feels_like_f: number
  conditions: string
  humidity: number
  wind_speed_mph: number
}

interface ForecastDay {
  date: string
  max_temp_f: number
  min_temp_f: number
  conditions: string
  chance_of_rain: number
}

function getConditionIcon(conditions: string): string {
  const lower = conditions.toLowerCase()
  if (lower.includes('sunny') || lower.includes('clear')) return '☀️'
  if (lower.includes('partly cloudy')) return '⛅'
  if (lower.includes('cloudy') || lower.includes('overcast')) return '☁️'
  if (lower.includes('rain') || lower.includes('drizzle')) return '🌧️'
  if (lower.includes('thunder') || lower.includes('storm')) return '⛈️'
  if (lower.includes('snow')) return '❄️'
  if (lower.includes('fog') || lower.includes('mist')) return '🌫️'
  return '🌤️'
}

function formatDayName(dateStr: string): string {
  const date = new Date(dateStr + 'T12:00:00')
  const today = new Date()
  today.setHours(12, 0, 0, 0)
  const diffDays = Math.round((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24))
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Tomorrow'
  return date.toLocaleDateString('en-US', { weekday: 'short' })
}

export default function WeatherWidget({ data }: WidgetProps) {
  if (!data) return <div style={{ color: 'var(--color-text-muted)' }} className="text-sm py-4 text-center">No data</div>

  const weather = data as { error?: string | boolean | null; current?: CurrentWeather; forecast?: ForecastDay[] }

  if (weather.error) return <div style={{ color: 'var(--color-text-muted)' }} className="text-sm py-4 text-center">{String(weather.error)}</div>

  const current = weather.current
  const forecast = weather.forecast || []

  if (!current) return <div style={{ color: 'var(--color-text-muted)' }} className="text-sm py-4 text-center">No weather data</div>

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <span className="text-3xl">{getConditionIcon(current.conditions)}</span>
        <div className="flex-1">
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold" style={{ color: 'var(--color-text)' }}>{Math.round(current.temp_f)}°F</span>
            <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Feels {Math.round(current.feels_like_f)}°</span>
          </div>
          <p className="mt-0.5 text-sm" style={{ color: 'var(--color-text)' }}>{current.conditions}</p>
          <div className="mt-1 flex items-center gap-3 text-xs" style={{ color: 'var(--color-text-muted)' }}>
            <span>💧 {current.humidity}%</span>
            <span>💨 {current.wind_speed_mph} mph</span>
          </div>
        </div>
      </div>

      {forecast.length > 0 && (
        <div className="grid gap-2 pt-3" style={{ borderTop: '1px solid var(--color-border)', gridTemplateColumns: `repeat(${Math.min(forecast.length, 3)}, 1fr)` }}>
          {forecast.slice(0, 3).map((day) => (
            <div key={day.date} className="flex flex-col items-center gap-1 rounded-md px-2 py-2 text-center">
              <span className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>{formatDayName(day.date)}</span>
              <span className="text-lg">{getConditionIcon(day.conditions)}</span>
              <div className="flex items-center gap-1 text-xs">
                <span className="font-medium" style={{ color: 'var(--color-text)' }}>{Math.round(day.max_temp_f)}°</span>
                <span style={{ color: 'var(--color-text-muted)' }}>{Math.round(day.min_temp_f)}°</span>
              </div>
              {day.chance_of_rain > 0 && <span className="text-xs" style={{ color: 'var(--color-accent)' }}>🌧 {day.chance_of_rain}%</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
