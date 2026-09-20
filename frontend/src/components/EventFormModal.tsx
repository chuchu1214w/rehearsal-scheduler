import { useMutation } from '@tanstack/react-query'
import { App as AntApp, Collapse, DatePicker, Form, Input, InputNumber, Modal, Switch } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useEffect } from 'react'

import { api, errorMessage } from '../api/client'
import type { Difficulty, EventSettings, RehearsalEvent } from '../api/types'
import { DIFFICULTIES } from '../api/types'
import { fmtDate, hourLabel, parsePlan } from '../utils'

interface Values {
  name: string
  performance_date: Dayjs
  formal_start_date: Dayjs
  timezone: string
  day_start_hour: number
  day_end_hour: number
  soft_daily_limit: number
  hard_daily_limit: number
  merge_visit_gap: number
  free_gap: number
  eval_durations: string
  eval_min_contiguous: number
  same_song_different_days: boolean
  tpl_简单: string
  tpl_一般: string
  tpl_困难: string
  stage_time_limit: number
}

const DEFAULT_SETTINGS: EventSettings = {
  soft_daily_limit: 8,
  hard_daily_limit: 8,
  merge_visit_gap: 1,
  free_gap: 1,
  eval_durations: [3, 2],
  eval_min_contiguous: 2,
  same_song_different_days: true,
  difficulty_templates: { 简单: [2, 2], 一般: [3, 2, 2], 困难: [3, 3, 3] },
  stage_time_limit: 90,
}

function toValues(ev?: RehearsalEvent): Values {
  const s = ev?.settings ?? DEFAULT_SETTINGS
  return {
    name: ev?.name ?? '',
    performance_date: ev ? dayjs(ev.performance_date) : dayjs().add(30, 'day'),
    formal_start_date: ev ? dayjs(ev.formal_start_date) : dayjs().add(1, 'day'),
    timezone: ev?.timezone ?? 'Asia/Seoul',
    day_start_hour: ev?.day_start_hour ?? 10,
    day_end_hour: ev?.day_end_hour ?? 23,
    soft_daily_limit: s.soft_daily_limit,
    hard_daily_limit: s.hard_daily_limit,
    merge_visit_gap: s.merge_visit_gap,
    free_gap: s.free_gap,
    eval_durations: s.eval_durations.join(','),
    eval_min_contiguous: s.eval_min_contiguous,
    same_song_different_days: s.same_song_different_days,
    tpl_简单: s.difficulty_templates.简单.join(','),
    tpl_一般: s.difficulty_templates.一般.join(','),
    tpl_困难: s.difficulty_templates.困难.join(','),
    stage_time_limit: s.stage_time_limit,
  }
}

function toBody(v: Values) {
  const templates = {} as Record<Difficulty, number[]>
  for (const d of DIFFICULTIES) templates[d] = parsePlan(v[`tpl_${d}` as const]) ?? []
  return {
    name: v.name,
    performance_date: v.performance_date.format('YYYY-MM-DD'),
    formal_start_date: v.formal_start_date.format('YYYY-MM-DD'),
    timezone: v.timezone,
    day_start_hour: v.day_start_hour,
    day_end_hour: v.day_end_hour,
    settings: {
      soft_daily_limit: v.soft_daily_limit,
      hard_daily_limit: v.hard_daily_limit,
      merge_visit_gap: v.merge_visit_gap,
      free_gap: v.free_gap,
      eval_durations: parsePlan(v.eval_durations) ?? [],
      eval_min_contiguous: v.eval_min_contiguous,
      same_song_different_days: v.same_song_different_days,
      difficulty_templates: templates,
      stage_time_limit: v.stage_time_limit,
    },
  }
}

const planRule = { pattern: /^\s*\d+(\s*[,，、]\s*\d+)*\s*$/, message: '用逗号分隔的小时数,如 3,2' }

interface Props {
  open: boolean
  initial?: RehearsalEvent
  onClose: () => void
  onSaved: (ev: RehearsalEvent) => void
}

