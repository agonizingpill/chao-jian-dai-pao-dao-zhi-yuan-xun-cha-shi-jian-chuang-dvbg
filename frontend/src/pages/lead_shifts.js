        import {workspace} from '../workspace.js';
        import {el, display} from '../dom.js';
        import {request} from '../api.js';
        import {dataView, status} from '../widgets.js';

        const reworkColumns = [
          {name: 'code', label: '调班批次'},
          {name: 'request_key', label: '签认请求号'},
          {name: 'route', label: '路线'},
        ];

        function planTable(plan) {
          const candidateRows = plan.candidates.map(c =>
            el('tr', {}, el('td', {}, c.window), el('td', {}, c.opens + '–' + c.closes.slice(11, 16)),
               el('td', {}, String(c.remaining))));
          const moveRows = plan.assignments.map(a =>
            el('tr', {}, el('td', {}, a.shift), el('td', {}, a.lead),
               el('td', {}, a.from_window), el('td', {}, a.to_window),
               el('td', {}, a.to_opens), el('td', {}, display(a.distance))));
          const unplaced = plan.unplaced.length
            ? el('div', {class:'rework-unplaced'}, el('h4', {}, '保留原班次 ' + plan.unplaced.length + ' 个'),
                el('ul', {}, plan.unplaced.map(u => el('li', {}, u.shift + '（' + u.lead + '）' + u.window + ' · ' + u.reason))))
            : el('p', {class:'rework-ok'}, '受影响班次已全部安置。');
          return el('div', {class:'rework-plan'},
            el('h4', {}, '调班方案 · ' + plan.route + ' · ' + plan.phase),
            el('p', {}, '受影响未签到 ' + plan.affected_count + ' 个，安置 ' + plan.placed_count
               + ' 个，总圆周距离 ' + display(plan.total_distance)),
            el('h5', {}, '后续同路同相潮窗（已排除封路重叠）'),
            el('div', {class:'scroll'}, el('table', {},
              el('thead', {}, el('tr', {}, el('th', {}, '潮窗'), el('th', {}, '时段 UTC+8'),
                el('th', {}, '剩余名额'))),
              el('tbody', {}, candidateRows))),
            el('h5', {}, '整组换班明细'),
            el('div', {class:'scroll'}, el('table', {},
              el('thead', {}, el('tr', {}, el('th', {}, '领班号'), el('th', {}, '带队员'),
                el('th', {}, '原潮窗'), el('th', {}, '调往潮窗'), el('th', {}, '新窗开始'),
                el('th', {}, '圆周距离'))),
              el('tbody', {}, moveRows))),
            unplaced);
        }

        function reworkHost(panel) {
          const grid = panel.closest('.work');
          let host = grid.querySelector('.rework-output');
          if (!host) {
            host = el('section', {class:'ledger rework-output', 'aria-label':'调班方案'});
            grid.append(host);
          }
          return host;
        }

        function renderPlan(panel, data) {
          reworkHost(panel).replaceChildren(planTable(data));
        }

        function renderConfirm(panel, data) {
          reworkHost(panel).replaceChildren(el('div', {class:'rework-plan confirmed'},
            el('h4', {}, (data.replayed ? '同次签认重试（回放既有批次）· ' : '整组调班已签认 · ')
               + data.code),
            planTable(data.plan)));
        }

        const page = {
  "title": "志愿者领班和检查点签收",
  "module": "带队与签到",
  "caption": "带队与签到",
  "detail": "带队员按名额和潮窗领班，到指定入口时签到，再由负责人签回。封路撞窗时可整组调往同路同相的后续潮窗：先按剩余名额安置尽量多的班次，再取总圆周距离最小的排法。",
  "path": "/lead_shifts",
  "columns": [
    {
      "name": "code",
      "label": "编号"
    },
    {
      "name": "window",
      "label": "关联潮窗"
    },
    {
      "name": "lead",
      "label": "带队员"
    },
    {
      "name": "contact",
      "label": "队内联络号"
    },
    {
      "name": "on_site",
      "label": "到场时间 UTC+8"
    },
    {
      "name": "checkpoint",
      "label": "签到检查点"
    },
    {
      "name": "state",
      "label": "交接状态"
    }
  ],
  "layout": "stack",
  "view": "table",
  "actions": [
    {
      "name": "assign_lead",
      "label": "确认志愿者领班",
      "path": "/lead_shifts/assign-lead",
      "fields": [
        {
          "name": "code",
          "label": "领班号",
          "kind": "text",
          "initial": "SHIFT-QA"
        },
        {
          "name": "window",
          "label": "潮窗编号",
          "kind": "text",
          "initial": "WINDOW-QA"
        },
        {
          "name": "lead",
          "label": "带队员",
          "kind": "text",
          "initial": "温河"
        },
        {
          "name": "contact",
          "label": "队内联络号",
          "kind": "text",
          "initial": "TD-030"
        }
      ],
      "help": "检查路线开放状态和窗口中的剩余名额。",
      "roles": [
        "operator",
        "reviewer"
      ],
      "success": "已写入"
    },
    {
      "name": "check_in",
      "label": "检查点签到",
      "path": "/lead_shifts/check-in",
      "fields": [
        {
          "name": "shift",
          "label": "领班号",
          "kind": "text",
          "initial": "SHIFT-QA"
        },
        {
          "name": "checkpoint",
          "label": "扫码检查点",
          "kind": "text",
          "initial": "GATE-EAST"
        },
        {
          "name": "arrived_at",
          "label": "到场时间 · YYYY-MM-DD HH:MM",
          "kind": "text",
          "initial": "2090-12-15 00:11"
        }
      ],
      "help": "记录本次演练的检查点扫码时间。",
      "roles": [
        "operator",
        "reviewer"
      ],
      "success": "已写入"
    },
    {
      "name": "hand_back",
      "label": "负责人签回班次",
      "path": "/lead_shifts/hand-back",
      "fields": [
        {
          "name": "shift",
          "label": "领班号",
          "kind": "text",
          "initial": "SHIFT-QA"
        }
      ],
      "help": "签回后旧记录仍可读取，名额释放。",
      "roles": [
        "reviewer"
      ],
      "success": "已写入"
    },
    {
      "name": "rework_plan",
      "label": "预览封路整组调班",
      "path": "/lead_shifts/rework-plan",
      "fields": [
        {
          "name": "route",
          "label": "受封路路线编号",
          "kind": "text",
          "initial": "TR-A"
        }
      ],
      "help": "为受影响且未签到的领班查找同路同相、不与封路重叠的后续潮窗，按剩余名额先求最大安置量，再取总圆周距离最小的排法。仅预览不占位。",
      "roles": [
        "operator",
        "reviewer"
      ],
      "success": "方案已生成",
      "render": renderPlan
    },
    {
      "name": "rework_confirm",
      "label": "签认整组调班",
      "path": "/lead_shifts/rework-confirm",
      "fields": [
        {
          "name": "code",
          "label": "调班批次号",
          "kind": "text",
          "initial": "RW-QA"
        },
        {
          "name": "route",
          "label": "受封路路线编号",
          "kind": "text",
          "initial": "TR-A"
        },
        {
          "name": "request_key",
          "label": "本次签认请求号（重试保持不变）",
          "kind": "text",
          "initial": "REQ-QA-1"
        }
      ],
      "help": "签认时以最新封路、签到和名额重新计算再确认；整组换班与原名额释放同一事务生效。同一请求号重复提交只回放既有批次，不重复占位。",
      "roles": [
        "operator",
        "reviewer"
      ],
      "success": "已签认",
      "render": renderConfirm
    }
  ]
};

        export const {title} = page;
        export const key = "lead_shifts";
        export async function render(root, role) {
          await workspace(root, role, page);
          try {
            const rows = await request('/rework_batches');
            const panel = el('section', {class:'ledger rework-ledger', 'aria-label':'整组调班批次'},
              el('h2', {}, '整组调班批次'),
              rows.length ? dataView(rows, reworkColumns, 'table')
                : status('暂无调班批次。可先在右侧预览封路整组调班。'));
            root.querySelector('.ledger').after(panel);
          } catch (error) {
            root.append(status(error.message, 'error'));
          }
        }
