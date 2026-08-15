export interface Health {
  status: string
  version: string
}

export interface PluginSummary {
  id: string
  version: string
  active: boolean
  provides: string[]
  requires: string[]
}

export interface TaskSummary {
  id: string
  title: string
  stage: 'draft' | 'stable'
  available: boolean
  missing_services: string[]
  missing_artifacts: string[]
}

export interface PublicEvent {
  id: number
  ts: string
  kind: string
  source: string
  run_id: string | null
  payload: Record<string, unknown>
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json() as Promise<T>
}