export function EventFormModal({ open, initial, onClose, onSaved }: Props) {
  const [form] = Form.useForm<Values>()
  const { message } = AntApp.useApp()
  const perf = Form.useWatch('performance_date', form)
  const start = Form.useWatch('formal_start_date', form)
  const dayStart = Form.useWatch('day_start_hour', form)
  const dayEnd = Form.useWatch('day_end_hour', form)

  useEffect(() => {
    if (open) form.setFieldsValue(toValues(initial))
  }, [open, initial, form])

  const mutation = useMutation({
    mutationFn: (v: Values) =>
      initial
        ? api<RehearsalEvent>(`/api/events/${initial.id}`, { method: 'PATCH', json: toBody(v) })
        : api<RehearsalEvent>('/api/events', { method: 'POST', json: toBody(v) }),
    onSuccess: (ev) => {
      message.success('已保存')
      onSaved(ev)
    },
    onError: (err) => message.error(errorMessage(err)),
  })

  const formalEnd = perf ? perf.subtract(2, 'day') : null
  const evalDate = perf ? perf.subtract(1, 'day') : null
  const dayCount = perf && start ? formalEnd!.diff(start, 'day') + 1 : null
  const slots = typeof dayStart === 'number' && typeof dayEnd === 'number' ? dayEnd - dayStart : null

  return (
    <Modal
      open={open}
      title={initial ? '编辑活动' : '新建活动'}
      onCancel={onClose}
      onOk={() => form.submit()}
      okText="保存"
      cancelText="取消"
      confirmLoading={mutation.isPending}
      width={560}
    >
      <Form<Values> form={form} layout="vertical" onFinish={(v) => mutation.mutate(v)} requiredMark={false}>
        <Form.Item name="name" label="活动名称" rules={[{ required: true, message: '请输入名称' }]}>
          <Input placeholder="例如 2026 秋季路演" maxLength={120} />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item name="performance_date" label="演出日期" rules={[{ required: true, message: '请选择' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="formal_start_date" label="排练开始日期" rules={[{ required: true, message: '请选择' }]}>
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </div>
        <div className="rs-muted" style={{ marginTop: -8, marginBottom: 16 }}>
          {formalEnd && evalDate ? (
            <>
              正规排练:{start ? fmtDate(start.format('YYYY-MM-DD')) : '?'} ~ {fmtDate(formalEnd.format('YYYY-MM-DD'))}
              {dayCount !== null && (dayCount > 0 ? `(${dayCount} 天)` : '(区间为空:开始日期需不晚于演出前两天)')}
              <br />
              全员评估日:{fmtDate(evalDate.format('YYYY-MM-DD'))}(演出前一天,不排其他排练)
            </>
          ) : (
            '选择日期后会显示排练区间与评估日'
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
          <Form.Item name="day_start_hour" label="每天最早" rules={[{ required: true }]}>
            <InputNumber<number> min={0} max={23} style={{ width: '100%' }} formatter={(v) => hourLabel(Number(v ?? 0))} parser={(v) => Number((v ?? '').split(':')[0])} />
          </Form.Item>
          <Form.Item name="day_end_hour" label="每天最晚" rules={[{ required: true }]}>
            <InputNumber<number> min={1} max={24} style={{ width: '100%' }} formatter={(v) => hourLabel(Number(v ?? 0))} parser={(v) => Number((v ?? '').split(':')[0])} />
          </Form.Item>
          <Form.Item name="timezone" label="时区" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        </div>
        {slots !== null && (
          <div className="rs-muted" style={{ marginTop: -8, marginBottom: 16 }}>
            {slots > 0 ? `每天 ${slots} 个时间格(1 小时一格)` : '结束时间必须晚于开始时间'}
          </div>
        )}
        <Collapse
          size="small"
          items={[
            {
              key: 'advanced',
              label: '规则参数(可稍后修改)',
              children: (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <Form.Item name="soft_daily_limit" label="单日软上限(小时)" tooltip="超过时计入“单日超时最少”目标">
                      <InputNumber min={1} max={24} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="hard_daily_limit" label="单日硬上限(小时)" tooltip="绝对不允许超过">
                      <InputNumber min={1} max={24} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="merge_visit_gap" label="往返合并间隔(小时)" tooltip="两场相隔不超过此值视为同一次到场">
                      <InputNumber min={0} max={12} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="free_gap" label="免罚空档(小时)" tooltip="当天空档不超过此值不计惩罚">
                      <InputNumber min={0} max={12} style={{ width: '100%' }} />
                    </Form.Item>
                    <Form.Item name="eval_durations" label="评估场时长(小时)" rules={[planRule]} tooltip="允许的时长,按总到场人时最多选择">
                      <Input placeholder="3,2" />
                    </Form.Item>
                    <Form.Item name="eval_min_contiguous" label="评估场最少连续到场(小时)">
                      <InputNumber min={1} max={12} style={{ width: '100%' }} />
                    </Form.Item>
                  </div>
                  <Form.Item name="same_song_different_days" label="同一曲目的场次必须在不同日期" valuePropName="checked">
                    <Switch />
                  </Form.Item>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                    {DIFFICULTIES.map((d) => (
                      <Form.Item key={d} name={`tpl_${d}`} label={`难度「${d}」场次`} rules={[{ required: true, message: '必填' }, planRule]}>
                        <Input placeholder="3,2,2" />
                      </Form.Item>
                    ))}
                  </div>
                  <Form.Item name="stage_time_limit" label="求解每阶段时限(秒)">
                    <InputNumber min={5} max={600} style={{ width: '100%' }} />
                  </Form.Item>
                </>
              ),
            },
          ]}
        />
      </Form>
    </Modal>
  )
}
