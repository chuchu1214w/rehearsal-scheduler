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
  max_absent_percent: number
  absent_per_member_song: number
  min_full_per_song: number
  difficulty_templates: Record<Difficulty, number[]>
  stage_time_limit: number
  objectives: string[]
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
  conflict_count: number
  created_at: string
  updated_at: string
}

export interface EventMember {
  member_id: number
  display_name: string
  active: boolean
  note: string // 仅管理员可见,成员端为 ''
  account: Account | null // 仅管理员可见,成员端为 null
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
  warning?: string | null
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
  /** 成员昵称 -> 日期 -> 每格状态('0' 没空 / '1' 有空 / '2' 尽量避开) */
  availability: Record<string, Record<string, string>>
  songs: { code: string; name: string; members: string[]; durations: number[] }[]
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
  base_version_id: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  elapsed_seconds: number | null
}

/** 求解包的诊断报告(键为中文,与命令行输出一致) */
export interface Diagnosis {
  无候选任务?: string[]
  部分排程?: { 版本号: number; 未排: string[] }
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
  /** 给人看的「第几场」:同一首按日期排序后的序号 */
  task_no: number | null
  /** 场次在版本内的固定编号(复制成草稿后用来对应同一场) */
  task_key?: number | null
  date: string
  weekday: string
  start_slot: number
  duration_slots: number
  time: string
  members: MemberBrief[]
  absent: MemberBrief[]
  attendance: Record<string, string> | null
  locked: boolean
  location: string
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
  parent_version_id: number | null
  status: 'draft' | 'published' | 'archived'
  locked_count: number
  level_used: number | null
  exact_optimum: boolean
  objective_values: Record<string, number>
  validation_errors: string[]
  metrics: Record<string, number>
  skipped_songs: string[]
  session_count: number
  created_at: string
  published_at: string | null
  /** 修改次数;提交修改时带上,对不上说明期间被改过 */
  revision: number
}

/** 一条冲突(硬约束问题):涉及的场次在日历上标红 */
export interface ScheduleIssue {
  code: string
  message: string
  session_ids: number[]
}

export interface ScheduleOperation {
  id: number
  seq: number
  kind: 'move' | 'swap' | 'lock' | 'resize' | 'add' | 'delete'
  summary: string
  undone: boolean
  created_at: string
}

export interface ScheduleVersionDetail extends ScheduleVersion {
  sessions: ScheduleSession[]
  member_stats: MemberStat[]
  stage_records: StageRecord[]
  /** 以下仅管理员接口返回 */
  issues?: ScheduleIssue[]
  /** 不影响发布的提醒,如场数 / 时长与曲目方案不同 */
  notices?: string[]
  history?: ScheduleOperation[]
  can_undo?: boolean
  can_redo?: boolean
}

// ---------- 发布 / 日历订阅(M4) ----------
export interface PublishedSchedule extends ScheduleVersionDetail {
  event_name: string
  performance_date: string
  formal_start_date: string
  formal_end_date: string
  eval_date: string
  day_start_hour: number
  day_end_hour: number
  my_member_id: number | null
}

export interface CalendarInfo {
  url: string
  webcal_url: string
}

// ---------- 排练表调整(M5) ----------
export interface EditResult {
  version: ScheduleVersionDetail
  warnings: string[]
  forked: boolean
  /** 这次修改新引入的冲突(草稿暂存,发布前必须解决) */
  new_issues?: string[]
}

export type DiffChange = 'added' | 'removed' | 'moved' | 'changed'

export interface DiffItem {
  change: DiffChange
  kind: 'formal' | 'evaluation'
  before: ScheduleSession | null
  after: ScheduleSession | null
}

export interface ScheduleDiff {
  base_id: number
  base_no: number
  against_id: number
  against_no: number
  items: DiffItem[]
  affected_members: MemberBrief[]
  summary: string
}

export interface Conflict {
  session: ScheduleSession
  member: MemberBrief
  hours: string[]
}

export interface Conflicts {
  version_id: number
  version_no: number
  status: string
  items: Conflict[]
  members: MemberBrief[]
}

// ---------- 通知(M6) ----------
export interface Notification {
  id: number
  type: string
  title: string
  body: string
  link: string
  event_id: number | null
  created_at: string
  read_at: string | null
}

export interface RemindResult {
  notified: string[]
  without_account: string[]
  copy_text: string
}

export interface Objective {
  key: string
  label: string
  default_on: boolean
}

/** AI 调度员(开发文档 §5.11) */
export interface AdvisorChange {
  kind: 'add_rule' | 'edit_rule' | 'disable_rule' | 'setting' | 'session_plan'
  kind_label: string
  description: string
  reason: string
}

export interface AdvisorRun {
  id: number
  event_id: number
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  progress: string
  log: { kind: 'info' | 'think' | 'text' | 'tool' | 'result' | 'done'; text: string; at: number }[]
  proposal: {
    summary: string
    changes: AdvisorChange[]
    song_plans?: { song: string; song_name: string; current: string; suggested: string; plan: number[]; note: string }[]
    check: { 全部排完?: boolean; 使用层级?: string; 缺席场次?: number; 最多能排?: string; 排不上的场次?: string[]; 说明?: string; 注意?: string; 数据问题?: string[] }
  } | null
  applied: number[]
  error: string | null
  created_at: string
  finished_at: string | null
  elapsed_seconds: number | null
  cost_usd: number | null
}
