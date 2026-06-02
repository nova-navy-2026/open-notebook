import apiClient from './client'

export interface NavigationRouteRequest {
  location_a: string
  location_b: string
  surface?: 'global_chat' | 'notebook_chat'
  run_id?: string
  session_id?: string
  notebook_id?: string
  model_id?: string
}

export interface NavigationRouteResponse {
  distance_km?: number
  duration_min?: number
  estimated_time?: string
  route_preference?: string
  source?: string
  start_point?: { query?: string; resolved_address?: string; lat: number; lon: number }
  end_point?: { query?: string; resolved_address?: string; lat: number; lon: number }
  [key: string]: unknown
}

export const navigationApi = {
  route: async (data: NavigationRouteRequest) => {
    const response = await apiClient.post<NavigationRouteResponse>(
      '/navigation/route',
      data,
    )
    return response.data
  },
}
