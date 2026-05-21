
import datetime
from typing import Optional, Set, Tuple
from models import MonthSchedule, ShiftType

# 근무 유형별 색상·텍스트
SHIFT_STYLE = {
    ShiftType.DAY:       {"bg": "#4A90D9", "fg": "#fff"},
    ShiftType.NIGHT:     {"bg": "#1A237E", "fg": "#fff"},
    ShiftType.OFF:       {"bg": "#90A4AE", "fg": "#fff"},
    ShiftType.HOLIDAY:   {"bg": "#43A047", "fg": "#fff"},
    ShiftType.ANNUAL:    {"bg": "#66BB6A", "fg": "#fff"},
    ShiftType.SPECIAL:   {"bg": "#FFA726", "fg": "#fff"},
    ShiftType.EDUCATION: {"bg": "#AB47BC", "fg": "#fff"},
}


def _cell_td(shift: Optional[ShiftType], violation: bool = False) -> str:
    if shift is None:
        return '<td style="width:30px;text-align:center;font-size:12px;">-</td>'
    st     = SHIFT_STYLE.get(shift, {"bg": "#eee", "fg": "#333"})
    border = "2px solid #e53935" if violation else "1px solid #e0e0e0"
    return (
        f'<td style="width:30px;text-align:center;background:{st["bg"]};'
        f'color:{st["fg"]};font-weight:bold;border:{border};'
        f'border-radius:3px;font-size:12px;padding:1px 0;">'
        f'{shift.value}</td>'
    )


def render_grid_html(
    result: MonthSchedule,
    show_stats: bool = False,
    highlight_cells: Set[Tuple[str, int]] = None,
) -> str:
    highlight_cells = highlight_cells or set()
    days = list(range(1, result.num_days + 1))

    # 날짜 헤더
    def day_color(d):
        wd = datetime.date(result.year, result.month, d).weekday()
        return "#e53935" if wd == 6 else ("#1565C0" if wd == 5 else "#444")

    hdr = '<th style="min-width:80px;padding:3px 6px;text-align:left;">이름</th>'
    hdr += "".join(
        f'<th style="width:30px;text-align:center;color:{day_color(d)};font-size:11px;">{d}</th>'
        for d in days
    )
    if show_stats:
        hdr += '<th style="min-width:130px;padding:3px 6px;">통계</th>'

    rows = [f"<tr>{hdr}</tr>"]

    # 직원 행
    for emp in result.employees:
        cells = (
            f'<td style="padding:3px 6px;font-weight:bold;'
            f'white-space:nowrap;font-size:13px;">{emp.name}</td>'
        )
        for d in days:
            shift     = result.get_shift(emp.name, d)
            violation = (emp.name, d) in highlight_cells
            cells    += _cell_td(shift, violation)
        if show_stats:
            st = result.get_stats(emp.name)
            cells += (
                f'<td style="padding:3px 8px;font-size:11px;white-space:nowrap;color:#555;">'
                f'주{st["주간"]} 야{st["야간"]} 비{st["비번"]} '
                f'휴{st["휴일"]} 연{st["연가"]} 교{st["교육"]}</td>'
            )
        rows.append(f"<tr>{cells}</tr>")

    # 합계 행
    if show_stats:
        for shift_type, label in [(ShiftType.DAY, "주간합"), (ShiftType.NIGHT, "야간합")]:
            cells = f'<td style="padding:3px 6px;font-weight:bold;font-size:12px;">{label}</td>'
            for d in days:
                cnt   = sum(1 for e in result.employees
                            if result.get_shift(e.name, d) == shift_type)
                color = "#e53935" if (shift_type == ShiftType.DAY and cnt == 3) else "#333"
                cells += (
                    f'<td style="width:30px;text-align:center;font-size:11px;'
                    f'font-weight:bold;color:{color};">{cnt}</td>'
                )
            if show_stats:
                cells += "<td></td>"
            rows.append(f'<tr style="background:#f9f9f9;">{cells}</tr>')

    body = "\n".join(rows)
    return f"""
    <div style="overflow-x:auto;font-family:'Courier New',monospace;margin-top:8px;">
      <table style="border-collapse:separate;border-spacing:2px;min-width:max-content;">
        <thead style="position:sticky;top:0;background:#fff;z-index:1;">
          <tr>{hdr}</tr>
        </thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def render_calendar_html(result: MonthSchedule, emp_name: str) -> str:
    first_wd = datetime.date(result.year, result.month, 1).weekday()  # 0=월

    # 빈 셀 + 날짜 셀
    cells = ["<td></td>"] * first_wd
    for day in range(1, result.num_days + 1):
        shift  = result.get_shift(emp_name, day)
        wd     = datetime.date(result.year, result.month, day).weekday()
        dc     = "#e53935" if wd == 6 else ("#1565C0" if wd == 5 else "#333")
        if shift:
            st  = SHIFT_STYLE.get(shift, {"bg": "#eee", "fg": "#333"})
            tag = (
                f'<div style="background:{st["bg"]};color:{st["fg"]};'
                f'border-radius:4px;font-weight:bold;padding:1px 4px;'
                f'font-size:13px;margin-top:2px;">{shift.value}</div>'
            )
        else:
            tag = ""
        cells.append(
            f'<td style="width:52px;height:52px;text-align:center;vertical-align:top;'
            f'border:1px solid #eee;border-radius:6px;padding:3px;">'
            f'<div style="font-size:11px;color:{dc};">{day}</div>{tag}</td>'
        )

    # 7열 분할
    dow_labels = ["월","화","수","목","금",
                  '<span style="color:#1565C0">토</span>',
                  '<span style="color:#e53935">일</span>']
    header = "".join(
        f'<th style="width:52px;text-align:center;padding:4px;font-size:12px;">{d}</th>'
        for d in dow_labels
    )
    rows = [f"<tr>{header}</tr>"]
    for i in range(0, len(cells), 7):
        chunk = cells[i:i+7]
        while len(chunk) < 7:
            chunk.append("<td></td>")
        rows.append(f"<tr>{''.join(chunk)}</tr>")

    return (
        "<div style='font-family:sans-serif;margin-top:8px;'>"
        f"<table style='border-collapse:separate;border-spacing:3px;'>{''.join(rows)}</table>"
        "</div>"
    )
