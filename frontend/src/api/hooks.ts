import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, errorMessage } from './client'
import type { Availability, EventMember, Heat, Member, Precheck, RehearsalEvent, Rule, RuleTypeInfo, SongList } from './types'
import { useToast } from '../ui/Toast'

export const keys = {
  events: ['events'] as const,
  event: (id: number) => ['event', id] as const,
  members: (id: number) => ['event-members', id] as const,
  songs: (id: number) => ['songs', id] as const,
  rules: (id: number) => ['rules', id] as const,
  ruleTypes: ['rule-types'] as const,
  roster: ['roster'] as const,
  availability: (id: number, memberId: number) => ['availability', id, memberId] as const,
  heat: (id: number) => ['heat', id] as const,
}

export function useEvents() {
  return useQuery({ queryKey: keys.events, queryFn: () => api<RehearsalEvent[]>('/api/events') })
}

export function useEvent(id: number) {
  return useQuery({ queryKey: keys.event(id), queryFn: () => api<RehearsalEvent>(`/api/events/${id}`), enabled: Number.isFinite(id) })
}

export function useEventMembers(id: number) {
  return useQuery({ queryKey: keys.members(id), queryFn: () => api<EventMember[]>(`/api/events/${id}/members`), enabled: Number.isFinite(id) })
}

export function useSongs(id: number) {
  return useQuery({ queryKey: keys.songs(id), queryFn: () => api<SongList>(`/api/events/${id}/songs`), enabled: Number.isFinite(id) })
}

export function useRules(id: number) {
  return useQuery({ queryKey: keys.rules(id), queryFn: () => api<Rule[]>(`/api/events/${id}/rules`), enabled: Number.isFinite(id) })
}

export function useRuleTypes() {
  return useQuery({ queryKey: keys.ruleTypes, queryFn: () => api<RuleTypeInfo[]>('/api/rule-types'), staleTime: Infinity })
}

export function useRoster(enabled = true) {
  return useQuery({ queryKey: keys.roster, queryFn: () => api<Member[]>('/api/members'), enabled })
}

export function useAvailability(eventId: number, memberId: number) {
  return useQuery({
    queryKey: keys.availability(eventId, memberId),
    queryFn: () => api<Availability>(`/api/events/${eventId}/availability/${memberId}`),
    enabled: Number.isFinite(eventId) && Number.isFinite(memberId),
  })
}

export function useHeat(eventId: number) {
  return useQuery({ queryKey: keys.heat(eventId), queryFn: () => api<Heat>(`/api/events/${eventId}/availability/overview`) })
}

export function usePrecheck(eventId: number) {
  return useQuery({ queryKey: ['precheck', eventId], queryFn: () => api<Precheck>(`/api/events/${eventId}/precheck`, { method: 'POST' }) })
}

/** 让某个演出相关的所有查询失效(演出、人员、曲目、要求、进度) */
export function useInvalidateEvent() {
  const qc = useQueryClient()
  return (id: number) => {
    void qc.invalidateQueries({ queryKey: keys.events })
    void qc.invalidateQueries({ queryKey: keys.event(id) })
    void qc.invalidateQueries({ queryKey: keys.members(id) })
    void qc.invalidateQueries({ queryKey: keys.songs(id) })
    void qc.invalidateQueries({ queryKey: keys.rules(id) })
    void qc.invalidateQueries({ queryKey: keys.heat(id) })
    void qc.invalidateQueries({ queryKey: ['precheck', id] })
    void qc.invalidateQueries({ queryKey: keys.roster })
  }
}

/** 带默认错误提示的 mutation 包装 */
export function useAction<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>, onSuccess?: (result: TResult, vars: TVars) => void) {
  const { error } = useToast()
  return useMutation({
    mutationFn: fn,
    onSuccess,
    onError: (err) => error(errorMessage(err)),
  })
}
