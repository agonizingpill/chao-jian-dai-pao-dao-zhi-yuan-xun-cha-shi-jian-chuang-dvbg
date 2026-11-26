from collections import deque

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.records import get, insert, need
from domain.learning import phase_distance
from domain.lead_shifts_model import lead_shifts
from domain.patrol_windows_model import patrol_windows
from domain.rework_batches_model import rework_batches
from domain.trail_notices_model import trail_notices
from domain.trail_routes_model import trail_routes

UNSIGNED_STATE = '已领班'
COST_SCALE = 1_000_000


def _closures(conn, route_code):
    rows = conn.execute(select(trail_notices).where(
        trail_notices.c.route == route_code,
        trail_notices.c.status == '封闭')).mappings().all()
    return [dict(row) for row in rows]


def _overlaps(begins, until, opens, closes):
    """两个半开区间 [begins, until) 与 [opens, closes) 是否相交。"""
    return begins < closes and until > opens


def _window_blocked(window, closures):
    return any(_overlaps(ban['begins'], ban['until'], window['opens'], window['closes'])
               for ban in closures)


def _candidate_windows(conn, route, phase, earliest, closures, original_codes):
    rows = conn.execute(select(patrol_windows).where(
        patrol_windows.c.route == route,
        patrol_windows.c.phase == phase,
        patrol_windows.c.opens > earliest)).mappings().all()
    windows = [dict(row) for row in rows]
    return [w for w in windows
            if w['code'] not in original_codes and not _window_blocked(w, closures)]


def _distance(target, candidate):
    """沿用历史相似性的圆周距离算子：单位圆弦长 + 窗口时长差/180。"""
    chord = phase_distance(target['opening_minute'], candidate['opening_minute'])
    return round(chord + abs(target['minutes'] - candidate['minutes']) / 180, 6)


def _min_cost_assignment(shift_count, window_count, capacities, edges):
    """最小费用最大流：源点->班次->候选窗->汇点。

    先保证安置班次最多（最大流），再在同等安置量下取总圆周距离最小。
    费用统一放大为整数，避免浮点比较误差。
    """
    source = 0
    shift_nodes = list(range(1, shift_count + 1))
    window_nodes = list(range(shift_count + 1, shift_count + window_count + 1))
    sink = shift_count + window_count + 1
    size = sink + 1

    graph = [[] for _ in range(size)]

    def add_edge(u, v, capacity, cost):
        graph[u].append([v, capacity, cost, len(graph[v])])
        graph[v].append([u, 0, -cost, len(graph[u]) - 1])

    for i in shift_nodes:
        add_edge(source, i, 1, 0)
    for j, capacity in enumerate(capacities):
        add_edge(window_nodes[j], sink, capacity, 0)
    for shift_index, window_index, distance in edges:
        add_edge(shift_nodes[shift_index], window_nodes[window_index], 1,
                 round(distance * COST_SCALE))

    flow = 0
    total_cost = 0
    while True:
        dist = [None] * size
        dist[source] = 0
        previous = [None] * size
        queue = deque([source])
        in_queue = [False] * size
        in_queue[source] = True
        while queue:
            u = queue.popleft()
            in_queue[u] = False
            for edge_index, (v, capacity, cost, _) in enumerate(graph[u]):
                if capacity <= 0:
                    continue
                candidate = dist[u] + cost
                if dist[v] is None or candidate < dist[v]:
                    dist[v] = candidate
                    previous[v] = (u, edge_index)
                    if not in_queue[v]:
                        queue.append(v)
                        in_queue[v] = True
        if dist[sink] is None:
            break
        v = sink
        while v != source:
            u, edge_index = previous[v]
            edge = graph[u][edge_index]
            edge[1] -= 1
            reverse = graph[v][edge[3]]
            reverse[1] += 1
            v = u
        flow += 1
        total_cost += dist[sink]

    pairing = {}
    for shift_index, node in enumerate(shift_nodes):
        for v, capacity, _, reverse_index in graph[node]:
            reverse_edge = graph[v][reverse_index]
            if v in window_nodes and reverse_edge[1] > 0:
                pairing[shift_index] = v - shift_count - 1
    return flow, total_cost / COST_SCALE, pairing


