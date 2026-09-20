export type Role = 'admin' | 'member'

export interface User {
  id: number
  username: string
  role: Role
  is_active: boolean
  member_id: number | null
  member_name: string | null
  created_at: string
  last_login_at: string | null
}

export interface Account {
  user_id: number
  username: string
  is_active: boolean
  last_login_at: string | null
}

export interface Member {
  id: number
  display_name: string
  aliases: string[]
  note: string
  active: boolean
  sort_order: number
  account: Account | null
}

export interface Invite {
  token: string
  url: string
  expires_at: string
}

export interface InviteInfo {
  member_name: string
  expires_at: string
}

export type Difficulty = '简单' | '一般' | '困难'
export const DIFFICULTIES: Difficulty[] = ['简单', '一般', '困难']

export interface EventSettings {
  soft_daily_limit: number
  hard_daily_limit: number
  merge_visit_gap: number
  free_gap: number
  eval_durations: number[]
  eval_min_contiguous: number
  same_song_different_days: boolean
  difficulty_templates: Record<Difficulty, number[]>
  stage_time_limit: number
}

export type EventStatus = 'preparing' | 'collecting' | 'scheduling' | 'published' | 'closed'
export const STATUS_LABELS: Record<EventStatus, string> = {
  preparing: '筹备中',
  collecting: '填报中',
  scheduling: '排程中',
  published: '已发布',
  closed: '已结束',
}

export interface RehearsalEvent {
  id: number
  name: string
  performance_date: string
  formal_start_date: string
  formal_end_date: string
  eval_date: string
  formal_day_count: number
  timezone: string
  slot_minutes: number
  day_start_hour: number
  day_end_hour: number
  slots_per_day: number
  status: EventStatus
  settings: EventSettings
  member_count: number
  song_count: number
  session_count: number
  created_at: string
  updated_at: string
}

export interface EventMember {
  member_id: number
  display_name: string
  active: boolean
  availability_submitted_at: string | null
}

export interface MemberBrief {
  id: number
  display_name: string
}

export interface Song {
  id: number
  event_id: number
  code: string
  name: string
  difficulty: Difficulty
  members: MemberBrief[]
  session_plan: number[] | null
  durations: number[]
  session_count: number
  sort_order: number
}

export interface SongList {
  songs: Song[]
  warnings: string[]
  total_sessions: number
}
