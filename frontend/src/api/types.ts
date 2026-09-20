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
  latest_version_no: number | null
  published_version_no: number | null
  latest_job_status: JobStatus | null
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

// ---------- 排程 / 排练表 ----------
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'infeasible' | 'failed' | 'cancelled'

export interface StageRecord {
  key: string
  label: string
  value: number | null
  status: string
}

export interface SolveJob {
  id: number
  event_id: number
  status: JobStatus
  progress: string
  stage_records: StageRecord[]
  attempts: { 层级: string; 状态: string; 说明?: string }[]
  ladder_level_used: number | null
  skipped_songs: string[]
  diagnosis: Diagnosis | null
  summary: string
  error: string | null
  version_id: number | null
  only_ready_songs: boolean
  created_at: string
  started_at: string | null
  finished_at: string | null
  elapsed_seconds: number | null
}

/** 求解包的诊断报告(键为中文,与命令行输出一致) */
export interface Diagnosis {
  无候选任务?: string[]
  最大覆盖?: { 状态: string; 最多可排场次: number; 要求场次: number }
  各曲缺口?: { 曲目: string; 曲目名: string; 要求场次: number; 单曲最多可排: number; 单曲缺口: number; 全局方案已排: number; 全局缺口: number }[]
  只差一人的时段?: { 曲目: string; 曲目名: string; 时长: number; 日期: string; 星期: string; 时间段: string; 只差成员: string; 需开放小时数: number; 需开放的格: string[] }[]
  最小调整建议?: {
    可行: boolean
    状态?: string
    受影响成员数: number
    调整小时数: number
    调整: { 成员: string; 日期: string; 星期: string; 需开放的格: string }[]
    放宽后示例: { 任务: string; 曲目: string; 日期: string; 星期?: string; 时间段: string }[]
  }
  评估场?: {
    可行: boolean
    评估日: string
    每格可到人数: Record<string, number>
    成员总数: number
    可行窗口数: number
    最接近的窗口: { 时长: number; 时间段: string; 开始格: number; 缺少人数: number; 需开放小时数: number; 阻塞成员: Record<string, number> }[]
  }
}

export interface ScheduleSession {
  id: number
  kind: 'formal' | 'evaluation'
  song_id: number | null
  song_code: string | null
  song_name: string
  task_no: number | null
  date: string
  weekday: string
  start_slot: number
  duration_slots: number
  time: string
  members: MemberBrief[]
  absent: MemberBrief[]
  attendance: Record<string, string> | null
  locked: boolean
}

export interface MemberStat {
  member_id: number
  display_name: string
  sessions: number
  hours: number
  days: number
  absent: number
  eval_time: string | null
}

export interface ScheduleVersion {
  id: number
  event_id: number
  version_no: number
  source: string
  status: 'draft' | 'published' | 'archived'
  level_used: number | null
  exact_optimum: boolean
  objective_values: Record<string, number>
  validation_errors: string[]
  metrics: Record<string, number>
  skipped_songs: string[]
  session_count: number
  created_at: string
  published_at: string | null
}

export interface ScheduleVersionDetail extends ScheduleVersion {
  sessions: ScheduleSession[]
  member_stats: MemberStat[]
  stage_records: StageRecord[]
}