def build_plan(conn, route_code):
    """锁路线后重算整组调班方案；所有并发签认都以本方案为准。"""
    route = get(conn, trail_routes, route_code, lock=True)
    need(route['active'], '路线已停用，不能安排调班')
    closures = _closures(conn, route_code)

    shift_rows = [dict(row) for row in conn.execute(select(lead_shifts).where(
        lead_shifts.c.state == UNSIGNED_STATE)).mappings().all()]
    affected = []
    for shift in shift_rows:
        window = get(conn, patrol_windows, shift['window'])
        if window['route'] != route_code:
            continue
        if _window_blocked(window, closures):
            affected.append({'shift': shift, 'window': window})
    need(bool(affected), '该路线当前没有受封路影响且未签到的领班班次')

    phases = sorted({item['window']['phase'] for item in affected})
    need(len(phases) == 1, '受影响班次的潮窗相位不一致，无法整组同相位调班')
    phase = phases[0]
    earliest = min(item['window']['opens'] for item in affected)
    original_codes = {item['window']['code'] for item in affected}
    candidates = _candidate_windows(conn, route_code, phase, earliest, closures, original_codes)
    need(bool(candidates), '没有同路同相位且不与封路重叠的后续潮窗')

    occupied = {}
    for w in candidates:
        used = conn.execute(select(lead_shifts.c.code).where(
            lead_shifts.c.window == w['code'],
            lead_shifts.c.state != '已交回')).all()
        occupied[w['code']] = len(used)
    capacities = [max(0, route['max_leads'] - occupied[w['code']]) for w in candidates]

    edges = []
    distance_table = []
    for shift_index, item in enumerate(affected):
        row = []
        for window_index, candidate in enumerate(candidates):
            distance = _distance(item['window'], candidate)
            row.append(distance)
            if capacities[window_index] > 0:
                edges.append((shift_index, window_index, distance))
        distance_table.append(row)

    placed, total_distance, pairing = _min_cost_assignment(
        len(affected), len(candidates), capacities, edges)

    assignments = []
    for shift_index, item in enumerate(affected):
        if shift_index in pairing:
            window_index = pairing[shift_index]
            target = candidates[window_index]
            assignments.append({
                'shift': item['shift']['code'],
                'lead': item['shift']['lead'],
                'from_window': item['window']['code'],
                'to_window': target['code'],
                'to_opens': target['opens'],
                'to_closes': target['closes'],
                'distance': distance_table[shift_index][window_index],
            })
    assigned_shifts = {row['shift'] for row in assignments}
    unplaced = [{
        'shift': item['shift']['code'],
        'lead': item['shift']['lead'],
        'window': item['window']['code'],
        'reason': '后续同相位潮窗剩余名额不足，保留原班次',
    } for item in affected if item['shift']['code'] not in assigned_shifts]
    assignments.sort(key=lambda row: (row['to_opens'], row['to_window'], row['shift']))

    return {
        'route': route_code,
        'phase': phase,
        'affected_count': len(affected),
        'placed_count': placed,
        'total_distance': round(total_distance, 6),
        'closures': [{'code': ban['code'], 'begins': ban['begins'], 'until': ban['until']}
                     for ban in closures],
        'candidates': [{'window': w['code'], 'opens': w['opens'], 'closes': w['closes'],
                        'remaining': capacities[j]} for j, w in enumerate(candidates)],
        'assignments': assignments,
        'unplaced': unplaced,
    }


def preview_plan(conn, user, data):
    return build_plan(conn, data.route)


def confirm_rework(conn, user, data):
    # 路线行锁串行化同一路线的签到、领班登记、封路变更与调班签认。
    route = get(conn, trail_routes, data.route, lock=True)
    need(route['active'], '路线已停用，不能安排调班')

    existing = conn.execute(select(rework_batches).where(
        rework_batches.c.request_key == data.request_key)).mappings().first()
    if existing is not None:
        # 同次签认重试：直接回传既有批次，不再次换班、不重复占位。
        return {'code': existing['code'], 'request_key': existing['request_key'],
                'replayed': True, 'plan': existing['plan']}

    # 依据在预览后发生变化时，以锁内最新数据重算后再确认。
    plan = build_plan(conn, data.route)
    need(plan['route'] == data.route, '调班路线与重算结果不一致')

    for row in plan['assignments']:
        conn.execute(lead_shifts.update().where(
            lead_shifts.c.code == row['shift']).values(window=row['to_window']))
    # 原名额随窗口更新一起释放，整组换班与释放处于同一事务，要么全成要么全不成。
    try:
        saved = insert(conn, rework_batches, code=data.code, request_key=data.request_key,
                       route=data.route, plan=plan)
    except IntegrityError:
        # 同键并发的落败方：唯一约束兜底，回读既有批次当作重试处理，不重复占位。
        existing = conn.execute(select(rework_batches).where(
            rework_batches.c.request_key == data.request_key)).mappings().first()
        need(existing is not None, '同次签认冲突，请用原请求号重试')
        return {'code': existing['code'], 'request_key': existing['request_key'],
                'replayed': True, 'plan': existing['plan']}
    return {'code': saved['code'], 'request_key': saved['request_key'],
            'replayed': False, 'plan': saved['plan']}
