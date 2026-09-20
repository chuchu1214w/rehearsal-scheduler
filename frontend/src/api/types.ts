export type Role = 'admin' | 'member'

export interface User {
  id: number
  username: string
  role: Role
  is_active: boolean
  must_change_password: boolean
  member_id: number | null
  member_name: string | null
  created_at: string
  last_login_at: string | null
}

export interface Account {
  user_id: number
  username: string
  is_active: boolean
  must_change_password: boolean
  last_login_at: string | null
}

export interface Credentials {
  member_id: number
  display_name: string
  username: string
  password: string
  copy_text: string
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
export type StepState = 'done' | 'current' | 'todo'

export interface Step {
  no: number
  key: string
  label: string
  state: StepState
  summary: string
}

export interface RehearsalEvent {
  id: number
  name: string
  performance_date: string
  formal_start_date: string
  formal_end_date: string
  eval_date: string
  formal_day_count: number
  availability_deadline: string | null
  days_until_performance: number
  timezone: string
  slot_minutes: number
  day_start_hour: number
  day_end_hour: number
  slots_per_day: number
  status: EventStatus
  settings: EventSettings
  member_count: number
  account_count: number
  submitted_count: number
  song_count: number
  session_count: number
  rule_count: number
  current_step: number
  steps: Step[]
  created_at: string
  updated_at: string
}

export interface EventMember {
  member_id: number
  display_name: string
  active: boolean
  note: string
  account: Account | null
  availability_submitted_at: string | null
  availability_filled_days: number
  availability_filled_by: 'member' | 'admin' | null
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

export type RuleType =
  | 'member_song_max_absent'
  | 'member_song_max_attendance'
  | 'blocked_day'
  | 'blocked_slots'
  | 'max_sessions_per_date'
  | 'fixed_session'
  | 'focus_member'

export interface Rule {
  id: number
  event_id: number
  type: RuleType
  params: Record<string, unknown>
  hardness: 'hard' | 'soft'
  enabled: boolean
  sentence: string
  sort_order: number
}

export interface RuleTypeInfo {
  type: RuleType
  hardness: 'hard' | 'soft'
  template: string
  fields: string[]
  description: string
}

export interface Availability {
  event_id: number
  member_id: number
  display_name: string
  dates: string[]
  eval_date: string
  slots_per_day: number
  day_start_hour: number
  days: Record<string, string>
  filled_days: number
  filled_by: 'member' | 'admin' | null
  submitted_at: string | null
  deadline: string | null
  past_deadline: boolean
}

export interface Heat {
  dates: string[]
  slots_per_day: number
  day_start_hour: number
  member_count: number
  submitted_count: number
  heat: Record<string, number[]>
}

export interface PrecheckItem {
  key: string
  ok: boolean
  level: 'ok' | 'warn' | 'error'
  label: string
  detail: string
}

export interface Precheck {
  items: PrecheckItem[]
  can_solve: boolean
  warnings: number
}
